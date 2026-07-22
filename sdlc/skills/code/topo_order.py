"""Deterministic scheduler for sdlc-code: loads the task graph (docs/TASKS.json
+ every docs/TASKS__*.json), overlays the execution ledger, and prints the
execution schedule — topologically sorted with the test-first ready-queue
policy — plus ring boundaries, blocked/stale/failed tasks, and the --next
resolution. The skill quotes this tool's output instead of hand-computing
order, the same way sdlc-task quotes count_work_units.py.

Run from the project root:

    python sdlc/skills/code/topo_order.py
    python sdlc/skills/code/topo_order.py --scope backend-api --state .claude/skills-state/sdlc-code.state.yaml
    python sdlc/skills/code/topo_order.py --next
    python sdlc/skills/code/topo_order.py --fingerprints
    python sdlc/skills/code/topo_order.py --emit build-sandbox/TSK-004 build-sandbox/TSK-006
    python sdlc/skills/code/topo_order.py --overlap build-sandbox/TSK-004 build-sandbox/TSK-006

The `--emit` mode is the **worker-packet builder**: it prints the verbatim task
object(s) for the requested qualified id(s), each joined with a
`requirement_context` slice (the task's FR/NFR/WKF/ACR ids — from `implements`,
`implements_workflows`, and `test_spec.covers` — resolved to their one-line
PRD statements). The manager builds a wave from the schedule, then calls `--emit`
for exactly those ids and pipes the result into each worker's brief — so neither
the manager nor a worker ever reads a whole (potentially hundreds-of-KB) TASKS
shard or the whole PRD to assemble one task's context.

Scheduling policy (see references/execution-loop.md):
    Among READY tasks (all depends_on satisfied), a ready `test` task always
    wins — so tests run the moment the implementation they exercise lands.
    Non-test ties break by (same component as previous task, build_order
    position of the owning file, numeric tsk id).

Task states (ledger overlay):
    done     — ledger says done and the task's fingerprint still matches.
    stale    — ledger says done but the task JSON changed since (re-confirm).
    failed / skipped — from the ledger; their dependents are BLOCKED.
    pending  — everything else (scheduled).

SCHEDULER<->VALIDATOR CONTRACT (K1/SK-19): this scheduler and the task skill's
validate_schema.py must always AGREE on what makes a graph schedulable. Both
enforce exactly two blocking graph rules — depends_on resolution against the
union node set, and union-graph acyclicity. A new blocking graph rule lands in
BOTH tools in the same change, or is version-gated on the artifact's declared
tasks_container_version. (Historical counter-example this contract exists to
prevent: an ungated priority-monotonic gate once hard-failed graphs this
scheduler ran fine; D2 deleted it.)

Exit codes:
    0 — schedule printed (there may be blocked/stale items; read the output).
    1 — graph error: dangling depends_on ref or a dependency cycle (a validated
        'complete' artifact cannot legally contain either — re-run the task
        validator).
    2 — no task files found / unreadable JSON or YAML.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required.\nInstall with:  pip install pyyaml", file=sys.stderr)
    sys.exit(2)

TSK_RE = re.compile(r"^TSK-\d{3,}$")

# A PRD requirement/workflow definition line: ``- "FR-015: <statement>"`` (also
# NFR-### under non_functional_requirements, WKF-### under use_cases, and
# ACR-### under success_metrics.acceptance_criteria — the family a test task's
# ``test_spec.covers`` may name). The id sits right after an opening quote and
# is followed by ``:`` — which is what separates a definition line from a mere
# ``FR-091 (…)`` prose reference.
_REQ_RE = re.compile(r'"(?P<id>(?:FR|NFR|WKF|ACR)-\d+):\s*(?P<text>.*)"\s*$')


def fingerprint(task: Dict[str, Any]) -> str:
    blob = json.dumps(task, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def tsk_num(tsk_id: str) -> int:
    m = re.search(r"(\d+)$", tsk_id)
    return int(m.group(1)) if m else 0


class Graph:
    def __init__(self) -> None:
        self.tasks: Dict[str, Dict[str, Any]] = {}       # qualified id -> task object
        self.deps: Dict[str, List[str]] = {}             # qualified id -> qualified deps
        self.file_of: Dict[str, str] = {}                # qualified id -> file key
        self.build_order: List[str] = []
        self.errors: List[str] = []

    def qualify(self, ref: str, home: str) -> str:
        return ref if "/" in ref else f"{home}/{ref}"


def load_graph(docs: Path) -> Graph:
    g = Graph()
    files: Dict[str, Path] = {}
    system = docs / "TASKS.json"
    if system.is_file():
        files["TASKS"] = system
    for p in sorted(docs.glob("TASKS__*.json")):
        files[p.stem.replace("TASKS__", "", 1)] = p
    if not files:
        print(f"[FAIL] no TASKS.json / TASKS__*.json found under {docs}", file=sys.stderr)
        sys.exit(2)

    for key, path in files.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[FAIL] cannot read {path}: {e}", file=sys.stderr)
            sys.exit(2)
        if key == "TASKS":
            g.build_order = list(data.get("build_order") or [])
        for t in data.get("tasks", []):
            tid = t.get("tsk_id", "")
            if not TSK_RE.match(tid):
                g.errors.append(f"{path.name}: malformed tsk_id {tid!r}")
                continue
            q = f"{key}/{tid}"
            g.tasks[q] = t
            g.file_of[q] = key
            g.deps[q] = [g.qualify(d, key) for d in (t.get("depends_on") or [])]

    for q, deps in g.deps.items():
        for d in deps:
            if d not in g.tasks:
                g.errors.append(f"{q}: depends_on {d!r} does not resolve to any loaded task")
    return g


def load_ledger(state_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if not state_path:
        return {}
    if not state_path.is_file():
        return {}
    try:
        data = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"[FAIL] cannot read state file {state_path}: {e}", file=sys.stderr)
        sys.exit(2)
    return data.get("tasks") or {}


def classify(g: Graph, ledger: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Map every qualified id to done|stale|failed|skipped|pending."""
    state: Dict[str, str] = {}
    for q, task in g.tasks.items():
        entry = ledger.get(q)
        if not entry:
            state[q] = "pending"
            continue
        st = entry.get("status")
        if st == "done":
            recorded = entry.get("task_fingerprint")
            state[q] = "done" if recorded == fingerprint(task) else "stale"
        elif st in ("failed", "skipped"):
            state[q] = st
        else:  # in_progress or unknown -> Phase-1 reconcile decides; schedule it
            state[q] = "pending"
    return state


