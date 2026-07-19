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
       Meta-corpus dialect (system strategy sets `meta_corpus_dialect: true`):
       per-container shards may prefix ids as TST-<PREFIX>-NNN (a short
       container tag) so independently authored shards share no namespace;
       global uniqueness still keys on the full id. A generated app keeps flat
       TST-NNN.
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
    7. Test->subject seam (v2.0, SK-06): every unit-tier container test names
       its subject work unit(s) in targets_work_units (plural; the legacy
       singular targets_work_unit is parsed as an alias) OR is deferred via a
       WRN-NNN naming its tst_id. BLOCKING at
       test_strategy_container_version >= 2.0; below 2.0 a warning; SILENT in
       the meta-corpus dialect (its coverage mechanism is covers-intersection
       and check 11's work-unit-coverage advisory already carries the
       unexercised-unit signal). The seam is what lets the task skill wire
       each test task's depends_on to the impl task(s) it exercises.
    8. Non-gating flag (v2.0, SK-07; warn-level): a test with gating: false is
       excluded from the default suite via a pytest marker
       (non_gating_marker, default 'eval_nongating'); warn when its directives
       never mention the marker, and warn when a unit-tier test is non-gating
       (evals are usually e2e/llm-judge).
    9. Shared test infrastructure (v2.0, SK-08; warn-level): when
       mock_policy/fixture_strategy prose names mocks/stubs/fixtures/factories
       but shared_infrastructure declares no deliverable, warn — downstream
       codegen workers will each reinvent the helper. shared_infrastructure
       item shape (path, purpose, realizes) is format-checked when present.

    D2 (2026-07-16, pipeline-wide): the per-test `priority` field is RETIRED.
    It is no longer required at status: complete; old artifacts carrying it
    still parse (accepted-and-ignored).

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
    """DEPRECATED (D2, 2026-07-16): the priority paradigm is retired
    pipeline-wide. Kept so old artifacts carrying `priority` still parse;
    no check reads it."""

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
    priority: Optional[Priority] = None          # DEPRECATED (D2) — accepted, ignored
    gating: Optional[bool] = None                # None/true = gating; false = excluded
                                                 #   from the default suite (SK-07)
    non_gating_marker: Optional[str] = None      # pytest marker for gating: false
                                                 #   (default 'eval_nongating')
    setup: Optional[str] = None
    acceptance: Optional[str] = None
    status: Optional[TestStatus] = None


class ContainerStrategyRef(BaseModel):
    container_id: Optional[str] = None
    file_path: Optional[str] = None


class SharedInfraItem(BaseModel):
    """One shared test deliverable the mock/fixture/data policy implies
    (SK-08) — e.g. tests/conftest.py, a factory module, a fake-LLM helper.
    The task skill turns the list into ONE test-infrastructure task per
    container; codegen workers import instead of reinventing."""

    path: Optional[str] = None            # REQUIRED when present — repo-relative
    purpose: Optional[str] = None         # REQUIRED when present — what it provides
    realizes: Optional[List[str]] = None  # REQUIRED when present — >=1 of
                                          #   mock_policy | fixture_strategy |
                                          #   test_data_strategy
    contents_hint: Optional[str] = None   # OPTIONAL — for the codegen worker


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
    shared_infrastructure: Optional[List[SharedInfraItem]] = None  # v2.0 (SK-08)
    test_file_convention: Optional[str] = None  # v2.0 (SK-09) — path template the
                                                #   task skill derives test-task
                                                #   target_files from; default
                                                #   tests/<container>/<component_snake>/
                                                #   test_<tst_id_snake>.py
    ci_integration: Optional[str] = None
    environments: Optional[List[Environment]] = None
    tests: Optional[List[SystemTest]] = None
    container_strategies: Optional[List[ContainerStrategyRef]] = None
    # Meta-corpus dialect opt-in (OPTIONAL). True flips the strategy into the
    # sharded/no-API-layer meta-corpus mode: container-namespaced TST ids
    # (TST-<PREFIX>-NNN) and the covers-based coverage mechanism. A generated
    # app OMITS this (or sets false) and keeps the strict stock behavior.
    meta_corpus_dialect: Optional[bool] = None
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
    targets_work_units: Optional[List[str]] = None  # v2.0 — the subject seam: the
                                              # work_units[].name entries (of
                                              # component_ref) this test exercises.
                                              # Multi-subject is real (a gate test
                                              # verifying exit + entry adequacy).
    targets_work_unit: Optional[str] = None   # LEGACY singular alias (pre-2.0) —
                                              # parsed and validated; warns at >= 2.0
    targets_operation: Optional[str] = None   # DEPRECATED pre-1.2 alias (OPN-NNN of the
                                              # retired ARCH operations[] family); parsed
                                              # for backward compat, warns, never blocks
    directives: Optional[List[str]] = None
    covers: Optional[List[str]] = None
    targets_failure_mode: Optional[str] = None
    targets_security_concern: Optional[str] = None
    priority: Optional[Priority] = None       # DEPRECATED (D2) — accepted, ignored
    gating: Optional[bool] = None             # None/true = gating; false = excluded
                                              #   from the default suite (SK-07)
    non_gating_marker: Optional[str] = None   # pytest marker for gating: false
                                              #   (default 'eval_nongating')
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
    shared_infrastructure: Optional[List[SharedInfraItem]] = None  # v2.0 override —
                                                #   null => inherit the system list
    test_file_convention: Optional[str] = None  # v2.0 override — null => inherit
    test_environment: Optional[str] = None
    tests: Optional[List[ContainerTest]] = None
    test_strategy_warnings: Optional[List[str]] = None


