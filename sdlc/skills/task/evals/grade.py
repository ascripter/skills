"""Grade subagent outputs for the sdlc-task eval suite.

Usage:
    python sdlc/skills/task/evals/grade.py --iteration 1

For each eval directory under sdlc-task-workspace/iteration-N/, this inspects
test-project/docs/TASKS.json (+ any TASKS__*.json) against the assertions for
that eval, runs the sdlc-task validator for the exit-code check, and writes
per-eval grading.json + a top-level benchmark.md summary.

The task graph is JSON (the one sdlc artifact that is, because it is machine-
generated and machine-consumed); upstream specs are still YAML. The structural
checks here mirror the validator's own semantics — trace-or-defer coverage
(component_ref / implements_tests, deferral via a WRN-NNN naming the id), the
union-graph acyclicity check (the "stitch"), and the system build_order /
provider-before-consumer ordering — so the grader and the validator agree.

grading.json uses the field names the eval viewer depends on: text/passed/evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "sdlc-task-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

TSK_RE = re.compile(r"^TSK-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
TST_RE = re.compile(r"^TST-\d{3,}$", re.IGNORECASE)
FRNFR_RE = re.compile(r"^(?:FR|NFR)-\d+$", re.IGNORECASE)
XREF_RE = re.compile(r"^(?P<scope>[A-Za-z0-9_-]+)/(?P<tsk>TSK-\d{3,})$")
CHANGELOG_RE = re.compile(r"^\d+(?:\.\d+)*\s*\(\d{4}-\d{2}-\d{2}\):\s+.+")

CONTAINER_KINDS = {
    "scaffold", "implementation", "test", "integration", "migration", "config", "chore",
}
SYSTEM_KINDS = {
    "scaffold", "integration", "test", "config", "migration", "deploy-prep", "docs", "chore",
}
INFRA_ARCHETYPES = {
    "primary-database", "secondary-database", "cache", "blob-store", "search-index", "message-bus",
}


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        return {"__parse_error__": str(e)}


def _load_yaml(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(tp: Path) -> Tuple[int, str]:
    """Run the sdlc-task validator anchored at docs/TASKS.json.

    The validator validates the system file plus every sibling TASKS__*.json in
    the same dir, so one anchor covers all modes (the anchor file need not exist;
    only its parent docs dir is used to locate the task files)."""
    docs = tp / "docs"
    if not (docs / "TASKS.json").exists() and not list(docs.glob("TASKS__*.json")):
        return 99, "no TASKS*.json produced"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", "docs/TASKS.json"],
        cwd=tp, capture_output=True, text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _tasks(doc: dict) -> List[dict]:
    return [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]


def _all_match(values, regex: re.Pattern) -> bool:
    return all(isinstance(v, str) and regex.match(v) for v in values)


def _deferred_literals(warnings, ids: Set[str]) -> Set[str]:
    deferred: Set[str] = set()
    for i in ids:
        pat = re.compile(r"\b" + re.escape(i) + r"\b")
        if any(isinstance(w, str) and pat.search(w) for w in (warnings or [])):
            deferred.add(i)
    return deferred


def _changelog_ok(doc: dict) -> bool:
    changelog = (doc.get("metadata") or {}).get("changelog") or []
    return isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )


def _outputs_acceptance_ok(tasks: List[dict]) -> Tuple[bool, str]:
    bad = [t.get("tsk_id") for t in tasks if not t.get("outputs") or not t.get("acceptance")]
    return (not bad), f"tasks missing outputs/acceptance: {bad}" if bad else "all tasks have outputs+acceptance"


def _tsk_ids_ok(tasks: List[dict]) -> Tuple[bool, str]:
    ids = [t.get("tsk_id") for t in tasks]
    ok = all(isinstance(x, str) and TSK_RE.match(x) for x in ids) and len(ids) == len(set(ids))
    return ok, f"tsk_ids={ids}"


# ---------------------------------------------------------------------------
# Upstream loaders (read from the staged test-project so the grader tracks
# whatever the fixtures actually declare).
# ---------------------------------------------------------------------------


def _arch_facts(tp: Path) -> dict:
    """container_ids, testable set, and cross-container calls/depends_on edges."""
    facts = {"container_ids": set(), "testable": set(), "cross_edges": []}
    arch = _load_yaml(tp / "docs" / "ARCH.yaml")
    if not isinstance(arch, dict):
        return facts
    for c in arch.get("containers") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("container_id")
        if not cid:
            continue
        facts["container_ids"].add(cid)
        archetype = (c.get("archetype") or "").strip()
        if (not c.get("external")) and archetype not in INFRA_ARCHETYPES and archetype != "external-service":
            facts["testable"].add(cid)
    for e in arch.get("edges") or []:
        if isinstance(e, dict) and (e.get("type") or "") in ("calls", "depends_on"):
            frm, to = e.get("from"), e.get("to")
            if frm and to and frm != to:
                facts["cross_edges"].append((frm, to))
    return facts


def _arch_component_ids(tp: Path, cid: str) -> Set[str]:
    raw = _load_yaml(tp / "docs" / f"ARCH__{cid}.yaml")
    out: Set[str] = set()
    if not isinstance(raw, dict):
        return out
    for comp in raw.get("components") or []:
        if isinstance(comp, dict) and comp.get("component_id"):
            out.add(comp["component_id"])
    return out


def _arch_allowed_reqs(tp: Path, cid: str) -> Set[str]:
    raw = _load_yaml(tp / "docs" / f"ARCH__{cid}.yaml")
    out: Set[str] = set()
    if not isinstance(raw, dict):
        return out

    def _toks(lst):
        for s in lst or []:
            m = re.match(r"^(?:FR|NFR)-\d+", str(s).strip(), re.IGNORECASE)
            if m:
                out.add(m.group(0).upper())

    _toks(raw.get("implements_requirements"))
    for comp in raw.get("components") or []:
        if isinstance(comp, dict):
            _toks(comp.get("implements_requirements"))
    return out


def _tst_ids(path: Path) -> Set[str]:
    raw = _load_yaml(path)
    out: Set[str] = set()
    if isinstance(raw, dict):
        for t in raw.get("tests") or []:
            if isinstance(t, dict) and t.get("tst_id"):
                out.add(str(t["tst_id"]).upper())
    return out


# ---------------------------------------------------------------------------
# Union-graph acyclicity (the stitch) — mirrors the validator.
# ---------------------------------------------------------------------------


def _graph_acyclic_and_resolved(
    sysm: Optional[dict], containers: List[Tuple[str, dict]]
) -> Tuple[bool, bool, str]:
    """Return (deps_resolve, acyclic, evidence) across the union of task files."""
    nodes: Set[str] = set()
    if sysm:
        for t in _tasks(sysm):
            if t.get("tsk_id"):
                nodes.add(f"TASKS/{t['tsk_id']}")
    for cid, cm in containers:
        for t in _tasks(cm):
            if t.get("tsk_id"):
                nodes.add(f"{cid}/{t['tsk_id']}")

    adj: Dict[str, Set[str]] = {n: set() for n in nodes}
    unresolved: List[str] = []

    def _resolve(scope: str, ref: str) -> Optional[str]:
        ref = str(ref).strip()
        if TSK_RE.match(ref):
            return f"{scope}/{ref}"
        m = XREF_RE.match(ref)
        return f"{m.group('scope')}/{m.group('tsk')}" if m else None

    def _wire(scope: str, tasks: List[dict]) -> None:
        for t in tasks:
            if not t.get("tsk_id"):
                continue
            src = f"{scope}/{t['tsk_id']}"
            for ref in t.get("depends_on") or []:
                tgt = _resolve(scope, ref)
                if tgt is None or tgt not in nodes:
                    unresolved.append(f"{src} -> {ref}")
                elif tgt != src:
                    adj.setdefault(tgt, set()).add(src)

    if sysm:
        _wire("TASKS", _tasks(sysm))
    for cid, cm in containers:
        _wire(cid, _tasks(cm))

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    cyc: List[str] = []

    def _dfs(u: str, stack: List[str]) -> bool:
        color[u] = GRAY
        stack.append(u)
        for v in sorted(adj.get(u, ())):
            if color.get(v, WHITE) == GRAY:
                cyc.extend(stack[stack.index(v):] + [v])
                return True
            if color.get(v, WHITE) == WHITE and _dfs(v, stack):
                return True
        color[u] = BLACK
        stack.pop()
        return False

    acyclic = True
    for n in sorted(adj):
        if color[n] == WHITE and _dfs(n, []):
            acyclic = False
            break

    ev = []
    if unresolved:
        ev.append(f"unresolved depends_on: {unresolved}")
    if not acyclic:
        ev.append("cycle: " + " -> ".join(cyc))
    return (not unresolved), acyclic, ("; ".join(ev) or "all depends_on resolve; union graph acyclic")


# ---------------------------------------------------------------------------
# Shared container coverage assertions (evals 2 and 3).
# ---------------------------------------------------------------------------


def _container_asserts(tp: Path, cid: str, container: dict) -> List[dict]:
    comp_ids = _arch_component_ids(tp, cid)
    allowed = _arch_allowed_reqs(tp, cid)
    cont_tst = _tst_ids(tp / "docs" / f"TEST-STRATEGY__{cid}.yaml")
    tasks = _tasks(container)
    warnings = container.get("task_warnings") or []

    component_refs: Set[str] = set()
    covered_tst: Set[str] = set()
    implements_all: Set[str] = set()
    impl_without_scope = 0
    test_without_tests = 0
    for t in tasks:
        if t.get("component_ref"):
            component_refs.add(t["component_ref"])
        for r in t.get("implements_tests") or []:
            covered_tst.add(str(r).upper())
        for r in t.get("implements") or []:
            implements_all.add(str(r).upper())
        if t.get("kind") == "implementation" and not t.get("component_ref") and not t.get("touches_operations"):
            impl_without_scope += 1
        if t.get("kind") == "test" and not t.get("implements_tests"):
            test_without_tests += 1

    deferred_comp = _deferred_literals(warnings, comp_ids)
    deferred_tst = {x.upper() for x in _deferred_literals(warnings, cont_tst)}

    comp_covered = all((c in component_refs or c in deferred_comp) for c in comp_ids)
    tst_covered = all((t in covered_tst or t in deferred_tst) for t in cont_tst)
    refs_resolve = component_refs.issubset(comp_ids) if comp_ids else True
    no_fr005 = "FR-005" not in implements_all
    impl_resolve = implements_all.issubset(allowed) if allowed else all(FRNFR_RE.match(x) for x in implements_all)
    deps_resolve, acyclic, dep_ev = _graph_acyclic_and_resolved(None, [(cid, container)])
    oa_ok, oa_ev = _outputs_acceptance_ok(tasks)
    tsk_ok, tsk_ev = _tsk_ids_ok(tasks)
    kinds_bad = sorted({t.get("kind") for t in tasks if t.get("kind") not in CONTAINER_KINDS})

    return [
        _assert("Every ARCH__<cid> component is realized by a task (component_ref) or deferred (WRN-NNN)",
                comp_covered, f"components={sorted(comp_ids)}; refs={sorted(component_refs)}; deferred={sorted(deferred_comp)}"),
        _assert("Every TEST-STRATEGY__<cid> test is realized by a task (implements_tests) or deferred",
                tst_covered, f"tst={sorted(cont_tst)}; covered={sorted(covered_tst)}; deferred={sorted(deferred_tst)}"),
        _assert("No task implements FR-005 (owned by digest-worker, not backend-api)", no_fr005,
                f"implements={sorted(implements_all)}"),
        _assert("Every implementation task is scoped (component_ref or touches_operations)",
                impl_without_scope == 0, f"impl_without_scope={impl_without_scope}"),
        _assert("Every component_ref resolves to a real ARCH__<cid> component", refs_resolve,
                f"refs={sorted(component_refs)}; known={sorted(comp_ids)}"),
        _assert("Every `implements` id resolves to the container/component's allowed FR/NFR set", impl_resolve,
                f"implements={sorted(implements_all)}; allowed={sorted(allowed)}"),
        _assert("Every kind:test task has a non-empty implements_tests", test_without_tests == 0,
                f"test_without_tests={test_without_tests}"),
        _assert("depends_on resolve and the container subgraph is acyclic", deps_resolve and acyclic, dep_ev),
        _assert("Every task has non-empty outputs and acceptance", oa_ok, oa_ev),
        _assert("Every tsk_id matches TSK-NNN and is unique", tsk_ok, tsk_ev),
        _assert("Every kind is in the container-kind vocabulary", not kinds_bad, f"off-vocab kinds={kinds_bad}"),
        _assert("Every task_warnings entry matches WRN-NNN", _all_match(warnings, WRN_RE), f"warnings={warnings[:3]}"),
    ]


# ---------------------------------------------------------------------------
# Per-eval graders
# ---------------------------------------------------------------------------


def grade_eval_1(tp: Path) -> List[dict]:
    """system-stitch-and-build-order."""
    sysm = _load_json(tp / "docs" / "TASKS.json")
    rc, vout = _validator_exit(tp)
    if not isinstance(sysm, dict) or "__parse_error__" in sysm:
        return [_assert("docs/TASKS.json exists and is valid JSON", False, str(sysm) if sysm else "missing")]

    meta = sysm.get("metadata") or {}
    tasks = _tasks(sysm)
    warnings = sysm.get("task_warnings") or []
    facts = _arch_facts(tp)
    sys_tst = _tst_ids(tp / "docs" / "TEST-STRATEGY.yaml")

    build_order = sysm.get("build_order") or []
    bo_nonempty_resolves = bool(build_order) and all(c in facts["container_ids"] for c in build_order)
    pos = {c: i for i, c in enumerate(build_order)}
    topo_ok = all(pos[to] < pos[frm] for (frm, to) in facts["cross_edges"] if frm in pos and to in pos)

    has_scaffold = any(t.get("kind") == "scaffold" for t in tasks)

    covered_tst: Set[str] = set()
    involves: Set[str] = set()
    test_without_tests = 0
    for t in tasks:
        for r in t.get("implements_tests") or []:
            covered_tst.add(str(r).upper())
        involves.update(t.get("involves_containers") or [])
        if t.get("kind") == "test" and not t.get("implements_tests"):
            test_without_tests += 1
    deferred = {x.upper() for x in _deferred_literals(warnings, sys_tst)}
    tst_covered = all((t in covered_tst or t in deferred) for t in sys_tst)
    involves_resolve = involves.issubset(facts["container_ids"]) if facts["container_ids"] else True

    deps_resolve, acyclic, dep_ev = _graph_acyclic_and_resolved(sysm, [])
    oa_ok, oa_ev = _outputs_acceptance_ok(tasks)
    tsk_ok, tsk_ev = _tsk_ids_ok(tasks)
    kinds_bad = sorted({t.get("kind") for t in tasks if t.get("kind") not in SYSTEM_KINDS})

    return [
        _assert("docs/TASKS.json exists and is valid JSON", True, str(tp / "docs" / "TASKS.json")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete", f"status={meta.get('status')!r}"),
        _assert("build_order is non-empty and every entry is an ARCH container_id", bo_nonempty_resolves,
                f"build_order={build_order}; container_ids={sorted(facts['container_ids'])}"),
        _assert("build_order is topological: each provider precedes its consumer (ARCH calls/depends_on)", topo_ok,
                f"build_order={build_order}; cross_edges={facts['cross_edges']}"),
        _assert("At least one kind:scaffold task exists (repo skeleton)", has_scaffold,
                f"kinds={[t.get('kind') for t in tasks]}"),
        _assert("Every system TST-NNN is realized by a task (implements_tests) or deferred (WRN-NNN)", tst_covered,
                f"sys_tst={sorted(sys_tst)}; covered={sorted(covered_tst)}; deferred={sorted(deferred)}"),
        _assert("Every kind:test task has a non-empty implements_tests", test_without_tests == 0,
                f"test_without_tests={test_without_tests}"),
        _assert("All involves_containers resolve to ARCH container_ids", involves_resolve,
                f"involves={sorted(involves)}; container_ids={sorted(facts['container_ids'])}"),
        _assert("depends_on resolve and the union task graph is acyclic", deps_resolve and acyclic, dep_ev),
        _assert("Every task has non-empty outputs and acceptance", oa_ok, oa_ev),
        _assert("Every tsk_id matches TSK-NNN and is unique", tsk_ok, tsk_ev),
        _assert("Every kind is in the system-kind vocabulary", not kinds_bad, f"off-vocab kinds={kinds_bad}"),
        _assert("Every task_warnings entry matches WRN-NNN", _all_match(warnings, WRN_RE), f"warnings={warnings[:3]}"),
        _assert("metadata.changelog has >= 1 well-formed entry", _changelog_ok(sysm),
                f"changelog={(meta.get('changelog') or [])[:2]}"),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """container-coverage-gate (backend-api)."""
    cid = "backend-api"
    container = _load_json(tp / "docs" / f"TASKS__{cid}.json")
    rc, vout = _validator_exit(tp)
    if not isinstance(container, dict) or "__parse_error__" in container:
        return [_assert(f"docs/TASKS__{cid}.json exists and is valid JSON", False,
                        str(container) if container else "missing")]
    meta = container.get("metadata") or {}
    out = [
        _assert(f"docs/TASKS__{cid}.json exists and is valid JSON", True, str(tp / "docs" / f"TASKS__{cid}.json")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert(f"container_id == '{cid}'", container.get("container_id") == cid, f"container_id={container.get('container_id')!r}"),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete", f"status={meta.get('status')!r}"),
        _assert("tasks[] is non-empty", len(_tasks(container)) >= 1, f"n_tasks={len(_tasks(container))}"),
    ]
    out.extend(_container_asserts(tp, cid, container))
    out.append(_assert("metadata.changelog has >= 1 well-formed entry", _changelog_ok(container),
                       f"changelog={(meta.get('changelog') or [])[:2]}"))
    return out


def grade_eval_3(tp: Path) -> List[dict]:
    """next-builds-container-before-system."""
    cid = "backend-api"
    container = _load_json(tp / "docs" / f"TASKS__{cid}.json")
    rc, vout = _validator_exit(tp)

    system_exists = (tp / "docs" / "TASKS.json").exists()
    produced = sorted(p.name for p in (tp / "docs").glob("TASKS__*.json"))
    only_backend = produced == [f"TASKS__{cid}.json"]

    if not isinstance(container, dict) or "__parse_error__" in container:
        return [
            _assert(f"--next produced docs/TASKS__{cid}.json", False, f"produced={produced}"),
            _assert("docs/TASKS.json was NOT produced (system stitch comes last)", not system_exists,
                    f"TASKS.json exists={system_exists}"),
            _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        ]
    meta = container.get("metadata") or {}
    out = [
        _assert(f"--next advanced to {cid} (produced its container file)", True, f"produced={produced}"),
        _assert("docs/TASKS.json was NOT produced (key distinction from sdlc:test --next: containers precede the system stitch)",
                not system_exists, f"TASKS.json exists={system_exists}"),
        _assert("No OTHER container file was produced (only backend-api)", only_backend, f"produced={produced}"),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert(f"container_id == '{cid}'", container.get("container_id") == cid, f"container_id={container.get('container_id')!r}"),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete", f"status={meta.get('status')!r}"),
    ]
    out.extend(_container_asserts(tp, cid, container))
    return out


def grade_eval_4(tp: Path) -> List[dict]:
    """cross-file-stitch-system-over-existing-container.

    The one eval where the SYSTEM file and a pre-built CONTAINER file coexist, so
    the union-graph cross-file resolution (`<cid>/TSK-NNN`) + acyclicity actually
    walk across files — and the mode-boundary rule (system mode must not edit a
    TASKS__*.json) is observable. Grades both files together."""
    cid = "backend-api"
    sysm = _load_json(tp / "docs" / "TASKS.json")
    container = _load_json(tp / "docs" / f"TASKS__{cid}.json")
    rc, vout = _validator_exit(tp)

    if not isinstance(sysm, dict) or "__parse_error__" in sysm:
        return [_assert("docs/TASKS.json exists and is valid JSON", False, str(sysm) if sysm else "missing")]
    if not isinstance(container, dict) or "__parse_error__" in container:
        return [
            _assert("docs/TASKS.json exists and is valid JSON", True, str(tp / "docs" / "TASKS.json")),
            _assert(f"docs/TASKS__{cid}.json (pre-built container) is present and valid JSON", False,
                    str(container) if container else "missing"),
        ]

    meta = sysm.get("metadata") or {}
    sys_tasks = _tasks(sysm)
    warnings = sysm.get("task_warnings") or []
    facts = _arch_facts(tp)
    sys_tst = _tst_ids(tp / "docs" / "TEST-STRATEGY.yaml")
    container_tsk_ids = {t.get("tsk_id") for t in _tasks(container) if t.get("tsk_id")}

    # A3 — container_task_graphs registers backend-api with an on-disk file_path.
    registry = sysm.get("container_task_graphs") or []
    reg_entry = next((r for r in registry if isinstance(r, dict) and r.get("container_id") == cid), None)
    reg_fp = (reg_entry or {}).get("file_path")
    reg_on_disk = bool(reg_fp) and (tp / "docs" / Path(reg_fp).name).exists()
    a3 = reg_entry is not None and reg_on_disk

    # A4 — at least one system task carries a cross-file dep backend-api/TSK-NNN
    #      that names a real task in the container file. This is THE stitch edge;
    #      it can only exist if system mode authored it (the container has only
    #      same-file deps).
    xfile_edges: List[str] = []
    for t in sys_tasks:
        for ref in t.get("depends_on") or []:
            m = XREF_RE.match(str(ref).strip())
            if m and m.group("scope") == cid and m.group("tsk") in container_tsk_ids:
                xfile_edges.append(f"{t.get('tsk_id')} -> {ref}")
    a4 = len(xfile_edges) >= 1

    # A5 — union resolve + acyclicity across BOTH files.
    deps_resolve, acyclic, dep_ev = _graph_acyclic_and_resolved(sysm, [(cid, container)])

    # A6 — container file unchanged vs the staged fixture (mode-boundary rule).
    fixture = SKILL_ROOT / "evals" / "fixtures" / "web-app-stitch" / "docs" / f"TASKS__{cid}.json"
    fixture_doc = _load_json(fixture)
    a6 = isinstance(fixture_doc, dict) and fixture_doc == container
    a6_ev = ("container matches the staged fixture (untouched)" if a6
             else f"container differs from {fixture.name} fixture (system mode edited it?)")

    # A7 — build_order topological (provider before consumer).
    build_order = sysm.get("build_order") or []
    bo_nonempty_resolves = bool(build_order) and all(c in facts["container_ids"] for c in build_order)
    pos = {c: i for i, c in enumerate(build_order)}
    topo_ok = all(pos[to] < pos[frm] for (frm, to) in facts["cross_edges"] if frm in pos and to in pos)
    a7 = bo_nonempty_resolves and topo_ok

    # A8 — system test coverage (trace-or-defer).
    covered_tst: Set[str] = set()
    for t in sys_tasks:
        for r in t.get("implements_tests") or []:
            covered_tst.add(str(r).upper())
    deferred = {x.upper() for x in _deferred_literals(warnings, sys_tst)}
    tst_covered = all((t in covered_tst or t in deferred) for t in sys_tst)

    # A9 — validator clean: exit 0, no file_path-not-found warning, no unresolved/cycle error.
    vlow = vout.lower()
    no_fp_warn = "not found on disk" not in vlow
    no_unresolved = ("does not resolve to an existing task" not in vlow
                     and "is not a valid tsk ref" not in vlow
                     and "dependency cycle" not in vlow)
    a9 = rc == 0 and no_fp_warn and no_unresolved

    # A10 — id + kind hygiene; A11 — outputs/acceptance.
    tsk_ok, tsk_ev = _tsk_ids_ok(sys_tasks)
    kinds_bad = sorted({t.get("kind") for t in sys_tasks if t.get("kind") not in SYSTEM_KINDS})
    a10 = tsk_ok and not kinds_bad
    oa_ok, oa_ev = _outputs_acceptance_ok(sys_tasks)

    return [
        _assert("docs/TASKS.json exists and is valid JSON", True, str(tp / "docs" / "TASKS.json")),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete", f"status={meta.get('status')!r}"),
        _assert("container_task_graphs registers backend-api with an on-disk file_path", a3,
                f"entry={reg_entry}; on_disk={reg_on_disk}"),
        _assert("At least one system task has a cross-file depends_on 'backend-api/TSK-NNN' resolving to a real container task (the stitch edge)",
                a4, f"cross_file_edges={xfile_edges}; container_tsk_ids={sorted(container_tsk_ids)}"),
        _assert("Every depends_on across the union of both files resolves and the union graph is acyclic",
                deps_resolve and acyclic, dep_ev),
        _assert("docs/TASKS__backend-api.json is unchanged by the run (system mode must not edit container files)",
                a6, a6_ev),
        _assert("build_order is non-empty, resolves, and is topological (backend-api before web-frontend)", a7,
                f"build_order={build_order}; cross_edges={facts['cross_edges']}"),
        _assert("Every system TST-NNN is realized (implements_tests) or deferred (WRN-NNN)", tst_covered,
                f"sys_tst={sorted(sys_tst)}; covered={sorted(covered_tst)}; deferred={sorted(deferred)}"),
        _assert("Validator exits 0 with no file_path-not-found warning and no unresolved/cycle dependency error",
                a9, f"exit={rc}; {vout[:240]}"),
        _assert("Every tsk_id matches TSK-NNN, is unique, and every kind is in the system-kind vocabulary", a10,
                f"{tsk_ev}; off-vocab kinds={kinds_bad}"),
        _assert("Every task has non-empty outputs and acceptance", oa_ok, oa_ev),
        _assert("metadata.changelog has >= 1 well-formed entry", _changelog_ok(sysm),
                f"changelog={(meta.get('changelog') or [])[:2]}"),
    ]


GRADERS: Dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1, 2: grade_eval_2, 3: grade_eval_3, 4: grade_eval_4,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    if not iteration_dir.exists():
        print(f"ERROR: {iteration_dir} does not exist - run stage_iteration.py first.")
        return 2

    rows: List[dict] = []
    for eval_dir in sorted(iteration_dir.iterdir()):
        if not eval_dir.is_dir() or not eval_dir.name.startswith("eval-"):
            continue
        meta = json.loads((eval_dir / "eval_metadata.json").read_text(encoding="utf-8"))
        eid = meta["eval_id"]
        grader = GRADERS.get(eid)
        if grader is None:
            print(f"WARN: no grader for eval {eid}, skipping")
            continue
        results = grader(eval_dir / "test-project")
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        grading = {
            "eval_id": eid,
            "eval_name": meta["eval_name"],
            "passed": passed,
            "total": total,
            "pass_rate": passed / total if total else 0.0,
            "expectations": results,
        }
        (eval_dir / "grading.json").write_text(json.dumps(grading, indent=2), encoding="utf-8")
        rows.append(grading)
        bar = "#" * passed + "-" * (total - passed)
        print(f"  eval {eid:>2}: {meta['eval_name']:<38} [{bar}] {passed}/{total}")

    lines = [f"# sdlc-task eval results - iteration {args.iteration}", ""]
    total_p = sum(r["passed"] for r in rows)
    total_t = sum(r["total"] for r in rows)
    lines.append(f"**Overall pass rate:** {total_p}/{total_t} ({(total_p/total_t*100 if total_t else 0):.0f}%)")
    lines += ["", "| Eval | Name | Passed | Total |", "|---:|---|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['eval_id']} | {r['eval_name']} | {r['passed']} | {r['total']} |")
    lines.append("\n## Per-eval detail")
    for r in rows:
        lines.append(f"\n### Eval {r['eval_id']} - {r['eval_name']}  ({r['passed']}/{r['total']})\n")
        for exp in r["expectations"]:
            mark = "[OK]  " if exp["passed"] else "[FAIL]"
            lines.append(f"- {mark} {exp['text']}  \n  *evidence:* `{exp['evidence']}`")
    out = iteration_dir / "benchmark.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