def schedule(g: Graph, state: Dict[str, str], scope: Optional[str]) -> Tuple[List[str], Dict[str, List[str]], List[str]]:
    """Return (ordered pending tasks in scope, blocked -> blocking causes, cycle members)."""
    satisfied = {q for q, s in state.items() if s in ("done", "stale")}
    dead = {q for q, s in state.items() if s in ("failed", "skipped")}

    # transitive blocking through pending tasks whose ancestry is dead
    blocked: Dict[str, List[str]] = {}
    changed = True
    while changed:
        changed = False
        for q, s in state.items():
            if s != "pending" or q in blocked:
                continue
            causes = [d for d in g.deps[q] if d in dead or d in blocked]
            if causes:
                blocked[q] = causes
                changed = True

    in_scope = lambda q: scope is None or g.file_of[q] == scope  # noqa: E731

    file_rank = {cid: i for i, cid in enumerate(g.build_order)}
    file_rank.setdefault("TASKS", -1)  # system scaffold work sorts first by default

    pend = [q for q, s in state.items() if s == "pending" and q not in blocked]
    remaining: Set[str] = set(pend)
    ordered: List[str] = []
    prev_component: Optional[str] = None

    def ready(q: str) -> bool:
        return all(d in satisfied for d in g.deps[q])

    while remaining:
        candidates = [q for q in remaining if ready(q)]
        if not candidates:
            # cycle among pending tasks, or waiting on out-of-ledger blocked deps
            stuck = sorted(remaining)
            return [x for x in ordered if in_scope(x)], blocked, stuck

        def sort_key(q: str) -> Tuple:
            t = g.tasks[q]
            comp = t.get("component_ref")
            return (
                t.get("kind") != "test",                       # test tasks first
                comp != prev_component if comp else True,      # component locality
                file_rank.get(g.file_of[q], len(file_rank)),   # build_order position
                tsk_num(t.get("tsk_id", "")),
            )

        nxt = min(candidates, key=sort_key)
        remaining.discard(nxt)
        satisfied.add(nxt)
        ordered.append(nxt)
        prev_component = g.tasks[nxt].get("component_ref") or prev_component

    return [q for q in ordered if in_scope(q)], blocked, []