# =============================================================================
# Regexes + small helpers
# =============================================================================

_TST_RE = re.compile(r"^TST-\d{3,}$")
# Meta-corpus dialect: a per-container strategy shard prefixes its TST ids with
# a short uppercase container tag (TST-CLI-001, TST-SBX-014) so independently
# authored shards share no id namespace. Accepted ONLY when the system strategy
# opts in via `meta_corpus_dialect: true`; a generated app keeps flat TST-NNN.
_TST_SHARDED_RE = re.compile(r"^TST-(?:[A-Z][A-Z0-9]*-)?\d{3,}$")
_WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
_FR_RE = re.compile(r"^FR-\d+$", re.IGNORECASE)
_NFR_RE = re.compile(r"^NFR-\d+$", re.IGNORECASE)
_ACR_RE = re.compile(r"^ACR-\d+$", re.IGNORECASE)
_WKF_RE = re.compile(r"^WKF-\d+$", re.IGNORECASE)

_REQ_TOKEN_RE = re.compile(r"\b(?:FR|NFR|ACR|WKF)-\d+\b", re.IGNORECASE)

# SK-08 emptiness advisory: prose that names shared deliverables.
_MOCK_PROSE_RE = re.compile(r"\b(mock|stub|fake)", re.IGNORECASE)
_FIXTURE_PROSE_RE = re.compile(r"\b(fixture|factor)", re.IGNORECASE)
_SHARED_INFRA_REALIZES = {"mock_policy", "fixture_strategy", "test_data_strategy"}
DEFAULT_NON_GATING_MARKER = "eval_nongating"

# The test->subject seam (check 12) BLOCKS only at container artifact
# version >= this floor AND meta_corpus_dialect false; otherwise it warns.
# 2.0 deliberately clears the AICF corpus's self-stamped 1.9 (see the
# SKILLS-PLANS-OVERVIEW convention-3 amendment): a version gate the corpus
# has already walked past protects nothing.
SUBJECT_SEAM_MIN_VERSION = (2, 0)


def _version_tuple(v: Optional[str]) -> Tuple[int, int]:
    """Parse 'MAJOR.MINOR[...]' leniently; unparseable -> (0, 0)."""
    try:
        parts = str(v).strip().split(".")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, AttributeError, IndexError):
        return (0, 0)

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
        self.comp_implements: Dict[str, Set[str]] = {}    # component_id -> {FR/NFR it implements}
                                                          # (meta-corpus covers-intersection)
        self.fmode_component: Dict[str, str] = {}         # failure_mode id -> owning component_id
                                                          # (container-level fmodes are absent here)


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
        comp_reqs = _req_tokens_in(comp.get("implements_requirements") or [])
        if coid:
            info.component_ids.add(coid)
            if comp.get("acceptance_criteria"):
                info.components_with_acceptance.add(coid)
            units: Set[str] = set()
            for wu in comp.get("work_units") or []:
                if isinstance(wu, dict) and wu.get("name"):
                    units.add(str(wu["name"]).strip())
            info.comp_units[coid] = units
            info.comp_implements[coid] = comp_reqs
            for fid in _collect_struct_ids(comp.get("failure_modes"), "id"):
                info.fmode_component[fid] = coid
        info.implements |= comp_reqs
        info.failure_mode_ids |= _collect_struct_ids(comp.get("failure_modes"), "id")
    return info


