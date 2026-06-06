"""Validate docs/TASKS.json + every docs/TASKS__*.json against the sdlc-task
schemas, and run the cross-check suite — including the union-graph acyclicity
check that validates FR-013's "deterministic stitch into one global
dependency-ordered TaskGraph" (the trace-or-defer contract from CLAUDE.md §6).

The task graph is the one sdlc artifact written as JSON, not YAML (it is
machine-generated and machine-consumed by the codegen stage, a large regular
graph that gets programmatically stitched and topologically sorted — see
references/merge-validate.md). The upstream artifacts it reads (PRD, ARCH,
ARCH__*, TEST-STRATEGY, TEST-STRATEGY__*, DATA-MODEL, API__*) are still YAML.

Run from the project root:

    python sdlc/skills/task/validate_schema.py
    python sdlc/skills/task/validate_schema.py --path docs/TASKS.json

The --path argument only locates the docs directory: the system file
(TASKS.json) and every sibling TASKS__*.json in the same directory are
validated together, with their upstream docs read for the cross-checks.

Validates:
    1. docs/TASKS.json — the system task graph (repo scaffold + cross-container
       integration + system e2e/contract test tasks + build_order + the
       per-container subgraph registry).
    2. Every docs/TASKS__*.json sibling — one per container.
    3. Required-field checks (status: complete gate).
    4. ID-prefix formats: TSK-NNN (unique per file) on every tsk_id; WRN-NNN on
       every task_warnings entry.
    5. Reference integrity (block status: complete):
       - component_ref resolves to the matching ARCH__<container>.yaml; an
         implementation task is scoped to a component (component_ref) or a
         contract (touches_operations).
       - implements entries are FR/NFR and resolve to PRD ids (⊆ the
         container's + targeted component's implements_requirements).
       - implements_tests entries are TST-NNN and resolve to the matching
         TEST-STRATEGY(.__container).yaml; kind:test must set one.
       - involves_containers / build_order / container_task_graphs resolve to
         ARCH.yaml.
       - depends_on entries resolve across the union of all task files, and the
         union graph is acyclic.
    6. Coverage cross-checks (trace-or-defer; block status: complete):
       - Container: every component_id and every container TST-NNN is realized
         by some task OR deferred via a WRN-NNN.
       - System: every system TST-NNN is realized by some task OR deferred.

Exit codes:
    0 — schema valid; status='complete' (all checks passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but a cross-check failed.
    2 — could not read or parse any task file (none present, bad JSON).
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required.\nInstall with:  pip install pyyaml", file=sys.stderr)
    sys.exit(3)

try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    print(
        "ERROR: pydantic v2 is required.\nInstall with:  pip install 'pydantic>=2'",
        file=sys.stderr,
    )
    sys.exit(3)


# =============================================================================
# Enums — kept in lockstep with the two .schema.yaml files.
# =============================================================================


class Status(str, Enum):
    draft = "draft"
    complete = "complete"


class Priority(str, Enum):
    must = "must"
    should = "should"
    could = "could"


class TaskStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"


class Granularity(str, Enum):
    coarse = "coarse"
    fine = "fine"


# `kind` is validated as a plain string against these sets in the checks (not a
# strict pydantic enum) so a draft with an off-vocabulary kind stays loadable
# and reports a fixable error instead of crashing the parse.
CONTAINER_KINDS = {
    "scaffold", "implementation", "test", "integration", "migration", "config", "chore",
}
SYSTEM_KINDS = {
    "scaffold", "integration", "test", "config", "migration", "deploy-prep", "docs", "chore",
}


# =============================================================================
# Pydantic models. Almost every field is Optional: the schema's "REQUIRED"
# fields are enforced by check_required() only when status == complete, so a
# status: draft artifact validates even with holes (the documented contract).
# =============================================================================


class SystemMetadata(BaseModel):
    tasks_version: Optional[str] = None
    last_updated: Optional[str] = None
    generated_by: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[Status] = None
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class ContainerMetadata(BaseModel):
    tasks_container_version: Optional[str] = None
    last_updated: Optional[str] = None
    generated_by: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[Status] = None
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class ContainerTask(BaseModel):
    tsk_id: Optional[str] = None
    title: Optional[str] = None
    kind: Optional[str] = None
    description: Optional[str] = None
    component_ref: Optional[str] = None
    implements: Optional[List[str]] = None
    implements_tests: Optional[List[str]] = None
    touches_entities: Optional[List[str]] = None
    touches_operations: Optional[List[str]] = None
    depends_on: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    acceptance: Optional[List[str]] = None
    priority: Optional[Priority] = None
    estimate: Optional[str] = None
    status: Optional[TaskStatus] = None


class SystemTask(BaseModel):
    tsk_id: Optional[str] = None
    title: Optional[str] = None
    kind: Optional[str] = None
    description: Optional[str] = None
    involves_containers: Optional[List[str]] = None
    implements: Optional[List[str]] = None
    implements_tests: Optional[List[str]] = None
    depends_on: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    acceptance: Optional[List[str]] = None
    priority: Optional[Priority] = None
    estimate: Optional[str] = None
    status: Optional[TaskStatus] = None


class ContainerTaskGraphRef(BaseModel):
    container_id: Optional[str] = None
    file_path: Optional[str] = None


class TasksSystem(BaseModel):
    metadata: SystemMetadata
    overview: Optional[str] = None
    granularity: Optional[Granularity] = None
    build_order: Optional[List[str]] = None
    tasks: Optional[List[SystemTask]] = None
    container_task_graphs: Optional[List[ContainerTaskGraphRef]] = None
    task_warnings: Optional[List[str]] = None


class TasksContainer(BaseModel):
    metadata: ContainerMetadata
    container_id: Optional[str] = None
    overview: Optional[str] = None
    inherits_from: Optional[str] = None
    granularity: Optional[Granularity] = None
    tasks: Optional[List[ContainerTask]] = None
    task_warnings: Optional[List[str]] = None


# =============================================================================
# Regexes + small helpers
# =============================================================================

_TSK_RE = re.compile(r"^TSK-\d{3,}$")
_WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
_TST_RE = re.compile(r"^TST-\d{3,}$", re.IGNORECASE)
_FR_RE = re.compile(r"^FR-\d+$", re.IGNORECASE)
_NFR_RE = re.compile(r"^NFR-\d+$", re.IGNORECASE)
# A cross-file dep ref: "<container-or-TASKS>/TSK-NNN".
_XREF_RE = re.compile(r"^(?P<scope>[A-Za-z0-9_-]+)/(?P<tsk>TSK-\d{3,})$")

_REQ_TOKEN_RE = re.compile(r"\b(?:FR|NFR)-\d+\b", re.IGNORECASE)

INFRA_ARCHETYPES = {
    "primary-database",
    "secondary-database",
    "cache",
    "blob-store",
    "search-index",
    "message-bus",
}


def _safe_yaml(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def _safe_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _req_tokens_in(strings: List[str]) -> Set[str]:
    """Every FR/NFR token appearing anywhere in a list of strings."""
    out: Set[str] = set()
    for s in strings or []:
        if isinstance(s, str):
            for m in _REQ_TOKEN_RE.findall(s):
                out.add(m.upper())
    return out


def _deferred_literals(warnings: List[str], ids: Set[str]) -> Set[str]:
    """Subset of `ids` named as whole words in any warning (the defer half)."""
    deferred: Set[str] = set()
    for i in ids:
        pat = re.compile(r"\b" + re.escape(i) + r"\b")
        if any(isinstance(w, str) and pat.search(w) for w in (warnings or [])):
            deferred.add(i)
    return deferred


# =============================================================================
# Upstream loaders (PRD / ARCH / ARCH__<cid> / TEST-STRATEGY(.__cid))
# =============================================================================


def load_prd_id_families(prd_path: Path) -> Dict[str, Set[str]]:
    """Return {'FR','NFR'} id sets declared in PRD.yaml (monorepo-aware)."""
    fams: Dict[str, Set[str]] = {"FR": set(), "NFR": set()}
    raw = _safe_yaml(prd_path)
    if raw is None:
        return fams
    monorepo = bool((raw.get("metadata") or {}).get("monorepo"))

    def _pull(node: dict) -> None:
        freqs = node.get("functional_requirements") or {}
        if isinstance(freqs, dict):
            for key in ("must_have_features", "nice_to_have_features"):
                for item in freqs.get(key) or []:
                    mm = re.match(r"^FR-\d+", str(item).strip(), re.IGNORECASE)
                    if mm:
                        fams["FR"].add(mm.group(0).upper())
        nfreqs = node.get("non_functional_requirements") or {}
        if isinstance(nfreqs, dict):
            for key in ("performance_targets", "other"):
                for item in nfreqs.get(key) or []:
                    mm = re.match(r"^NFR-\d+", str(item).strip(), re.IGNORECASE)
                    if mm:
                        fams["NFR"].add(mm.group(0).upper())

    if monorepo:
        for prod in (raw.get("products") or {}).values():
            if isinstance(prod, dict):
                _pull(prod)
    else:
        _pull(raw)
    return fams


class ArchInfo:
    """Parsed view of ARCH.yaml needed for the cross-checks."""

    def __init__(self) -> None:
        self.container_ids: Set[str] = set()
        self.testable: Set[str] = set()
        self.implements: Dict[str, Set[str]] = {}       # cid -> {FR/NFR}
        # cross-container calls/depends_on edges as (from_cid, to_cid) pairs:
        self.cross_edges: List[Tuple[str, str]] = []
        self.present: bool = False


def load_arch(arch_path: Path) -> ArchInfo:
    info = ArchInfo()
    raw = _safe_yaml(arch_path)
    if raw is None:
        return info
    info.present = True
    for c in raw.get("containers") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("container_id")
        if not cid:
            continue
        info.container_ids.add(cid)
        archetype = (c.get("archetype") or "").strip()
        external = bool(c.get("external"))
        if (not external) and archetype not in INFRA_ARCHETYPES and archetype != "external-service":
            info.testable.add(cid)
        info.implements[cid] = _req_tokens_in(c.get("implements_requirements") or [])
    for e in raw.get("edges") or []:
        if not isinstance(e, dict):
            continue
        if (e.get("type") or "") in ("calls", "depends_on"):
            frm, to = e.get("from"), e.get("to")
            if frm and to and frm != to:
                info.cross_edges.append((frm, to))
    return info


class ArchContainerInfo:
    def __init__(self) -> None:
        self.present: bool = False
        self.component_ids: Set[str] = set()
        self.implements: Set[str] = set()    # union of all implements_requirements


def load_arch_container(docs_dir: Path, cid: str) -> ArchContainerInfo:
    info = ArchContainerInfo()
    raw = _safe_yaml(docs_dir / f"ARCH__{cid}.yaml")
    if raw is None:
        return info
    info.present = True
    info.implements |= _req_tokens_in(raw.get("implements_requirements") or [])
    for comp in raw.get("components") or []:
        if not isinstance(comp, dict):
            continue
        coid = comp.get("component_id")
        if coid:
            info.component_ids.add(coid)
        info.implements |= _req_tokens_in(comp.get("implements_requirements") or [])
    return info


def load_test_tst_ids(path: Path) -> Set[str]:
    """tst_ids declared in a TEST-STRATEGY(.__container).yaml."""
    out: Set[str] = set()
    raw = _safe_yaml(path)
    if raw is None:
        return out
    for t in raw.get("tests") or []:
        if isinstance(t, dict) and t.get("tst_id"):
            out.add(str(t["tst_id"]).upper())
    return out


# =============================================================================
# Field-level format / required checks
# =============================================================================


def check_warning_ids(warnings: Optional[List[str]], label: str) -> List[str]:
    errs: List[str] = []
    for i, w in enumerate(warnings or []):
        if not isinstance(w, str) or not _WRN_RE.match(w.strip()):
            errs.append(f"{label}.task_warnings[{i}]: '{w}' must match 'WRN-NNN: <message>'")
    return errs


def check_tsk_ids(tasks: List[Any], label: str) -> List[str]:
    errs: List[str] = []
    seen: Set[str] = set()
    for i, t in enumerate(tasks or []):
        tid = getattr(t, "tsk_id", None)
        if not tid:
            continue  # required-ness handled by check_required
        if not _TSK_RE.match(str(tid)):
            errs.append(f"{label}.tasks[{i}].tsk_id '{tid}' must match 'TSK-NNN'")
        elif tid in seen:
            errs.append(f"{label}.tasks[{i}].tsk_id '{tid}' is duplicated")
        else:
            seen.add(tid)
    return errs


def check_kinds(tasks: List[Any], allowed: Set[str], label: str) -> List[str]:
    errs: List[str] = []
    for i, t in enumerate(tasks or []):
        k = getattr(t, "kind", None)
        if k is not None and k not in allowed:
            errs.append(f"{label}.tasks[{i}].kind '{k}' is not one of {sorted(allowed)}")
    return errs


def check_required_system(m: TasksSystem) -> List[str]:
    missing: List[str] = []
    if m.overview in (None, ""):
        missing.append("overview")
    if m.granularity is None:
        missing.append("granularity")
    if not m.build_order:
        missing.append("build_order (non-empty)")
    if not m.tasks:
        missing.append("tasks (non-empty)")
    for i, t in enumerate(m.tasks or []):
        for fld in ("tsk_id", "title", "kind", "description", "priority", "status"):
            if getattr(t, fld) in (None, ""):
                missing.append(f"tasks[{i}].{fld}")
        if not t.outputs:
            missing.append(f"tasks[{i}].outputs")
        if not t.acceptance:
            missing.append(f"tasks[{i}].acceptance")
    return missing


def check_required_container(m: TasksContainer) -> List[str]:
    missing: List[str] = []
    for fld in ("container_id", "overview"):
        if getattr(m, fld) in (None, ""):
            missing.append(fld)
    if m.granularity is None:
        missing.append("granularity")
    if not m.tasks:
        missing.append("tasks (non-empty)")
    for i, t in enumerate(m.tasks or []):
        for fld in ("tsk_id", "title", "kind", "description", "priority", "status"):
            if getattr(t, fld) in (None, ""):
                missing.append(f"tasks[{i}].{fld}")
        if not t.outputs:
            missing.append(f"tasks[{i}].outputs")
        if not t.acceptance:
            missing.append(f"tasks[{i}].acceptance")
    return missing


# =============================================================================
# Union dependency-graph helpers (the "stitch")
# =============================================================================


def _node(scope: str, tsk: str) -> str:
    return f"{scope}/{tsk}"


def collect_graph_nodes(
    sysm: Optional[TasksSystem],
    containers: List[Tuple[str, TasksContainer]],
) -> Set[str]:
    """Global node ids across every task file. System scope is 'TASKS'."""
    nodes: Set[str] = set()
    if sysm is not None:
        for t in sysm.tasks or []:
            if t.tsk_id:
                nodes.add(_node("TASKS", t.tsk_id))
    for cid, cm in containers:
        for t in cm.tasks or []:
            if t.tsk_id:
                nodes.add(_node(cid, t.tsk_id))
    return nodes


def resolve_dep(scope: str, ref: str) -> Optional[str]:
    """Map a depends_on entry to a global node id, or None if malformed."""
    ref = str(ref).strip()
    if _TSK_RE.match(ref):                 # same-file bare "TSK-NNN"
        return _node(scope, ref)
    m = _XREF_RE.match(ref)                # "<scope>/TSK-NNN"
    if m:
        return _node(m.group("scope"), m.group("tsk"))
    return None


def check_dependencies_and_cycles(
    sysm: Optional[TasksSystem],
    containers: List[Tuple[str, TasksContainer]],
) -> List[str]:
    """Resolve every depends_on against the union node set and check acyclicity.
    Returns a list of blocking errors (unresolved refs + any cycle)."""
    errs: List[str] = []
    nodes = collect_graph_nodes(sysm, containers)
    adj: Dict[str, Set[str]] = {n: set() for n in nodes}

    def _wire(scope: str, label: str, tasks: List[Any]) -> None:
        for t in tasks or []:
            if not t.tsk_id:
                continue
            src = _node(scope, t.tsk_id)
            for ref in t.depends_on or []:
                target = resolve_dep(scope, ref)
                if target is None:
                    errs.append(f"{label} {t.tsk_id}.depends_on '{ref}' is not a valid TSK ref")
                elif target not in nodes:
                    errs.append(f"{label} {t.tsk_id}.depends_on '{ref}' does not resolve to an existing task")
                elif target == src:
                    errs.append(f"{label} {t.tsk_id}.depends_on '{ref}' is a self-dependency")
                else:
                    # edge: dependency -> dependent (target must precede src)
                    adj.setdefault(target, set()).add(src)

    if sysm is not None:
        _wire("TASKS", "[TASKS]", sysm.tasks or [])
    for cid, cm in containers:
        _wire(cid, f"[{cid}]", cm.tasks or [])

    # Cycle detection (DFS three-color).
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in adj}
    cycle: List[str] = []

    def _dfs(u: str, stack: List[str]) -> bool:
        color[u] = GRAY
        stack.append(u)
        for v in sorted(adj.get(u, ())):
            if color.get(v, WHITE) == GRAY:
                i = stack.index(v)
                cycle.extend(stack[i:] + [v])
                return True
            if color.get(v, WHITE) == WHITE and _dfs(v, stack):
                return True
        color[u] = BLACK
        stack.pop()
        return False

    for n in sorted(adj):
        if color[n] == WHITE:
            if _dfs(n, []):
                errs.append(
                    "dependency cycle in the union task graph: " + " -> ".join(cycle)
                )
                break
    return errs


# =============================================================================
# Reference + coverage cross-checks
# =============================================================================


def check_system(
    m: TasksSystem,
    fams: Dict[str, Set[str]],
    arch: ArchInfo,
    docs_dir: Path,
) -> Tuple[List[str], List[str]]:
    errs: List[str] = []
    warns: List[str] = []
    all_reqs = fams["FR"] | fams["NFR"]
    sys_tst = load_test_tst_ids(docs_dir / "TEST-STRATEGY.yaml")

    # build_order integrity.
    for cid in m.build_order or []:
        if arch.present and cid not in arch.container_ids:
            errs.append(f"build_order '{cid}' is not an ARCH container_id")
    if arch.present and m.build_order is not None:
        bo = set(m.build_order)
        for cid in sorted(arch.testable - bo):
            warns.append(f"build_order omits buildable container '{cid}'")
        pos = {c: i for i, c in enumerate(m.build_order)}
        for frm, to in arch.cross_edges:          # to=provider should precede from=consumer
            if frm in pos and to in pos and pos[to] > pos[frm]:
                warns.append(f"build_order: provider '{to}' should precede consumer '{frm}' (ARCH edge {frm}->{to})")

    covered_tst: Set[str] = set()
    for i, t in enumerate(m.tasks or []):
        for cid in t.involves_containers or []:
            if arch.present and cid not in arch.container_ids:
                errs.append(f"tasks[{i}].involves_containers '{cid}' is not an ARCH container_id")
        for ref in t.implements or []:
            up = str(ref).upper()
            if not (_FR_RE.match(up) or _NFR_RE.match(up)):
                errs.append(f"tasks[{i}].implements '{ref}' is not an FR/NFR id")
            elif up not in all_reqs and all_reqs:
                errs.append(f"tasks[{i}].implements '{ref}' does not resolve to a PRD id")
        for ref in t.implements_tests or []:
            up = str(ref).upper()
            if not _TST_RE.match(up):
                errs.append(f"tasks[{i}].implements_tests '{ref}' is not a TST-NNN id")
            else:
                covered_tst.add(up)
                if sys_tst and up not in sys_tst:
                    errs.append(f"tasks[{i}].implements_tests '{ref}' is not a test in the system TEST-STRATEGY.yaml")
        if t.kind == "test" and not t.implements_tests:
            errs.append(f"tasks[{i}] is kind:test but has no implements_tests")

    # System test coverage (trace-or-defer).
    deferred = {x.upper() for x in _deferred_literals(m.task_warnings or [], sys_tst)}
    for tid in sorted(sys_tst):
        if tid not in covered_tst and tid not in deferred:
            errs.append(f"system test coverage: {tid} (system TEST-STRATEGY) is realized by no task and no WRN-NNN defers it")

    # Cross-container edge coverage (advisory).
    integ_pairs: Set[frozenset] = set()
    for t in m.tasks or []:
        ic = set(t.involves_containers or [])
        for a in ic:
            for b in ic:
                if a != b:
                    integ_pairs.add(frozenset((a, b)))
    edge_defer = m.task_warnings or []
    for frm, to in arch.cross_edges:
        if frozenset((frm, to)) not in integ_pairs:
            if not any(frm in w and to in w for w in edge_defer):
                warns.append(f"cross-container edge {frm}->{to} has no integration task and no deferral")

    # container_task_graphs integrity (advisory).
    for ref in m.container_task_graphs or []:
        if ref.container_id and arch.present and ref.container_id not in arch.container_ids:
            warns.append(f"container_task_graphs: '{ref.container_id}' is not an ARCH container_id")
        if ref.file_path and not (docs_dir / Path(ref.file_path).name).exists():
            warns.append(f"container_task_graphs: file_path '{ref.file_path}' not found on disk")
    return errs, warns


def check_container(
    m: TasksContainer,
    fams: Dict[str, Set[str]],
    arch: ArchInfo,
    docs_dir: Path,
) -> Tuple[List[str], List[str]]:
    errs: List[str] = []
    warns: List[str] = []
    cid = m.container_id
    label = f"[{cid or '?'}]"
    all_reqs = fams["FR"] | fams["NFR"]

    # Identity.
    if cid and arch.present:
        if cid not in arch.container_ids:
            errs.append(f"{label} container_id is not in ARCH.yaml")
        elif cid not in arch.testable:
            errs.append(f"{label} container_id is not a buildable container (external or storage/infra)")
    ac = load_arch_container(docs_dir, cid) if cid else ArchContainerInfo()
    if cid and not ac.present:
        errs.append(f"{label} no docs/ARCH__{cid}.yaml found — run /sdlc:arch {cid} first")
    cont_tst = load_test_tst_ids(docs_dir / f"TEST-STRATEGY__{cid}.yaml") if cid else set()
    if cid and not cont_tst and not (docs_dir / f"TEST-STRATEGY__{cid}.yaml").exists():
        errs.append(f"{label} no docs/TEST-STRATEGY__{cid}.yaml found — run /sdlc:test {cid} first")

    allowed_reqs = (arch.implements.get(cid, set()) if cid else set()) | ac.implements

    covered_components: Set[str] = set()
    covered_tst: Set[str] = set()
    named_reqs: Set[str] = set()

    for i, t in enumerate(m.tasks or []):
        if t.component_ref:
            covered_components.add(t.component_ref)
            if ac.present and t.component_ref not in ac.component_ids:
                errs.append(f"{label} tasks[{i}].component_ref '{t.component_ref}' is not a component in ARCH__{cid}.yaml")
        # Scope integrity: an implementation task targets a component or a contract.
        if t.kind == "implementation" and not t.component_ref and not t.touches_operations:
            errs.append(f"{label} tasks[{i}] is kind:implementation but is scoped to neither a component (component_ref) nor a contract (touches_operations)")
        for ref in t.implements or []:
            up = str(ref).upper()
            if not (_FR_RE.match(up) or _NFR_RE.match(up)):
                errs.append(f"{label} tasks[{i}].implements '{ref}' is not an FR/NFR id")
                continue
            named_reqs.add(up)
            if up not in all_reqs and all_reqs:
                errs.append(f"{label} tasks[{i}].implements '{ref}' does not resolve to a PRD id")
            elif ac.present and allowed_reqs and up not in allowed_reqs:
                errs.append(f"{label} tasks[{i}].implements '{ref}' is not in the container's or targeted component's implements_requirements")
        for ref in t.implements_tests or []:
            up = str(ref).upper()
            if not _TST_RE.match(up):
                errs.append(f"{label} tasks[{i}].implements_tests '{ref}' is not a TST-NNN id")
            else:
                covered_tst.add(up)
                if cont_tst and up not in cont_tst:
                    errs.append(f"{label} tasks[{i}].implements_tests '{ref}' is not a test in TEST-STRATEGY__{cid}.yaml")
        if t.kind == "test" and not t.implements_tests:
            errs.append(f"{label} tasks[{i}] is kind:test but has no implements_tests")

    warnings = m.task_warnings or []
    deferred_components = _deferred_literals(warnings, ac.component_ids)
    deferred_tst = {x.upper() for x in _deferred_literals(warnings, cont_tst)}

    # Component coverage (trace-or-defer).
    for comp in sorted(ac.component_ids):
        if comp not in covered_components and comp not in deferred_components:
            errs.append(f"{label} component coverage: component '{comp}' is realized by no task and no WRN-NNN defers it")
    # Test coverage (trace-or-defer).
    for tid in sorted(cont_tst):
        if tid not in covered_tst and tid not in deferred_tst:
            errs.append(f"{label} test coverage: {tid} (TEST-STRATEGY__{cid}) is realized by no task and no WRN-NNN defers it")
    # Requirement coverage (advisory).
    for r in sorted(allowed_reqs):
        if r not in named_reqs:
            warns.append(f"{label} requirement coverage: {r} is implemented by this container but named by no task's `implements` (transitively covered if its component is realized)")
    return errs, warns


# =============================================================================
# Orchestration
# =============================================================================


def _format_errors(exc: ValidationError) -> List[str]:
    out = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"])
        out.append(f"{loc}: {e['msg']}")
    return out


def _cid_from_container_path(p: Path) -> str:
    # TASKS__<cid>.json  ->  <cid>
    return p.stem[len("TASKS__"):]


def validate_all(path: Path) -> int:
    docs_dir = path.parent
    if path.name.startswith("TASKS__"):
        system_path = docs_dir / "TASKS.json"
    else:
        system_path = path
    container_paths = sorted(
        p for p in docs_dir.glob("TASKS__*.json") if p.is_file()
    )

    if not system_path.exists() and not container_paths:
        print(f"ERROR: no TASKS.json or TASKS__*.json found in {docs_dir}", file=sys.stderr)
        return 2

    fams = load_prd_id_families(docs_dir / "PRD.yaml")
    arch = load_arch(docs_dir / "ARCH.yaml")

    parse_failed = False
    blocking: List[str] = []
    warnings: List[str] = []
    statuses: List[Tuple[str, Optional[Status]]] = []

    sysm: Optional[TasksSystem] = None
    containers: List[Tuple[str, TasksContainer]] = []

    # ---- system file ----
    if system_path.exists():
        raw = _safe_json(system_path)
        if raw is None:
            print(f"ERROR: cannot read/parse {system_path}", file=sys.stderr)
            return 2
        try:
            sysm = TasksSystem(**raw)
        except ValidationError as exc:
            print(f"[FAIL] {system_path.name} FAILED schema validation\n")
            for line in _format_errors(exc):
                print(f"  - {line}")
            parse_failed = True
            sysm = None
        if sysm is not None:
            statuses.append((system_path.name, sysm.metadata.status))
            blocking += [f"{system_path.name}: {e}" for e in check_required_system(sysm)]
            blocking += [f"{system_path.name}: {e}" for e in check_tsk_ids(sysm.tasks or [], system_path.stem)]
            blocking += [f"{system_path.name}: {e}" for e in check_kinds(sysm.tasks or [], SYSTEM_KINDS, system_path.stem)]
            blocking += [f"{system_path.name}: {e}" for e in check_warning_ids(sysm.task_warnings, system_path.stem)]
            s_errs, s_warns = check_system(sysm, fams, arch, docs_dir)
            blocking += [f"{system_path.name}: {e}" for e in s_errs]
            warnings += [f"{system_path.name}: {w}" for w in s_warns]

    # ---- container files ----
    for cp in container_paths:
        raw = _safe_json(cp)
        if raw is None:
            print(f"ERROR: cannot read/parse {cp}", file=sys.stderr)
            return 2
        try:
            cm = TasksContainer(**raw)
        except ValidationError as exc:
            print(f"[FAIL] {cp.name} FAILED schema validation\n")
            for line in _format_errors(exc):
                print(f"  - {line}")
            parse_failed = True
            continue
        cid = cm.container_id or _cid_from_container_path(cp)
        containers.append((cid, cm))
        statuses.append((cp.name, cm.metadata.status))
        blocking += [f"{cp.name}: {e}" for e in check_required_container(cm)]
        blocking += [f"{cp.name}: {e}" for e in check_tsk_ids(cm.tasks or [], cp.stem)]
        blocking += [f"{cp.name}: {e}" for e in check_kinds(cm.tasks or [], CONTAINER_KINDS, cp.stem)]
        blocking += [f"{cp.name}: {e}" for e in check_warning_ids(cm.task_warnings, cp.stem)]
        c_errs, c_warns = check_container(cm, fams, arch, docs_dir)
        blocking += [f"{cp.name}: {e}" for e in c_errs]
        warnings += [f"{cp.name}: {w}" for w in c_warns]

    if parse_failed:
        return 1

    # Union-graph dependency resolution + acyclicity (the stitch).
    blocking += [f"graph: {e}" for e in check_dependencies_and_cycles(sysm, containers)]

    # Upstream-status awareness (non-blocking).
    for up in ("PRD.yaml", "DATA-MODEL.yaml", "ARCH.yaml", "TEST-STRATEGY.yaml"):
        raw = _safe_yaml(docs_dir / up)
        if raw is not None:
            st = (raw.get("metadata") or {}).get("status")
            if st and st != "complete":
                warnings.append(f"upstream {up} has metadata.status='{st}' (expected 'complete')")

    any_complete = any(st == Status.complete for _, st in statuses)

    if any_complete and blocking:
        print("[FAIL] a task file claims status 'complete' but has errors:\n")
        for b in blocking:
            print(f"  - {b}")
        if warnings:
            print(f"\nWARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"  - {w}")
        return 1

    files = ", ".join(name for name, _ in statuses) or "(none)"
    if any_complete:
        print(f"[OK] task graph is valid and complete ({files}).")
    else:
        if blocking:
            print(f"[OK] task graph is a valid DRAFT ({files}); {len(blocking)} item(s) to resolve before 'complete':\n")
            for b in blocking:
                print(f"  - {b}")
        else:
            print(f"[OK] task graph is a valid DRAFT ({files}).")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate TASKS.json + every TASKS__*.json against the sdlc-task schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "TASKS.json"),
        help="Path that locates the docs dir (default: ./docs/TASKS.json). "
        "The system file + all sibling TASKS__*.json are validated together.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