def resolve_next(g: Graph, state: Dict[str, str]) -> str:
    """--next: the next incomplete unit in build_order semantics."""
    def has_pending(key: str) -> bool:
        return any(g.file_of[q] == key and state[q] == "pending" for q in g.tasks)

    # (a) system tasks that are READY right now and touch no container tasks
    #     (the repo-scaffold head that everything else hangs off)
    sys_head = [
        q for q in g.tasks
        if g.file_of[q] == "TASKS" and state[q] == "pending"
        and all(g.file_of[d] == "TASKS" for d in g.deps[q])
        and all(state.get(d) in ("done", "stale") for d in g.deps[q])
    ]
    if sys_head:
        return "unit: system head (repo scaffold / system tasks with no container deps)"
    for cid in g.build_order:
        if has_pending(cid):
            return f"unit: container {cid!r}"
    for key in sorted({k for k in g.file_of.values() if k != "TASKS"}):
        if key not in g.build_order and has_pending(key):
            return f"unit: container {key!r} (not in build_order — check TASKS.json)"
    if has_pending("TASKS"):
        return "unit: system tail (integration / e2e test tasks)"
    return "nothing pending — the graph is fully executed"


def load_requirements(docs: Path) -> Dict[str, str]:
    """Map every FR/NFR/WKF/ACR id to its one-line PRD statement.

    PRD requirement families are single-line ``"<id>: <statement>"`` strings, so
    this is a cheap grep — never a whole-PRD parse. Returns an empty map when
    ``PRD.yaml`` is absent (the caller emits tasks without requirement context).
    """
    prd = docs / "PRD.yaml"
    reqs: Dict[str, str] = {}
    if not prd.is_file():
        return reqs
    try:
        text = prd.read_text(encoding="utf-8")
    except OSError:
        return reqs
    for line in text.splitlines():
        m = _REQ_RE.search(line)
        if m is not None:
            # First definition wins; a later prose line can't overwrite it.
            reqs.setdefault(m.group("id"), " ".join(m.group("text").split()))
    return reqs


def _path_parts(p: str) -> Tuple[str, ...]:
    return tuple(x for x in str(p).replace("\\", "/").strip("/").split("/") if x not in ("", "."))


def paths_overlap(a: str, b: str) -> bool:
    """Path-aware overlap: equal paths collide, and a directory entry contains
    every path beneath it ("tests/" overlaps "tests/unit/test_x.py") — segment
    prefix containment, mirroring the task validator's _path_within_any."""
    pa, pb = _path_parts(a), _path_parts(b)
    n = min(len(pa), len(pb))
    return n > 0 and pa[:n] == pb[:n]