# =============================================================================
# Field-level format / required checks
# =============================================================================


def check_shared_infrastructure(items: Optional[List[SharedInfraItem]], label: str) -> List[str]:
    """Format-check shared_infrastructure items (blocking — the field is new, so
    this only ever fires on artifacts that opted into it)."""
    errs: List[str] = []
    for i, it in enumerate(items or []):
        if not it.path:
            errs.append(f"{label}.shared_infrastructure[{i}].path is required")
        if not it.purpose:
            errs.append(f"{label}.shared_infrastructure[{i}].purpose is required")
        rz = it.realizes or []
        if not rz:
            errs.append(
                f"{label}.shared_infrastructure[{i}].realizes must name >=1 of "
                f"{sorted(_SHARED_INFRA_REALIZES)}"
            )
        else:
            for r in rz:
                if r not in _SHARED_INFRA_REALIZES:
                    errs.append(
                        f"{label}.shared_infrastructure[{i}].realizes '{r}' is not one of "
                        f"{sorted(_SHARED_INFRA_REALIZES)}"
                    )
    return errs


def _infra_emptiness_warns(
    mock_policy: Optional[str],
    fixture_strategy: Optional[str],
    has_infra: bool,
    label: str,
) -> List[str]:
    """SK-08 advisory: policy prose names shared deliverables but
    shared_infrastructure declares none — every codegen worker will reinvent
    the helper (the F22 lesson: the corpus hand-authored TSK-414 for this)."""
    if has_infra:
        return []
    hits = []
    if mock_policy and _MOCK_PROSE_RE.search(mock_policy):
        hits.append("mock_policy")
    if fixture_strategy and _FIXTURE_PROSE_RE.search(fixture_strategy):
        hits.append("fixture_strategy")
    if not hits:
        return []
    prefix = f"{label} " if label else ""
    return [
        f"{prefix}{'/'.join(hits)} names shared test deliverables (mocks/stubs/"
        f"fixtures/factories) but shared_infrastructure lists none - a policy "
        f"with no named deliverable means downstream workers each reinvent it; "
        f"declare the conftest/factory/helper files (or inherit them)"
    ]


def _gating_warns(t: Any, i: int, label: str) -> List[str]:
    """SK-07 advisories for a gating: false test."""
    if t.gating is not False:
        return []
    warns: List[str] = []
    where = (f"{label} " if label else "") + f"tests[{i}] ({t.tst_id})"
    marker = (t.non_gating_marker or DEFAULT_NON_GATING_MARKER).strip()
    if t.tier == TestTier.unit:
        warns.append(
            f"{where} is unit-tier but gating: false - non-gating tests are "
            f"usually e2e/llm-judge evals; confirm the tier"
        )
    if not any(marker in d for d in (t.directives or []) if isinstance(d, str)):
        warns.append(
            f"{where} is gating: false but no directive mentions the exclusion "
            f"marker '{marker}' - the codegen worker needs an apply-the-marker "
            f"directive to keep it out of the default suite"
        )
    return warns


def check_warning_ids(warnings: Optional[List[str]], label: str) -> List[str]:
    errs: List[str] = []
    for i, w in enumerate(warnings or []):
        if not isinstance(w, str) or not _WRN_RE.match(w.strip()):
            errs.append(f"{label}.test_strategy_warnings[{i}]: '{w}' must match 'WRN-NNN: <message>'")
    return errs


