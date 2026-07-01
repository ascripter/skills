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
         contract (touches_operations), sets a target_symbol that resolves to one
         work_units[].name on its component_ref, and carries exactly one
         target_files entry (the atomic-codegen pin).
       - implements entries are FR/NFR and resolve to PRD ids (⊆ the
         container's + targeted component's implements_requirements).
       - implements_tests entries are TST-NNN and resolve to the matching
         TEST-STRATEGY(.__container).yaml; kind:test must set one.
       - touches_operations ⊆ API__*.yaml operation_ids (a bare resource_id is
         rejected); touches_entities ⊆ DATA-MODEL.yaml entities;
         implements_surfaces ⊆ UX.yaml SCR ids; implements_workflows ⊆ PRD WKF
         ids; touches_assets ⊆ DESIGN__assets.yaml AST ids.
       - involves_containers / build_order / container_task_graphs resolve to
         ARCH.yaml.
       - depends_on entries resolve across the union of all task files, and the
         union graph is acyclic.
    6. Coverage cross-checks (trace-or-defer; block status: complete). An item is
       covered if a task names it OR a task realizes a component that traces it
       (transitive credit); otherwise it must be deferred via a WRN-NNN:
       - Container: every component_id; every container TST-NNN; every SCR in the
         container's owns_ux_surfaces (needs UX.yaml to map slug→SCR); every
         operation_id of an owned API resource; every entity its components
         trace; every FR/NFR in its implements_requirements; (token_based_ui
         frontends) a design task wiring the tokens; and — the atomicity gate —
         every component work_unit (ARCH work_units[].name) named by exactly one
         task's target_symbol (always blocking; no coarse fallback).
       - System: every system TST-NNN.
       - Union: every PRD must-have FR is realized somewhere or deferred (hard
         only once the whole graph is stitched; advisory before).
       Surface/operation gates soften to advisory when UX/API are absent.

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