def check_overlap(g: Graph, raw_ids: List[str]) -> int:
    """--overlap: pairwise path-aware target_files check for a candidate wave."""
    resolved: List[Tuple[str, List[str]]] = []
    missing: List[str] = []
    for raw in raw_ids:
        qid = resolve_qid(g, raw)
        if qid is None:
            missing.append(raw)
            continue
        resolved.append((qid, [str(p) for p in (g.tasks[qid].get("target_files") or [])]))
    if missing:
        print(
            f"[overlap] unresolved task id(s): {', '.join(missing)} - "
            f"not in the loaded graph (check the qualified id)",
            file=sys.stderr,
        )
        return 1
    hits: List[Tuple[str, str, str, str]] = []
    for i in range(len(resolved)):
        for j in range(i + 1, len(resolved)):
            qa, fa = resolved[i]
            qb, fb = resolved[j]
            for a in fa:
                for b in fb:
                    if paths_overlap(a, b):
                        hits.append((qa, a, qb, b))
    for qa, a, qb, b in hits:
        print(f"OVERLAP  {qa} '{a}'  <->  {qb} '{b}'")
    if hits:
        print(f"[overlap] {len(hits)} overlapping pair(s) - these tasks cannot share a wave")
        return 1
    print(f"disjoint - {len(resolved)} task(s) can share a wave (path-aware check)")
    return 0


def resolve_qid(g: Graph, raw: str) -> Optional[str]:
    """Resolve a user-supplied id to a loaded qualified id, or None.

    Accepts the canonical qualified form (``build-sandbox/TSK-004``,
    ``TASKS/TSK-001``), tolerates a ``TASKS__``-prefixed file part
    (``TASKS__build-sandbox/TSK-004``), and a bare ``TSK-004`` when it is unique
    across the loaded graph.
    """
    if raw in g.tasks:
        return raw
    if raw.startswith("TASKS__"):
        alt = raw.replace("TASKS__", "", 1)
        if alt in g.tasks:
            return alt
    if TSK_RE.match(raw):
        hits = [q for q in g.tasks if q.rsplit("/", 1)[-1] == raw]
        if len(hits) == 1:
            return hits[0]
    return None