def check_tst_ids(tests: List[Any], label: str, meta_mode: bool = False) -> List[str]:
    errs: List[str] = []
    seen: Set[str] = set()
    rx = _TST_SHARDED_RE if meta_mode else _TST_RE
    expected = "TST-<PREFIX>-NNN" if meta_mode else "TST-NNN"
    for i, t in enumerate(tests or []):
        tid = getattr(t, "tst_id", None)
        if not tid:
            continue  # required-ness handled by check_required
        if not rx.match(str(tid)):
            errs.append(f"{label}.tests[{i}].tst_id '{tid}' must match '{expected}'")
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
        # D2: "priority" removed from the required tuple (retired field).
        for fld in ("tst_id", "name", "tier", "description", "acceptance", "status"):
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
        # D2: "priority" removed from the required tuple (retired field).
        for fld in ("tst_id", "name", "tier", "description", "acceptance", "status"):
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
        warns += _gating_warns(t, i, "")

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

    # shared_infrastructure format (blocking when used) + SK-08 emptiness
    # advisory (only at complete — a draft may not have decided yet).
    errs += check_shared_infrastructure(m.shared_infrastructure, "")
    if m.metadata.status == Status.complete:
        warns += _infra_emptiness_warns(
            m.mock_policy, m.fixture_strategy, bool(m.shared_infrastructure), ""
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
    meta_mode: bool = False,
    sys_has_infra: bool = False,
) -> Tuple[List[str], List[str]]:
    """Return (blocking_errors, non_blocking_warnings) for one container file.

    `meta_mode` (the system strategy's `meta_corpus_dialect: true`) turns on the
    covers-based coverage mechanism: a component is targeted when a test's
    `covers` FRs intersect its `implements_requirements` (not only when
    `component_ref` names it); covered NFRs resolve against the PRD NFR
    catalogue rather than a component's FR-only `implements_requirements`; and a
    failure_mode is exercised when its owning component is covers-targeted (or
    via `targets_failure_mode`, or a WRN-NNN deferral). Off for a generated app.
    """
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
    version = _version_tuple(m.metadata.test_strategy_container_version)
    # Check 12 (SK-06): unit-tier tests whose subject seam is unpinned.
    subjectless_unit_tests: List[Tuple[int, str]] = []   # (index, tst_id)

    for i, t in enumerate(m.tests or []):
        # component_ref integrity
        if t.component_ref:
            covered_components.add(t.component_ref)
            if ac.present and t.component_ref not in ac.component_ids:
                errs.append(f"{label} tests[{i}].component_ref '{t.component_ref}' is not a component in ARCH__{cid}.yaml")
        if t.tier == TestTier.unit and not t.component_ref:
            errs.append(f"{label} tests[{i}] is unit-tier but has no component_ref")
        # targets_work_units integrity — the atomic test grain (work_units[].name
        # entries of the targeted component; names are unique only within a
        # component, so component_ref is required alongside). The legacy
        # singular targets_work_unit is folded in as an alias (warns at >= 2.0).
        subjects: List[str] = []
        for u in t.targets_work_units or []:
            u = str(u).strip()
            if u and u not in subjects:
                subjects.append(u)
        if t.targets_work_unit:
            legacy = str(t.targets_work_unit).strip()
            if legacy and legacy not in subjects:
                subjects.append(legacy)
            if version >= SUBJECT_SEAM_MIN_VERSION:
                warns.append(f"{label} tests[{i}].targets_work_unit is the legacy singular alias - migrate to targets_work_units: [...] at version >= 2.0")
        for unit in subjects:
            if not t.component_ref:
                errs.append(f"{label} tests[{i}].targets_work_units '{unit}' set without component_ref — work_unit names only resolve within a component")
            else:
                targeted_units.add(f"{t.component_ref}/{unit}")
                comp_units = ac.comp_units.get(t.component_ref, set())
                if ac.present and comp_units and unit not in comp_units:
                    errs.append(f"{label} tests[{i}].targets_work_units '{unit}' is not a work_units[].name of component '{t.component_ref}' in ARCH__{cid}.yaml")
        if t.tier == TestTier.unit and not subjects and t.tst_id:
            subjectless_unit_tests.append((i, str(t.tst_id)))
        warns += _gating_warns(t, i, label)
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
                    # Meta-corpus: NFRs resolve against the PRD NFR catalogue
                    # (already validated via all_ids above), not a component's
                    # implements_requirements — which by house style lists only
                    # FRs. FRs still must map to implements_requirements.
                    if meta_mode and _NFR_RE.match(up):
                        pass
                    else:
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

    # Meta-corpus covers-based targeting (Part 4a): a component is "targeted"
    # when a test covers a requirement it implements — not only when
    # `component_ref` names it. Monotonic (adds coverage, never removes); gated
    # on meta_mode so a generated app keeps the explicit component_ref rule.
    if meta_mode:
        for comp_id, reqs in ac.comp_implements.items():
            if reqs & covered_reqs:
                covered_components.add(comp_id)

    warnings = m.test_strategy_warnings or []
    deferred_reqs = _req_tokens_in(warnings)
    deferred_components = _deferred_literals(warnings, ac.components_with_acceptance)
    deferred_fmodes = _deferred_literals(warnings, ac.failure_mode_ids)
    deferred_concerns = _deferred_literals(warnings, ac.security_concern_ids)

    # Check 12 (SK-06) — the test->subject seam is require-or-defer: at
    # status: complete every unit-tier test names targets_work_units OR a
    # WRN-NNN defers it by tst_id. BLOCKING at container version >= 2.0
    # (the floor deliberately clears the corpus's self-stamped 1.9 — see
    # SUBJECT_SEAM_MIN_VERSION); below 2.0 it warns. In the meta-corpus
    # dialect it is SILENT: the dialect's coverage mechanism is
    # covers-intersection, and the per-unit work-unit-coverage advisory
    # (check 11) already surfaces the unexercised-unit signal from the ARCH
    # side — a second, per-test warning family would restate it N times.
    # Without the seam the task skill cannot derive a test task's depends_on —
    # the corpus's 191-test absorber rewire (PLAN4) is what this prevents.
    if subjectless_unit_tests and m.metadata.status == Status.complete and not meta_mode:
        deferred_tsts = _deferred_literals(
            warnings, {tid for _, tid in subjectless_unit_tests}
        )
        seam_blocks = version >= SUBJECT_SEAM_MIN_VERSION
        for i, tid in subjectless_unit_tests:
            if tid in deferred_tsts:
                continue
            msg = (
                f"{label} tests[{i}] ({tid}) is unit-tier but names no "
                f"targets_work_units and no WRN-NNN defers it - the "
                f"test->subject seam is unpinned (the task skill cannot wire "
                f"this test's depends_on to the impl task it exercises)"
            )
            if seam_blocks:
                errs.append(msg)
            else:
                warns.append(msg)

    # shared_infrastructure (v2.0): format when used (blocking) + SK-08
    # emptiness advisory — only against the container's OWN policy overrides
    # (null inherits the system policy, which the system-file check covers).
    errs += check_shared_infrastructure(m.shared_infrastructure, label)
    if m.metadata.status == Status.complete and not sys_has_infra:
        warns += _infra_emptiness_warns(
            m.mock_policy, m.fixture_strategy, bool(m.shared_infrastructure), label
        )

    # Requirement coverage (trace-or-defer).
    for r in sorted(allowed_reqs):
        if r not in covered_reqs and r not in deferred_reqs:
            errs.append(f"{label} requirement coverage: {r} is implemented by this container but no test covers it and no WRN-NNN defers it")
    # Acceptance coverage (component granularity, trace-or-defer). In meta_mode
    # `covered_components` also counts covers-targeted components (Part 4a/c).
    for comp in sorted(ac.components_with_acceptance):
        if comp not in covered_components and comp not in deferred_components:
            errs.append(f"{label} acceptance coverage: component '{comp}' declares acceptance_criteria but no test targets it and no WRN-NNN defers it")
    # Risk coverage (trace-or-defer). Part 4c: in meta_mode a failure_mode is
    # also exercised when its owning component is covers-targeted.
    for fid in sorted(ac.failure_mode_ids):
        covered_by_component = meta_mode and ac.fmode_component.get(fid) in covered_components
        if fid not in targeted_fmodes and not covered_by_component and fid not in deferred_fmodes:
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
    meta_mode = False                  # system strategy's meta_corpus_dialect flag
    sys_has_infra = False              # system strategy declares shared_infrastructure

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
            meta_mode = bool(sysm.meta_corpus_dialect)
            sys_has_infra = bool(sysm.shared_infrastructure)
            statuses.append((system_path.name, sysm.metadata.status))
            _register_tsts(sysm.tests or [], system_path.name)
            blocking += [f"{system_path.name}: {e}" for e in check_required_system(sysm)]
            blocking += [f"{system_path.name}: {e}" for e in check_tst_ids(sysm.tests or [], system_path.stem, meta_mode)]
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
        blocking += [f"{cp.name}: {e}" for e in check_tst_ids(cm.tests or [], cp.stem, meta_mode)]
        blocking += [f"{cp.name}: {e}" for e in check_warning_ids(cm.test_strategy_warnings, cp.stem)]
        c_errs, c_warns = check_container(cm, fams, arch, docs_dir, meta_mode, sys_has_infra)
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