# `kind` is validated as a plain string against these sets in the checks (not a
# strict pydantic enum) so a draft with an off-vocabulary kind stays loadable
# and reports a fixable error instead of crashing the parse.
CONTAINER_KINDS = {
    "scaffold", "implementation", "test", "integration", "migration", "config",
    "design", "chore",
}
SYSTEM_KINDS = {
    "scaffold", "integration", "test", "config", "migration", "design",
    "deploy-prep", "docs", "chore",
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
    target_symbol: Optional[str] = None  # the SINGLE work_units[].name on component_ref
    implements: Optional[List[str]] = None
    implements_tests: Optional[List[str]] = None
    implements_surfaces: Optional[List[str]] = None
    implements_workflows: Optional[List[str]] = None
    touches_entities: Optional[List[str]] = None
    touches_operations: Optional[List[str]] = None
    touches_assets: Optional[List[str]] = None
    depends_on: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    target_files: Optional[List[str]] = None  # codegen write targets; grounded
                                              # in the component's code_location.
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
    target_files: Optional[List[str]] = None
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
    build_order: Optional[List[str]] = None
    tasks: Optional[List[SystemTask]] = None
    container_task_graphs: Optional[List[ContainerTaskGraphRef]] = None
    task_warnings: Optional[List[str]] = None


class TasksContainer(BaseModel):
    metadata: ContainerMetadata
    container_id: Optional[str] = None
    overview: Optional[str] = None
    inherits_from: Optional[str] = None
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
_SCR_RE = re.compile(r"^SCR-\d{3,}$", re.IGNORECASE)
_WKF_RE = re.compile(r"^WKF-\d{3,}$", re.IGNORECASE)
_AST_RE = re.compile(r"^AST-\d{3,}$", re.IGNORECASE)
_OPR_RE = re.compile(r"^OPR-\d{3,}$", re.IGNORECASE)
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


def _code_location_bases(code_location: List[str]) -> List[str]:
    """Normalize a component's code_location into directory/exact prefixes to
    test target_files against. A file-looking entry (a dot in its last segment)
    also contributes its parent directory, honouring the schema's
    'directory-firm, file-illustrative' rule."""
    bases: List[str] = []
    for cl in code_location or []:
        c = str(cl).strip().replace("\\", "/").rstrip("/")
        if not c:
            continue
        bases.append(c)
        last = c.rsplit("/", 1)[-1]
        if "." in last and "/" in c:        # looks like a file → allow its dir
            bases.append(c.rsplit("/", 1)[0])
    return bases


def _path_within_any(path: str, bases: List[str]) -> bool:
    """True if `path` equals or sits under any normalized base prefix."""
    p = str(path).strip().replace("\\", "/").rstrip("/")
    if not p:
        return True  # empty path isn't a placement claim — don't flag it
    for b in bases:
        if p == b or p.startswith(b + "/"):
            return True
    return False


# =============================================================================
# Upstream loaders (PRD / ARCH / ARCH__<cid> / TEST-STRATEGY(.__cid))
# =============================================================================


def load_prd_id_families(prd_path: Path) -> Dict[str, Set[str]]:
    """Return id sets declared in PRD.yaml (monorepo-aware):
      FR       — every functional requirement (must + nice).
      FR_MUST  — must_have_features only (the global-coverage target).
      NFR      — non-functional requirements.
      WKF      — use_cases.core_workflows ids.
    """
    fams: Dict[str, Set[str]] = {"FR": set(), "FR_MUST": set(), "NFR": set(), "WKF": set()}
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
                        fid = mm.group(0).upper()
                        fams["FR"].add(fid)
                        if key == "must_have_features":
                            fams["FR_MUST"].add(fid)
        nfreqs = node.get("non_functional_requirements") or {}
        if isinstance(nfreqs, dict):
            for key in ("performance_targets", "other"):
                for item in nfreqs.get(key) or []:
                    mm = re.match(r"^NFR-\d+", str(item).strip(), re.IGNORECASE)
                    if mm:
                        fams["NFR"].add(mm.group(0).upper())
        ucs = node.get("use_cases") or {}
        if isinstance(ucs, dict):
            for item in ucs.get("core_workflows") or []:
                mm = re.match(r"^WKF-\d+", str(item).strip(), re.IGNORECASE)
                if mm:
                    fams["WKF"].add(mm.group(0).upper())

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
        self.owns_ux: Dict[str, Set[str]] = {}          # cid -> {surface slugs}
        self.owns_api: Dict[str, Set[str]] = {}         # cid -> {resource_ids}
        self.persistence: Dict[str, Set[str]] = {}      # cid -> {store_ids}
        self.archetype: Dict[str, str] = {}             # cid -> archetype
        self.non_container_features: Set[str] = set()   # {FR} delivered off-container
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
        info.archetype[cid] = archetype
        external = bool(c.get("external"))
        if (not external) and archetype not in INFRA_ARCHETYPES and archetype != "external-service":
            info.testable.add(cid)
        info.implements[cid] = _req_tokens_in(c.get("implements_requirements") or [])
        info.owns_ux[cid] = {str(s).strip() for s in (c.get("owns_ux_surfaces") or [])}
        info.owns_api[cid] = {str(s).strip() for s in (c.get("owns_api_resources") or [])}
        info.persistence[cid] = {str(s).strip() for s in (c.get("persistence") or [])}
    for fr in raw.get("non_container_features") or []:
        mm = re.match(r"^FR-\d+", str(fr).strip(), re.IGNORECASE)
        if mm:
            info.non_container_features.add(mm.group(0).upper())
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
        # component_id -> its code_location list (repo-relative dirs/files).
        self.component_code_location: Dict[str, List[str]] = {}
        # component_id -> per-component upstream traces (for transitive coverage
        # credit: a REALIZED component covers everything it traces).
        self.comp_archetype: Dict[str, str] = {}
        self.comp_ux: Dict[str, Set[str]] = {}        # surface slugs
        self.comp_api_res: Dict[str, Set[str]] = {}   # resource_ids
        self.comp_api_op: Dict[str, Set[str]] = {}    # operation_ids / OPR-NNN
        self.comp_entities: Dict[str, Set[str]] = {}  # entity names
        self.comp_reqs: Dict[str, Set[str]] = {}      # FR/NFR
        self.comp_units: Dict[str, Set[str]] = {}     # component_id -> {work_unit names}
        # union of every component's traces_data_entities (the container's
        # architecture-declared entity footprint = the entity-coverage expected set)
        self.all_entities: Set[str] = set()


def _strset(node: dict, key: str) -> Set[str]:
    return {str(x).strip() for x in (node.get(key) or []) if str(x).strip()}


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
        if not coid:
            continue
        info.component_ids.add(coid)
        cl = comp.get("code_location")
        if isinstance(cl, list):
            info.component_code_location[coid] = [str(x) for x in cl]
        info.comp_archetype[coid] = (comp.get("archetype") or "").strip()
        info.comp_ux[coid] = _strset(comp, "traces_ux_surfaces")
        info.comp_api_res[coid] = _strset(comp, "traces_api_resources")
        info.comp_api_op[coid] = _strset(comp, "traces_api_operations")
        info.comp_entities[coid] = _strset(comp, "traces_data_entities")
        info.comp_reqs[coid] = _req_tokens_in(comp.get("implements_requirements") or [])
        info.implements |= info.comp_reqs[coid]
        info.all_entities |= info.comp_entities[coid]
        units: Set[str] = set()
        for wu in comp.get("work_units") or []:
            if isinstance(wu, dict) and wu.get("name"):
                units.add(str(wu["name"]).strip())
        info.comp_units[coid] = units
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


class UxInfo:
    """slug↔SCR maps from UX.yaml (monorepo-aware)."""

    def __init__(self) -> None:
        self.present: bool = False
        self.scr_ids: Set[str] = set()          # all SCR-NNN
        self.slug_to_scr: Dict[str, str] = {}   # surface_id slug -> SCR-NNN
        self.scr_to_slug: Dict[str, str] = {}   # SCR-NNN -> slug

    def to_scr(self, token: str) -> Optional[str]:
        """Normalize a surface token (SCR-NNN or slug) to its SCR-NNN."""
        t = str(token).strip()
        if _SCR_RE.match(t):
            return t.upper()
        return self.slug_to_scr.get(t)


def load_ux(ux_path: Path) -> UxInfo:
    info = UxInfo()
    raw = _safe_yaml(ux_path)
    if raw is None:
        return info
    info.present = True
    monorepo = bool((raw.get("metadata") or {}).get("monorepo"))

    def _pull(node: dict) -> None:
        for s in node.get("surface_inventory") or []:
            if not isinstance(s, dict):
                continue
            scr = s.get("id")
            slug = s.get("surface_id")
            if scr and _SCR_RE.match(str(scr)):
                scr = str(scr).upper()
                info.scr_ids.add(scr)
                if slug:
                    info.slug_to_scr[str(slug).strip()] = scr
                    info.scr_to_slug[scr] = str(slug).strip()

    if monorepo:
        for prod in (raw.get("products") or {}).values():
            if isinstance(prod, dict):
                _pull(prod)
    else:
        _pull(raw)
    return info


class ApiInfo:
    """resource→operation map across API__*.yaml (operation_id + OPR-NNN)."""

    def __init__(self) -> None:
        self.present: bool = False
        self.all_ops: Set[str] = set()            # operation_ids (+ OPR-NNN)
        self.resources: Set[str] = set()          # resource_ids
        self.resource_to_ops: Dict[str, Set[str]] = {}


def load_api(docs_dir: Path) -> ApiInfo:
    info = ApiInfo()
    for p in sorted(docs_dir.glob("API__*.yaml")):
        raw = _safe_yaml(p)
        if raw is None:
            continue
        info.present = True
        rid = raw.get("resource_id") or p.stem[len("API__"):]
        rid = str(rid).strip()
        info.resources.add(rid)
        ops: Set[str] = info.resource_to_ops.setdefault(rid, set())
        for ep in raw.get("endpoints") or []:
            if not isinstance(ep, dict):
                continue
            for key in ("operation_id", "id"):
                v = ep.get(key)
                if v:
                    ops.add(str(v).strip())
                    info.all_ops.add(str(v).strip())
    return info


def load_data_entities(data_path: Path) -> Tuple[Set[str], bool, bool]:
    """Return (entity names, present, polyglot). Single-store DATA models let the
    advisory entity check flag store-resident-but-untraced entities."""
    raw = _safe_yaml(data_path)
    if raw is None:
        return set(), False, False
    ents = raw.get("entities")
    names = set(ents.keys()) if isinstance(ents, dict) else set()
    polyglot = bool((raw.get("persistence") or {}).get("polyglot"))
    return {str(n) for n in names}, True, polyglot


class DesignInfo:
    def __init__(self) -> None:
        self.present: bool = False
        self.functional_structure: Set[str] = set()   # token_based_ui|asset_pipeline|headless
        self.ast_ids: Set[str] = set()                # AST-NNN from DESIGN__assets.yaml


def load_design(docs_dir: Path) -> DesignInfo:
    info = DesignInfo()
    raw = _safe_yaml(docs_dir / "DESIGN.yaml")
    if raw is not None:
        info.present = True
        fs = raw.get("functional_structure")
        if isinstance(fs, list):
            info.functional_structure = {str(x).strip() for x in fs}
        elif isinstance(fs, str):
            info.functional_structure = {fs.strip()}
    assets = _safe_yaml(docs_dir / "DESIGN__assets.yaml")
    if assets is not None:
        for a in assets.get("assets") or []:
            if isinstance(a, dict) and a.get("id") and _AST_RE.match(str(a["id"])):
                info.ast_ids.add(str(a["id"]).upper())
    return info


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
        # Atomic-codegen pin: an implementation task names exactly one callable
        # (target_symbol) housed in exactly one file (target_files).
        if t.kind == "implementation":
            if not (t.target_symbol or "").strip():
                missing.append(f"tasks[{i}].target_symbol (required for kind:implementation)")
            if not t.target_files or len(t.target_files) != 1:
                missing.append(
                    f"tasks[{i}].target_files (kind:implementation needs exactly one entry)"
                )
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
    ux: UxInfo,
    api: ApiInfo,
    data_ents: Set[str],
    data_present: bool,
    design: DesignInfo,
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
    explicit_surfaces: Set[str] = set()   # SCR-NNN, normalized
    explicit_ops: Set[str] = set()
    explicit_entities: Set[str] = set()
    realized_ast: Set[str] = set()
    realized_units: Set[Tuple[str, str]] = set()   # (component_ref, target_symbol) built
    symbol_task_count: Dict[Tuple[str, str], int] = {}   # for the uniqueness gate
    has_design_task = False

    for i, t in enumerate(m.tasks or []):
        if t.kind == "design":
            has_design_task = True
        if t.component_ref:
            covered_components.add(t.component_ref)
            if ac.present and t.component_ref not in ac.component_ids:
                errs.append(f"{label} tasks[{i}].component_ref '{t.component_ref}' is not a component in ARCH__{cid}.yaml")
        # target_symbol — the atomic scope: the ONE work_unit name of the task's
        # component that this task builds.
        sym = (t.target_symbol or "").strip()
        if sym:
            if not t.component_ref:
                errs.append(f"{label} tasks[{i}].target_symbol names '{sym}' but the task has no component_ref to resolve it against")
            elif ac.present and t.component_ref in ac.component_ids:
                comp_units = ac.comp_units.get(t.component_ref, set())
                if comp_units and sym not in comp_units:
                    errs.append(f"{label} tasks[{i}].target_symbol '{sym}' is not a work_units[].name on component '{t.component_ref}' in ARCH__{cid}.yaml")
                else:
                    realized_units.add((t.component_ref, sym))
            elif t.component_ref:
                realized_units.add((t.component_ref, sym))
            key = (t.component_ref or "", sym)
            symbol_task_count[key] = symbol_task_count.get(key, 0) + 1
        # target_files grounding (advisory) — a component-scoped task's write
        # targets should sit within the owning component's code_location.
        if t.component_ref and t.target_files:
            bases = _code_location_bases(ac.component_code_location.get(t.component_ref, []))
            if bases:
                for tf in t.target_files:
                    if not _path_within_any(tf, bases):
                        warns.append(
                            f"{label} tasks[{i}] target_file '{tf}' is outside "
                            f"component '{t.component_ref}' code_location "
                            f"({sorted(set(bases))}) — confirm placement"
                        )
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

        # --- new typed ref-field validation ---
        for ref in t.touches_operations or []:
            r = str(ref).strip()
            if not api.present:
                explicit_ops.add(r)               # cannot validate; accept
            elif r in api.all_ops:
                explicit_ops.add(r)
            elif r in api.resources:
                errs.append(f"{label} tasks[{i}].touches_operations '{r}' is a resource_id, not an operation — list its endpoints[].operation_id (or an OPR-NNN)")
            else:
                errs.append(f"{label} tasks[{i}].touches_operations '{r}' is not an operation_id/OPR-NNN in any API__*.yaml")
        for ref in t.touches_entities or []:
            e = str(ref).strip()
            if data_present and e not in data_ents:
                errs.append(f"{label} tasks[{i}].touches_entities '{e}' is not a DATA-MODEL entity")
            else:
                explicit_entities.add(e)
        for ref in t.implements_surfaces or []:
            s = str(ref).strip()
            if not _SCR_RE.match(s):
                errs.append(f"{label} tasks[{i}].implements_surfaces '{ref}' is not an SCR-NNN id")
            elif ux.present and s.upper() not in ux.scr_ids:
                errs.append(f"{label} tasks[{i}].implements_surfaces '{ref}' is not a surface in UX.yaml")
            else:
                explicit_surfaces.add(s.upper())
        for ref in t.implements_workflows or []:
            w = str(ref).strip().upper()
            if not _WKF_RE.match(w):
                errs.append(f"{label} tasks[{i}].implements_workflows '{ref}' is not a WKF-NNN id")
            elif fams["WKF"] and w not in fams["WKF"]:
                errs.append(f"{label} tasks[{i}].implements_workflows '{ref}' does not resolve to a PRD workflow")
        for ref in t.touches_assets or []:
            a = str(ref).strip().upper()
            if not _AST_RE.match(a):
                errs.append(f"{label} tasks[{i}].touches_assets '{ref}' is not an AST-NNN id")
            elif design.present and design.ast_ids and a not in design.ast_ids:
                errs.append(f"{label} tasks[{i}].touches_assets '{ref}' is not an asset in DESIGN__assets.yaml")
            else:
                realized_ast.add(a)

    # --- transitive coverage credit: a REALIZED component covers everything it
    #     traces (the codegen sub-agent building it reads its ARCH trace). ---
    trans_surfaces: Set[str] = set()
    trans_ops: Set[str] = set()
    trans_entities: Set[str] = set()
    trans_reqs: Set[str] = set()
    for comp in covered_components:
        for slug in ac.comp_ux.get(comp, set()):
            scr = ux.to_scr(slug)
            if scr:
                trans_surfaces.add(scr)
        trans_ops |= ac.comp_api_op.get(comp, set())
        for res in ac.comp_api_res.get(comp, set()):
            trans_ops |= api.resource_to_ops.get(res, set())
        trans_entities |= ac.comp_entities.get(comp, set())
        trans_reqs |= ac.comp_reqs.get(comp, set())

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

    # Surface coverage (trace-or-defer; soften when UX.yaml is absent).
    owned_slugs = arch.owns_ux.get(cid, set()) if cid else set()
    if owned_slugs:
        if ux.present:
            realized_scr = explicit_surfaces | trans_surfaces
            for slug in sorted(owned_slugs):
                scr = ux.to_scr(slug)
                if scr is None:
                    warns.append(f"{label} owns_ux_surface '{slug}' has no SCR id in UX.yaml")
                    continue
                defer_keys = {scr, slug}
                if scr not in realized_scr and not _deferred_literals(warnings, defer_keys):
                    errs.append(f"{label} surface coverage: {scr} ({slug}) (owns_ux_surfaces) is realized by no task and no WRN-NNN defers it")
        else:
            warns.append(f"{label} surface coverage not checked — UX.yaml absent (cannot resolve {len(owned_slugs)} owned surface slug(s) to SCR ids)")

    # Operation coverage (trace-or-defer; soften when no API__*.yaml is present).
    owned_res = arch.owns_api.get(cid, set()) if cid else set()
    if owned_res:
        if api.present:
            expected_ops: Set[str] = set()
            for res in owned_res:
                expected_ops |= api.resource_to_ops.get(res, set())
            realized_ops = explicit_ops | trans_ops
            # An operation set carries both operation_id and OPR-NNN for the same
            # endpoint; realizing either covers it. Compare the human operation_id
            # names (skip the bare OPR-NNN duplicates the resource map also holds).
            for op in sorted(expected_ops):
                if _OPR_RE.match(op):
                    continue
                if op not in realized_ops and not _deferred_literals(warnings, {op}):
                    errs.append(f"{label} operation coverage: operation '{op}' (owned API resource) is realized by no task and no WRN-NNN defers it")
        else:
            warns.append(f"{label} operation coverage not checked — no API__*.yaml present")

    # Entity coverage (trace-or-defer over the container's component-declared
    # entity footprint; transitive credit via a realized repository component).
    expected_ents = set(ac.all_entities)
    if expected_ents:
        realized_ents = explicit_entities | trans_entities
        for e in sorted(expected_ents):
            if e not in realized_ents and not _deferred_literals(warnings, {e}):
                errs.append(f"{label} entity coverage: entity '{e}' (traced by a component) is realized by no task and no WRN-NNN defers it")

    # Requirement coverage (trace-or-defer; promoted from advisory to blocking).
    realized_reqs = named_reqs | trans_reqs
    deferred_reqs = {x.upper() for x in _deferred_literals(warnings, allowed_reqs)}
    for r in sorted(allowed_reqs):
        if r not in realized_reqs and r not in deferred_reqs:
            errs.append(f"{label} requirement coverage: {r} is in implements_requirements but realized by no task and no WRN-NNN defers it")

    # Work-unit coverage (the atomicity gate — always BLOCKING). Every component
    # work_unit (ARCH work_units[].name) must be realized OR deferred. A work_unit
    # is realized only when exactly ONE task NAMES it in target_symbol (a bare
    # component_ref does NOT transitively cover its work_units — that is the point);
    # otherwise defer it with a WRN-NNN. Softens to a no-op only for a component
    # that declares no work_units (pure plumbing — there is no coarse fallback).
    for coid, unit_names in ac.comp_units.items():
        for name in sorted(unit_names):
            if (coid, name) in realized_units:
                continue
            if _deferred_literals(warnings, {name}):
                continue
            errs.append(
                f"{label} work-unit coverage: work_unit '{name}' of component "
                f"'{coid}' (ARCH__{cid}) is realized by no task's target_symbol and "
                f"no WRN-NNN defers it"
            )
    # target_symbol uniqueness — each work_unit is built by exactly one task.
    for (comp_ref, sym), n in sorted(symbol_task_count.items()):
        if n > 1:
            errs.append(
                f"{label} target_symbol '{sym}' (component '{comp_ref}') is named by "
                f"{n} tasks — each work_unit must be built by exactly one task"
            )

    # Design coverage — a token_based_ui frontend that owns surfaces needs a
    # design task wiring the tokens/theme (or a defer); assets stay advisory.
    if owned_slugs and design.present and "token_based_ui" in design.functional_structure:
        if not has_design_task and not any(
            kw in w.lower() for w in warnings for kw in ("design", "token", "theme")
        ):
            errs.append(f"{label} design coverage: container owns surfaces and DESIGN uses token_based_ui, but no kind:design task wires the tokens/theme (defer via a WRN-NNN if intentional)")
    if owned_slugs and design.present and "asset_pipeline" in design.functional_structure:
        for ast in sorted(design.ast_ids):
            if ast not in realized_ast and not _deferred_literals(warnings, {ast}):
                warns.append(f"{label} asset {ast} (DESIGN__assets) has no scaffolding/brief task")
    return errs, warns


# =============================================================================
# Global (union) coverage — the "convert all FRs" guarantee + entity advisory
# =============================================================================


def global_coverage(
    sysm: Optional[TasksSystem],
    containers: List[Tuple[str, TasksContainer]],
    fams: Dict[str, Set[str]],
    arch: ArchInfo,
    docs_dir: Path,
    data_ents: Set[str],
    data_present: bool,
) -> Tuple[List[str], List[str], bool]:
    """Returns (fr_gaps, entity_warnings, fully_stitched).

    fr_gaps        — PRD must_have FRs realized by no task across the union and
                     not deferred / non-container. Blocking only when the graph
                     is fully stitched (caller decides).
    entity_warnings— DATA entities traced by no component in any present
                     container file (likely an ARCH gap) — always advisory.
    fully_stitched — system file complete AND every buildable ARCH container has
                     a TASKS__*.json present (so an all-FR gate is fair).
    """
    must = set(fams["FR_MUST"])
    realized: Set[str] = set()
    deferred: Set[str] = set(arch.non_container_features)
    traced_entities: Set[str] = set()

    if sysm is not None:
        for t in sysm.tasks or []:
            realized |= {r.upper() for r in (t.implements or []) if _FR_RE.match(str(r).upper())}
        deferred |= _deferred_literals(sysm.task_warnings or [], must)

    present_cids: Set[str] = set()
    for cid, cm in containers:
        present_cids.add(cid)
        ac = load_arch_container(docs_dir, cid)
        traced_entities |= ac.all_entities
        covered_comps = {t.component_ref for t in (cm.tasks or []) if t.component_ref}
        for t in cm.tasks or []:
            realized |= {r.upper() for r in (t.implements or []) if _FR_RE.match(str(r).upper())}
        for comp in covered_comps:
            realized |= {r for r in ac.comp_reqs.get(comp, set()) if _FR_RE.match(r)}
        deferred |= _deferred_literals(cm.task_warnings or [], must)

    fr_gaps = [
        f"global requirement coverage: must-have {r} (PRD) is realized by no task in any file and is not deferred/non-container"
        for r in sorted(must - realized - deferred)
    ]

    ent_warns: List[str] = []
    if data_present and data_ents:
        for e in sorted(data_ents - traced_entities):
            ent_warns.append(
                f"DATA entity '{e}' is traced by no component in any built container — likely an ARCH gap; it will get no migration/repository task"
            )

    sys_complete = sysm is not None and sysm.metadata.status == Status.complete
    fully_stitched = bool(sys_complete and arch.testable and arch.testable <= present_cids)
    return fr_gaps, ent_warns, fully_stitched


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
    ux = load_ux(docs_dir / "UX.yaml")
    api = load_api(docs_dir)
    data_ents, data_present, _polyglot = load_data_entities(docs_dir / "DATA-MODEL.yaml")
    design = load_design(docs_dir)

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
        c_errs, c_warns = check_container(
            cm, fams, arch, docs_dir, ux, api, data_ents, data_present, design
        )
        blocking += [f"{cp.name}: {e}" for e in c_errs]
        warnings += [f"{cp.name}: {w}" for w in c_warns]

    if parse_failed:
        return 1

    # Union-graph dependency resolution + acyclicity (the stitch).
    blocking += [f"graph: {e}" for e in check_dependencies_and_cycles(sysm, containers)]

    # Global (union) requirement coverage + orphaned-entity advisory.
    fr_gaps, ent_warns, fully_stitched = global_coverage(
        sysm, containers, fams, arch, docs_dir, data_ents, data_present
    )
    # The all-FR gate is only fair once the whole graph is stitched (system file
    # complete AND every buildable container present). Before that it is advisory
    # — an FR owned by a not-yet-built container must not fail the early files.
    if fully_stitched:
        blocking += [f"union: {e}" for e in fr_gaps]
        # "traced by no component anywhere" is only a definitive ARCH gap once
        # every container is built; before that the picture is partial, so the
        # entity advisory would be noisy (a frontend-only run traces no entities).
        warnings += [f"union: {w}" for w in ent_warns]
    else:
        warnings += [f"union: {e} (advisory until the graph is fully stitched)" for e in fr_gaps]

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