def emit_packets(g: Graph, docs: Path, raw_ids: List[str]) -> int:
    """Print a self-contained worker packet per requested task, as one JSON array.

    Each packet is ``{qualified_id, task, requirement_context}`` where
    ``requirement_context`` maps the task's ``implements`` (FR/NFR),
    ``implements_workflows`` (WKF), and ``test_spec.covers`` (FR/NFR/ACR — a
    test task's requirement ids live there, not in ``implements``) to their
    PRD statements — so a worker builds from the packet alone, without reading
    the (large) TASKS shard or PRD.
    """
    reqs = load_requirements(docs)
    packets: List[Dict[str, Any]] = []
    missing: List[str] = []
    for raw in raw_ids:
        qid = resolve_qid(g, raw)
        if qid is None:
            missing.append(raw)
            continue
        task = g.tasks[qid]
        req_ids: List[str] = []
        for r in (
            list(task.get("implements") or [])
            + list(task.get("implements_workflows") or [])
            # A test task's requirement ids live in test_spec.covers, not
            # implements — without this, every test packet ships an empty
            # requirement_context (SK-25/K2).
            + list((task.get("test_spec") or {}).get("covers") or [])
        ):
            if r not in req_ids:
                req_ids.append(r)
        rc = {r: reqs[r] for r in req_ids if r in reqs}
        packet: Dict[str, Any] = {
            "qualified_id": qid,
            "task": task,
            "requirement_context": rc,
        }
        unresolved = [r for r in req_ids if r not in reqs]
        if unresolved:
            # Named but not found in PRD (stale ref / PRD absent) — flag so the
            # worker can fall back to an on-demand PRD read for just these ids.
            packet["requirement_context_unresolved"] = unresolved
        packets.append(packet)
    print(json.dumps(packets, indent=2, ensure_ascii=False))
    if missing:
        print(
            f"[emit] unresolved task id(s): {', '.join(missing)} — "
            f"not in the loaded graph (check the qualified id)",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Print the sdlc-code execution schedule.")
    ap.add_argument("--docs", default="docs", help="Directory holding TASKS*.json (default: docs).")
    ap.add_argument("--state", default=".claude/skills-state/sdlc-code.state.yaml", help="Execution ledger (optional).")
    ap.add_argument("--scope", default=None, help="all (default), TASKS, or a container_id.")
    ap.add_argument("--next", action="store_true", dest="next_", help="Print the --next unit resolution only.")
    ap.add_argument("--fingerprints", action="store_true", help="Print qualified id -> fingerprint and exit.")
    ap.add_argument(
        "--overlap",
        nargs="+",
        metavar="QID",
        help="Pairwise path-aware target_files overlap check for a candidate "
        "wave (a directory entry contains every path beneath it). Exit 0 = "
        "disjoint, 1 = overlapping (or unresolved id).",
    )
    ap.add_argument(
        "--emit",
        nargs="+",
        metavar="QID",
        help="Print the verbatim task object(s) for the given qualified id(s) "
        "(e.g. build-sandbox/TSK-004), each with a requirement_context slice from "
        "PRD — the worker packet builder. Never Read the TASKS file to slice a task.",
    )
    args = ap.parse_args()

    scope = None if args.scope in (None, "all") else args.scope
    g = load_graph(Path(args.docs))

    if args.fingerprints:
        for q in sorted(g.tasks):
            print(f"{q}  {fingerprint(g.tasks[q])}")
        return 0

    if args.emit:
        return emit_packets(g, Path(args.docs), args.emit)

    if args.overlap:
        return check_overlap(g, args.overlap)

    if g.errors:
        for e in g.errors:
            print(f"  [ERR] {e}")
        print("[FAIL] graph errors — re-run: python sdlc/skills/task/validate_schema.py")
        return 1

    if scope and scope not in set(g.file_of.values()):
        print(f"[FAIL] scope {scope!r} matches no loaded task file. Loaded: {sorted(set(g.file_of.values()))}", file=sys.stderr)
        return 2

    ledger = load_ledger(Path(args.state) if args.state else None)
    state = classify(g, ledger)

    if args.next_:
        print(resolve_next(g, state))
        return 0

    ordered, blocked, stuck = schedule(g, state, scope)

    counts: Dict[str, int] = {}
    for q, s in state.items():
        if scope is None or g.file_of[q] == scope:
            counts[s] = counts.get(s, 0) + 1
    print(f"build_order: {g.build_order}")
    print("state: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty")

    # ring boundaries: the last scheduled task of each component / file. A hint —
    # the skill confirms rings against the ledger (blocked/failed tasks may keep
    # a container from truly completing this run).
    last_of_component: Dict[str, str] = {}
    last_of_file: Dict[str, str] = {}
    for q in ordered:
        comp = g.tasks[q].get("component_ref")
        if comp:
            last_of_component[f"{g.file_of[q]}/{comp}"] = q
        last_of_file[g.file_of[q]] = q
    comp_ring_at = {v: k for k, v in last_of_component.items()}
    file_ring_at = {v: k for k, v in last_of_file.items()}

    print(f"\nschedule ({len(ordered)} pending, test-first policy):")
    for q in ordered:
        t = g.tasks[q]
        line = f"  {q}  [{t.get('kind')}]"
        if t.get("target_symbol"):
            line += f"  {t['target_symbol']}"
        if t.get("implements_tests"):
            line += f"  realizes {','.join(t['implements_tests'])}"
        print(line)
        if q in comp_ring_at:
            print(f"    >> component ring: {comp_ring_at[q]}")
        if q in file_ring_at:
            print(f"    >> container ring: {file_ring_at[q]}")

    stale = sorted(q for q, s in state.items() if s == "stale" and (scope is None or g.file_of[q] == scope))
    if stale:
        print("\nstale (task JSON changed since execution — re-confirm at the plan gate):")
        for q in stale:
            print(f"  {q}")

    if blocked:
        print("\nblocked (a dependency failed or was skipped):")
        for q, causes in sorted(blocked.items()):
            if scope is None or g.file_of[q] == scope:
                print(f"  {q}  <- {', '.join(causes)}")

    if stuck:
        print("\n[FAIL] unschedulable pending tasks (dependency cycle, or deps outside the ledger):")
        for q in stuck:
            print(f"  {q}  deps: {', '.join(g.deps[q]) or '(none)'}")
        return 1

    print(f"\n--next would run -> {resolve_next(g, state)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
