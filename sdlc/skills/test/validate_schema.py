"""Validate TEST-STRATEGY.yaml + every TEST-STRATEGY__*.yaml against the
sdlc-test schemas, and run the coverage cross-check suite (the trace-or-defer
contract from CLAUDE.md §6).

Run from the project root:

    python sdlc/skills/test/validate_schema.py
    python sdlc/skills/test/validate_schema.py --path docs/TEST-STRATEGY.yaml

The --path argument only locates the docs directory: the system file
(TEST-STRATEGY.yaml) and every sibling TEST-STRATEGY__*.yaml in the same
directory are validated together, with their upstream PRD.yaml / ARCH.yaml /
ARCH__*.yaml read for the cross-checks.

Validates:
    1. docs/TEST-STRATEGY.yaml — system test strategy (global policy + the
       cross-container e2e/contract suite).
    2. Every docs/TEST-STRATEGY__*.yaml sibling — one per container.
    3. Required-field checks (status: complete gate).
    4. ID-prefix formats: TST-NNN on every tst_id — unique per file AND
       GLOBALLY unique across the system file + every container file (the
       TST counter is one continuous space; downstream Task.test_refs assumes
       a single namespace, so per-file restarts at TST-001 collide). WRN-NNN
       on every test_strategy_warnings entry (WRN stays per-artifact).
    5. Reference integrity (block status: complete):
       - covers entries are FR/NFR/ACR/WKF and resolve to PRD ids.
       - involves_containers / container_strategies resolve to ARCH.yaml.
       - component_ref resolves to the matching ARCH__<container>.yaml;
         unit-tier tests must set it.
       - targets_failure_mode / targets_security_concern resolve to an id in
         the matching ARCH__<container>.yaml.
       - a container test's covered FR/NFR ⊆ the container's + targeted
         component's implements_requirements.
    6. Coverage cross-checks (trace-or-defer; block status: complete):
       - System: every cross-container PRD WKF-NNN is covered by some system
         test OR deferred via a WRN-NNN.
       - Container: every implements_requirements FR/NFR, every component that
         declares acceptance_criteria, and every failure_modes[].id /
         security_concerns[].id in the ARCH container file is covered by some
         test OR deferred via a WRN-NNN.

Exit codes:
    0 — schema valid; status='complete' (all checks passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but a cross-check failed.
    2 — could not read or parse any test-strategy file (none present, bad YAML).
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
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


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class TestTier(str, Enum):
    unit = "unit"
    integration = "integration"
    e2e = "e2e"
    contract = "contract"
    property = "property"
    load = "load"
    security = "security"
    accessibility = "accessibility"


class Priority(str, Enum):
    must = "must"
    should = "should"
    could = "could"


class TestStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"


# =============================================================================
# Pydantic models. Almost every field is Optional: the schema's "REQUIRED"
# fields are enforced by check_required() only when status == complete, so a
# status: draft artifact validates even with holes (the documented contract).
# Unknown keys are ignored (pydantic v2 default) so confidence/rationale
# siblings and manual edits don't break validation.
# =============================================================================


class SystemMetadata(BaseModel):
    test_strategy_version: Optional[str] = None
    last_updated: Optional[str] = None
    generated_by: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[Status] = None
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class ContainerMetadata(BaseModel):
    test_strategy_container_version: Optional[str] = None
    last_updated: Optional[str] = None
    generated_by: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[Status] = None
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class TestApproach(BaseModel):
    pyramid_targets: Optional[Dict[str, str]] = None
    pyramid_targets_confidence: Optional[Confidence] = None
    pyramid_rationale: Optional[str] = None
    ai_builder_notes: Optional[str] = None


class CovOverride(BaseModel):
    line_pct: Optional[float] = None
    branch_pct: Optional[float] = None


class CoverageThreshold(BaseModel):
    line_pct: Optional[float] = None
    line_pct_confidence: Optional[Confidence] = None
    branch_pct: Optional[float] = None
    rationale: Optional[str] = None
    per_container_overrides: Optional[Dict[str, CovOverride]] = None


class Environment(BaseModel):
    name: Optional[str] = None
    purpose: Optional[str] = None


class SystemTest(BaseModel):
    tst_id: Optional[str] = None
    name: Optional[str] = None
    tier: Optional[TestTier] = None
    description: Optional[str] = None
    directives: Optional[List[str]] = None
    covers: Optional[List[str]] = None
    involves_containers: Optional[List[str]] = None
    priority: Optional[Priority] = None
    setup: Optional[str] = None
    acceptance: Optional[str] = None
    status: Optional[TestStatus] = None


class ContainerStrategyRef(BaseModel):
    container_id: Optional[str] = None
    file_path: Optional[str] = None


class TestStrategySystem(BaseModel):
    metadata: SystemMetadata
    test_approach: Optional[TestApproach] = None
    coverage_threshold: Optional[CoverageThreshold] = None
    mock_policy: Optional[str] = None
    mock_policy_confidence: Optional[Confidence] = None
    mock_policy_rationale: Optional[str] = None
    fixture_strategy: Optional[str] = None
    fixture_strategy_confidence: Optional[Confidence] = None
    fixture_strategy_rationale: Optional[str] = None
    test_data_strategy: Optional[str] = None
    ci_integration: Optional[str] = None
    environments: Optional[List[Environment]] = None
    tests: Optional[List[SystemTest]] = None
    container_strategies: Optional[List[ContainerStrategyRef]] = None
    test_strategy_warnings: Optional[List[str]] = None


class ContainerCoverageTarget(BaseModel):
    line_pct: Optional[float] = None
    line_pct_confidence: Optional[Confidence] = None
    branch_pct: Optional[float] = None
    rationale: Optional[str] = None


class ContainerTest(BaseModel):
    tst_id: Optional[str] = None
    name: Optional[str] = None
    tier: Optional[TestTier] = None
    description: Optional[str] = None
    component_ref: Optional[str] = None
    targets_work_unit: Optional[str] = None   # work_units[].name of component_ref
    targets_operation: Optional[str] = None   # DEPRECATED pre-1.2 alias (OPN-NNN of the
                                              # retired ARCH operations[] family); parsed
                                              # for backward compat, warns, never blocks
    directives: Optional[List[str]] = None
    covers: Optional[List[str]] = None
    targets_failure_mode: Optional[str] = None
    targets_security_concern: Optional[str] = None
    priority: Optional[Priority] = None
    setup: Optional[str] = None
    fixtures: Optional[List[str]] = None
    mocks: Optional[List[str]] = None
    acceptance: Optional[str] = None
    status: Optional[TestStatus] = None


class TestStrategyContainer(BaseModel):
    metadata: ContainerMetadata
    container_id: Optional[str] = None
    overview: Optional[str] = None
    inherits_from: Optional[str] = None
    coverage_target: Optional[ContainerCoverageTarget] = None
    mock_policy: Optional[str] = None
    fixture_strategy: Optional[str] = None
    test_environment: Optional[str] = None
    tests: Optional[List[ContainerTest]] = None
    test_strategy_warnings: Optional[List[str]] = None


# =============================================================================
# Regexes + small helpers
# =============================================================================

_TST_RE = re.compile(r"^TST-\d{3,}$")
_WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
_FR_RE = re.compile(r"^FR-\d+$", re.IGNORECASE)
_NFR_RE = re.compile(r"^NFR-\d+$", re.IGNORECASE)
_ACR_RE = re.compile(r"^ACR-\d+$", re.IGNORECASE)
_WKF_RE = re.compile(r"^WKF-\d+$", re.IGNORECASE)

_REQ_TOKEN_RE = re.compile(r"\b(?:FR|NFR|ACR|WKF)-\d+\b", re.IGNORECASE)

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


def _req_tokens_in(strings: List[str]) -> Set[str]:
    """Every FR/NFR/ACR/WKF token appearing anywhere in a list of strings."""
    out: Set[str] = set()
    for s in strings or []:
        if isinstance(s, str):
            for m in _REQ_TOKEN_RE.findall(s):
                out.add(m.upper())
    return out


def _deferred_literals(warnings: List[str], ids: Set[str]) -> Set[str]:
    """Subset of `ids` (kebab-case ids) named as whole words in any warning."""
    deferred: Set[str] = set()
    for i in ids:
        pat = re.compile(r"\b" + re.escape(i) + r"\b")
        if any(isinstance(w, str) and pat.search(w) for w in (warnings or [])):
            deferred.add(i)
    return deferred


# =============================================================================
# Upstream loaders (PRD / ARCH / ARCH__<container>)
# =============================================================================


def load_prd_id_families(prd_path: Path) -> Dict[str, Set[str]]:
    """Return {'FR','NFR','WKF','ACR'} id sets declared in PRD.yaml.

    FR from functional_requirements.must/nice; NFR from
    non_functional_requirements.performance_targets + .other; WKF from
    use_cases.core_workflows; ACR via a raw token scan (acceptance criteria
    are nested per FR/NFR/USR). Honors monorepo mode.
    """
    fams: Dict[str, Set[str]] = {"FR": set(), "NFR": set(), "WKF": set(), "ACR": set()}
    raw_text = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""
    for m in re.findall(r"\bACR-\d+\b", raw_text, re.IGNORECASE):
        fams["ACR"].add(m.upper())
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
        self.implements: Dict[str, Set[str]] = {}   # cid -> {FR/NFR}
        self.workflows: Dict[str, Set[str]] = {}     # cid -> {WKF}
        self.acceptance: Dict[str, bool] = {}        # cid -> has acceptance_criteria
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
        info.workflows[cid] = _req_tokens_in(c.get("traces_prd_workflows") or [])
        ac = c.get("acceptance_criteria") or []
        info.acceptance[cid] = bool(ac)
    return info


class ArchContainerInfo:
    """Parsed view of one ARCH__<container>.yaml for the coverage gate."""

    def __init__(self) -> None:
        self.present: bool = False
        self.component_ids: Set[str] = set()
        self.implements: Set[str] = set()                 # union of all implements_requirements
        self.components_with_acceptance: Set[str] = set()
        self.failure_mode_ids: Set[str] = set()
        self.security_concern_ids: Set[str] = set()
        self.comp_units: Dict[str, Set[str]] = {}         # component_id -> {work_units[].name}
                                                          # (names unique only per component)


def _collect_struct_ids(items: Any, key: str) -> Set[str]:
    """Ids from a list whose entries may be {id: ...} dicts or bare strings.
    Bare strings (the v1.0 backwards-compat shape) carry no stable id → skipped.
    """
    out: Set[str] = set()
    for it in items or []:
        if isinstance(it, dict):
            v = it.get(key)
            if isinstance(v, str) and v and v != "auto":
                out.add(v)
    return out


def load_arch_container(docs_dir: Path, cid: str) -> ArchContainerInfo:
    info = ArchContainerInfo()
    raw = _safe_yaml(docs_dir / f"ARCH__{cid}.yaml")
    if raw is None:
        return info
    info.present = True
    info.failure_mode_ids |= _collect_struct_ids(raw.get("failure_modes"), "id")
    info.security_concern_ids |= _collect_struct_ids(raw.get("security_concerns"), "id")
    for comp in raw.get("components") or []:
        if not isinstance(comp, dict):
            continue
        coid = comp.get("component_id")
        if coid:
            info.component_ids.add(coid)
            if comp.get("acceptance_criteria"):
                info.components_with_acceptance.add(coid)
            units: Set[str] = set()
            for wu in comp.get("work_units") or []:
                if isinstance(wu, dict) and wu.get("name"):
                    units.add(str(wu["name"]).strip())
            info.comp_units[coid] = units
        info.implements |= _req_tokens_in(comp.get("implements_requirements") or [])
        info.failure_mode_ids |= _collect_struct_ids(comp.get("failure_modes"), "id")
    return info


# =============================================================================
# Field-level format / required checks
# =============================================================================


def check_warning_ids(warnings: Optional[List[str]], label: str) -> List[str]:
    errs: List[str] = []
    for i, w in enumerate(warnings or []):
        if not isinstance(w, str) or not _WRN_RE.match(w.strip()):
            errs.append(f"{label}.test_strategy_warnings[{i}]: '{w}' must match 'WRN-NNN: <message>'")
    return errs


def check_tst_ids(tests: List[Any], label: str) -> List[str]:
    errs: List[str] = []
    seen: Set[str] = set()
    for i, t in enumerate(tests or []):
        tid = getattr(t, "tst_id", None)
        if not tid:
            continue  # required-ness handled by check_required
        if not _TST_RE.match(str(tid)):
            errs.append(f"{label}.tests[{i}].tst_id '{tid}' must match 'TST-NNN'")
        elif tid in seen:
            errs.append(f"{label}.tests[{i}].tst_id '{tid}' is duplicated")
        else:
            seen.add(tid)
    return errs


def check_required_system(m: TestStrategySystem) -> List[str]:
    missing: List[str] = []
    if not (m.test_approach and m.test_approach.pyramid_targets):
        missing.append("test_approach.pyramid_targets")
    if not (m.coverage_threshold and m.coverage_threshold.line_pct is not None):
        missing.append("coverage_threshold.line_pct")
    if not m.mock_policy:
        missing.append("mock_policy")
    if not m.fixture_strategy:
        missing.append("fixture_strategy")
    if m.tests is None:
        missing.append("tests")
    for i, t in enumerate(m.tests or []):
        for fld in ("tst_id", "name", "tier", "description", "priority", "acceptance", "status"):
            if getattr(t, fld) in (None, ""):
                missing.append(f"tests[{i}].{fld}")
        if not t.directives:
            missing.append(f"tests[{i}].directives")
        if not t.covers:
            missing.append(f"tests[{i}].covers")
        if not t.involves_containers:
            missing.append(f"tests[{i}].involves_containers")
    return missing


def check_required_container(m: TestStrategyContainer) -> List[str]:
    missing: List[str] = []
    for fld in ("container_id", "overview", "coverage_target"):
        if getattr(m, fld) in (None, ""):
            missing.append(fld)
    if not m.tests:
        missing.append("tests (non-empty)")
    for i, t in enumerate(m.tests or []):
        for fld in ("tst_id", "name", "tier", "description", "priority", "acceptance", "status"):
            if getattr(t, fld) in (None, ""):
                missing.append(f"tests[{i}].{fld}")
        if not t.directives:
            missing.append(f"tests[{i}].directives")
    return missing


# =============================================================================
# Reference + coverage cross-checks
# =============================================================================


def check_system(
    m: TestStrategySystem,
    fams: Dict[str, Set[str]],
    arch: ArchInfo,
    docs_dir: Path,
) -> Tuple[List[str], List[str]]:
    """Return (blocking_errors, non_blocking_warnings) for the system file."""
    errs: List[str] = []
    warns: List[str] = []
    all_ids = fams["FR"] | fams["NFR"] | fams["ACR"] | fams["WKF"]

    covered_wkf: Set[str] = set()
    for i, t in enumerate(m.tests or []):
        for ref in t.covers or []:
            up = str(ref).upper()
            if not (_FR_RE.match(up) or _NFR_RE.match(up) or _ACR_RE.match(up) or _WKF_RE.match(up)):
                errs.append(f"tests[{i}].covers '{ref}' is not an FR/NFR/ACR/WKF id")
            elif up not in all_ids and (fams["FR"] or fams["WKF"]):
                errs.append(f"tests[{i}].covers '{ref}' does not resolve to a PRD id")
            if _WKF_RE.match(up):
                covered_wkf.add(up)
        for cid in t.involves_containers or []:
            if arch.present and cid not in arch.container_ids:
                errs.append(f"tests[{i}].involves_containers '{cid}' is not an ARCH container_id")

    # Workflow coverage (trace-or-defer): every cross-container WKF must be
    # covered by a system test or deferred via a warning.
    deferred = _req_tokens_in(m.test_strategy_warnings or [])
    if arch.present:
        wkf_container_count: Dict[str, int] = {}
        for cid, wset in arch.workflows.items():
            for w in wset:
                wkf_container_count[w] = wkf_container_count.get(w, 0) + 1
        cross_container_wkf = {w for w, n in wkf_container_count.items() if n >= 2}
        for w in sorted(cross_container_wkf):
            if w not in covered_wkf and w not in deferred:
                errs.append(
                    f"workflow coverage: {w} spans multiple containers but no system "
                    f"test covers it and no WRN-NNN defers it"
                )

    # container_strategies integrity (non-blocking).
    for ref in m.container_strategies or []:
        if ref.container_id and arch.present and ref.container_id not in arch.container_ids:
            warns.append(f"container_strategies: '{ref.container_id}' is not an ARCH container_id")
        if ref.file_path and not (docs_dir / Path(ref.file_path).name).exists():
            warns.append(f"container_strategies: file_path '{ref.file_path}' not found on disk")
    return errs, warns


def check_container(
    m: TestStrategyContainer,
    fams: Dict[str, Set[str]],
    arch: ArchInfo,
    docs_dir: Path,
) -> Tuple[List[str], List[str]]:
    """Return (blocking_errors, non_blocking_warnings) for one container file."""
    errs: List[str] = []
    warns: List[str] = []
    cid = m.container_id
    label = f"[{cid or '?'}]"
    all_ids = fams["FR"] | fams["NFR"] | fams["ACR"] | fams["WKF"]

    # Identity.
    if cid and arch.present:
        if cid not in arch.container_ids:
            errs.append(f"{label} container_id is not in ARCH.yaml")
        elif cid not in arch.testable:
            errs.append(f"{label} container_id is not a testable container (external or storage/infra)")
    ac = load_arch_container(docs_dir, cid) if cid else ArchContainerInfo()
    if cid and not ac.present:
        errs.append(f"{label} no docs/ARCH__{cid}.yaml found — run /sdlc:arch {cid} first")

    allowed_reqs = (arch.implements.get(cid, set()) if cid else set()) | ac.implements

    covered_reqs: Set[str] = set()
    covered_components: Set[str] = set()
    targeted_fmodes: Set[str] = set()
    targeted_concerns: Set[str] = set()
    targeted_units: Set[str] = set()          # qualified "<component_id>/<unit name>"

    for i, t in enumerate(m.tests or []):
        # component_ref integrity
        if t.component_ref:
            covered_components.add(t.component_ref)
            if ac.present and t.component_ref not in ac.component_ids:
                errs.append(f"{label} tests[{i}].component_ref '{t.component_ref}' is not a component in ARCH__{cid}.yaml")
        if t.tier == TestTier.unit and not t.component_ref:
            errs.append(f"{label} tests[{i}] is unit-tier but has no component_ref")
        # targets_work_unit integrity — the atomic test grain (work_units[].name
        # of the targeted component; names are unique only within a component,
        # so component_ref is required alongside).
        if t.targets_work_unit:
            unit = str(t.targets_work_unit).strip()
            if not t.component_ref:
                errs.append(f"{label} tests[{i}].targets_work_unit '{unit}' set without component_ref — work_unit names only resolve within a component")
            else:
                targeted_units.add(f"{t.component_ref}/{unit}")
                comp_units = ac.comp_units.get(t.component_ref, set())
                if ac.present and comp_units and unit not in comp_units:
                    errs.append(f"{label} tests[{i}].targets_work_unit '{unit}' is not a work_units[].name of component '{t.component_ref}' in ARCH__{cid}.yaml")
        # Legacy pre-1.2 alias: parsed, warned about, never blocks (ARCH no
        # longer emits operations[], so OPN ids resolve against nothing).
        if t.targets_operation:
            warns.append(f"{label} tests[{i}].targets_operation '{t.targets_operation}' is deprecated (OPN family retired) — migrate to targets_work_unit referencing ARCH work_units[].name")
        # covers integrity
        for ref in t.covers or []:
            up = str(ref).upper()
            if not (_FR_RE.match(up) or _NFR_RE.match(up) or _ACR_RE.match(up) or _WKF_RE.match(up)):
                errs.append(f"{label} tests[{i}].covers '{ref}' is not an FR/NFR/ACR/WKF id")
                continue
            if up not in all_ids and (fams["FR"] or fams["NFR"]):
                errs.append(f"{label} tests[{i}].covers '{ref}' does not resolve to a PRD id")
            if (_FR_RE.match(up) or _NFR_RE.match(up)):
                covered_reqs.add(up)
                if ac.present and allowed_reqs and up not in allowed_reqs:
                    errs.append(
                        f"{label} tests[{i}].covers '{ref}' is not in the container's or "
                        f"targeted component's implements_requirements"
                    )
        # risk targets
        if t.targets_failure_mode:
            targeted_fmodes.add(t.targets_failure_mode)
            if ac.present and t.targets_failure_mode not in ac.failure_mode_ids:
                errs.append(f"{label} tests[{i}].targets_failure_mode '{t.targets_failure_mode}' is not a failure_modes id in ARCH__{cid}.yaml")
        if t.targets_security_concern:
            targeted_concerns.add(t.targets_security_concern)
            if ac.present and t.targets_security_concern not in ac.security_concern_ids:
                errs.append(f"{label} tests[{i}].targets_security_concern '{t.targets_security_concern}' is not a security_concerns id in ARCH__{cid}.yaml")

    warnings = m.test_strategy_warnings or []
    deferred_reqs = _req_tokens_in(warnings)
    deferred_components = _deferred_literals(warnings, ac.components_with_acceptance)
    deferred_fmodes = _deferred_literals(warnings, ac.failure_mode_ids)
    deferred_concerns = _deferred_literals(warnings, ac.security_concern_ids)

    # Requirement coverage (trace-or-defer).
    for r in sorted(allowed_reqs):
        if r not in covered_reqs and r not in deferred_reqs:
            errs.append(f"{label} requirement coverage: {r} is implemented by this container but no test covers it and no WRN-NNN defers it")
    # Acceptance coverage (component granularity, trace-or-defer).
    for comp in sorted(ac.components_with_acceptance):
        if comp not in covered_components and comp not in deferred_components:
            errs.append(f"{label} acceptance coverage: component '{comp}' declares acceptance_criteria but no test targets it and no WRN-NNN defers it")
    # Risk coverage (trace-or-defer).
    for fid in sorted(ac.failure_mode_ids):
        if fid not in targeted_fmodes and fid not in deferred_fmodes:
            errs.append(f"{label} risk coverage: failure_mode '{fid}' is not exercised by any test and no WRN-NNN defers it")
    for sid in sorted(ac.security_concern_ids):
        if sid not in targeted_concerns and sid not in deferred_concerns:
            errs.append(f"{label} risk coverage: security_concern '{sid}' is not exercised by any test and no WRN-NNN defers it")
    # Work-unit coverage (ADVISORY — never blocks). A test strategy is risk-driven,
    # so a trivial work unit may legitimately have no dedicated test; we surface the
    # gap rather than force it. No-op when no component declares work_units.
    all_unit_names = {u for units in ac.comp_units.values() for u in units}
    if all_unit_names:
        deferred_units = _deferred_literals(warnings, all_unit_names)
        for comp_id in sorted(ac.comp_units):
            for unit in sorted(ac.comp_units[comp_id]):
                if f"{comp_id}/{unit}" not in targeted_units and unit not in deferred_units:
                    warns.append(f"{label} work-unit coverage: '{comp_id}/{unit}' (ARCH__{cid}) is exercised by no test (targets_work_unit) — add a test or defer via a WRN-NNN")
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


def validate_all(path: Path) -> int:
    docs_dir = path.parent
    # `--path` locates the docs dir. Its filename is the system file unless it
    # names a container file, in which case the system file is the canonical
    # sibling (used so a single renamed fixture can be validated directly).
    if path.name.startswith("TEST-STRATEGY__"):
        system_path = docs_dir / "TEST-STRATEGY.yaml"
    else:
        system_path = path
    container_paths = sorted(
        p for p in docs_dir.glob("TEST-STRATEGY__*.yaml") if p.is_file()
    )

    if not system_path.exists() and not container_paths:
        print(f"ERROR: no TEST-STRATEGY.yaml or TEST-STRATEGY__*.yaml found in {docs_dir}", file=sys.stderr)
        return 2

    fams = load_prd_id_families(docs_dir / "PRD.yaml")
    arch = load_arch(docs_dir / "ARCH.yaml")

    parse_failed = False
    blocking: List[str] = []           # errors that block a 'complete' claim
    warnings: List[str] = []           # always non-blocking
    statuses: List[Tuple[str, Optional[Status]]] = []
    tst_registry: Dict[str, List[str]] = {}   # tst_id -> files declaring it

    def _register_tsts(tests: List[Any], file_name: str) -> None:
        seen_here: Set[str] = set()
        for t in tests or []:
            tid = getattr(t, "tst_id", None)
            if tid and tid not in seen_here:   # in-file dupes are check_tst_ids' job
                seen_here.add(tid)
                tst_registry.setdefault(str(tid), []).append(file_name)

    # ---- system file ----
    if system_path.exists():
        raw = _safe_yaml(system_path)
        if raw is None:
            print(f"ERROR: cannot read/parse {system_path}", file=sys.stderr)
            return 2
        try:
            sysm = TestStrategySystem(**raw)
        except ValidationError as exc:
            print(f"[FAIL] {system_path.name} FAILED schema validation\n")
            for line in _format_errors(exc):
                print(f"  - {line}")
            parse_failed = True
            sysm = None
        if sysm is not None:
            statuses.append((system_path.name, sysm.metadata.status))
            _register_tsts(sysm.tests or [], system_path.name)
            blocking += [f"{system_path.name}: {e}" for e in check_required_system(sysm)]
            blocking += [f"{system_path.name}: {e}" for e in check_tst_ids(sysm.tests or [], system_path.stem)]
            blocking += [f"{system_path.name}: {e}" for e in check_warning_ids(sysm.test_strategy_warnings, system_path.stem)]
            s_errs, s_warns = check_system(sysm, fams, arch, docs_dir)
            blocking += [f"{system_path.name}: {e}" for e in s_errs]
            warnings += [f"{system_path.name}: {w}" for w in s_warns]

    # ---- container files ----
    for cp in container_paths:
        raw = _safe_yaml(cp)
        if raw is None:
            print(f"ERROR: cannot read/parse {cp}", file=sys.stderr)
            return 2
        try:
            cm = TestStrategyContainer(**raw)
        except ValidationError as exc:
            print(f"[FAIL] {cp.name} FAILED schema validation\n")
            for line in _format_errors(exc):
                print(f"  - {line}")
            parse_failed = True
            continue
        statuses.append((cp.name, cm.metadata.status))
        _register_tsts(cm.tests or [], cp.name)
        blocking += [f"{cp.name}: {e}" for e in check_required_container(cm)]
        blocking += [f"{cp.name}: {e}" for e in check_tst_ids(cm.tests or [], cp.stem)]
        blocking += [f"{cp.name}: {e}" for e in check_warning_ids(cm.test_strategy_warnings, cp.stem)]
        c_errs, c_warns = check_container(cm, fams, arch, docs_dir)
        blocking += [f"{cp.name}: {e}" for e in c_errs]
        warnings += [f"{cp.name}: {w}" for w in c_warns]

    if parse_failed:
        return 1

    # Global TST uniqueness across the system file + every container file.
    # TST-NNN is ONE continuous id space: downstream Task.test_refs assumes a
    # single namespace, so a per-file restart at TST-001 silently collides.
    for tid in sorted(tst_registry):
        files = tst_registry[tid]
        if len(files) > 1:
            blocking.append(
                f"tst_id '{tid}' is declared in {len(files)} files "
                f"({', '.join(files)}) — TST ids are globally unique across the "
                f"system file and all container files (one continuous counter); "
                f"renumber the later file(s)"
            )

    # Upstream-status awareness (non-blocking).
    for up in ("PRD.yaml", "DATA-MODEL.yaml", "ARCH.yaml"):
        raw = _safe_yaml(docs_dir / up)
        if raw is not None:
            st = (raw.get("metadata") or {}).get("status")
            if st and st != "complete":
                warnings.append(f"upstream {up} has metadata.status='{st}' (expected 'complete')")

    any_complete = any(st == Status.complete for _, st in statuses)

    # A 'complete' file with blocking errors fails; otherwise OK.
    if any_complete and blocking:
        print("[FAIL] a test-strategy file claims status 'complete' but has errors:\n")
        for b in blocking:
            print(f"  - {b}")
        if warnings:
            print(f"\nWARNINGS ({len(warnings)}):")
            for w in warnings:
                print(f"  - {w}")
        return 1

    files = ", ".join(name for name, _ in statuses) or "(none)"
    if any_complete:
        print(f"[OK] test strategy is valid and complete ({files}).")
    else:
        if blocking:
            print(f"[OK] test strategy is a valid DRAFT ({files}); {len(blocking)} item(s) to resolve before 'complete':\n")
            for b in blocking:
                print(f"  - {b}")
        else:
            print(f"[OK] test strategy is a valid DRAFT ({files}).")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate TEST-STRATEGY.yaml + every TEST-STRATEGY__*.yaml against the sdlc-test schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "TEST-STRATEGY.yaml"),
        help="Path that locates the docs dir (default: ./docs/TEST-STRATEGY.yaml). "
        "The system file + all sibling TEST-STRATEGY__*.yaml are validated together.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
