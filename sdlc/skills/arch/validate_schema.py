"""Validate ARCH.yaml + every ARCH__*.yaml against the sdlc-arch schemas,
and run the cross-check suite (coverage, edge integrity, container/system
consistency, upstream traceability).

Run from the project root:

    python sdlc/skills/arch/validate_schema.py
    python sdlc/skills/arch/validate_schema.py --path docs/ARCH.yaml
    python sdlc/skills/arch/validate_schema.py --docs-dir other/docs

Validates:
    1. docs/ARCH.yaml (or --path) — system architecture.
    2. Every docs/ARCH__*.yaml sibling — one per container.
    3. Required-field checks (status: complete gate).
    4. ID-prefix formats (cross-skill conventions):
       - WRN-NNN on every arch_warnings entry (system + each container).
       - FR-NNN on every implements_requirements entry (containers +
         components) and on non_container_features.
       - WKF-NNN on every traces_prd_workflows entry (containers +
         components).
    5. Coverage cross-checks (block status: complete):
       - API-resource coverage: every API__*.yaml resource_id appears
         in some container's owns_api_resources.
       - UX-surface coverage: every UX__*.yaml data-bearing surface_id
         appears in some container's owns_ux_surfaces.
       - DATA-store coverage: every store id in
         DATA-MODEL.yaml.persistence.* appears in some container's
         persistence.
       - PRD feature coverage: every PRD must_have_features FR-NNN
         appears in some container's implements_requirements OR in
         ARCH.yaml.non_container_features. Skipped if PRD.yaml absent.
    6. Edge + trace integrity (block status: complete):
       - Edge endpoint integrity: every edge's `from` / `to` is a valid
         container_id (system level) or component_id (container level),
         and external_edges' `to` resolves against the on-disk graph.
       - Edge via_* resolution against API / DATA upstreams.
       - Component traces (api/ux/data/operations) resolve upstream and
         sit within the parent container's owns_*.
       - implements_requirements / traces_prd_workflows resolve to PRD
         FR-NNN / WKF-NNN ids; component features ⊆ parent container's.

Exit codes:
    0 — schema valid; status='complete' (with all checks passing) or
        status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but
        required fields are missing, OR status='complete' but any
        cross-check failed.
    2 — could not read or parse one of the files (missing, bad YAML).
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

try:
    import yaml
except ImportError:
    print(
        "ERROR: pyyaml is required.\nInstall with:  pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(3)

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
except ImportError:
    print(
        "ERROR: pydantic v2 is required.\nInstall with:  pip install 'pydantic>=2'",
        file=sys.stderr,
    )
    sys.exit(3)


# =============================================================================
# Enums — kept in lockstep with ARCH.schema.yaml and ARCH__CONTAINER.schema.yaml
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class ArchPattern(str, Enum):
    monolith = "monolith"
    modular_monolith = "modular_monolith"
    microservices = "microservices"
    event_driven = "event_driven"
    hexagonal = "hexagonal"
    serverless = "serverless"
    plugin = "plugin"
    pipeline = "pipeline"
    other = "other"


class IdentityProvider(str, Enum):
    internal = "internal"
    external_oidc = "external_oidc"
    external_saml = "external_saml"
    external_proprietary = "external_proprietary"
    none = "none"


class TokenStrategy(str, Enum):
    jwt = "jwt"
    session = "session"
    api_key = "api_key"
    mtls = "mtls"
    opaque_token = "opaque_token"
    none = "none"


class ContainerArchetype(str, Enum):
    backend_api = "backend-api"
    web_frontend = "web-frontend"
    mobile_frontend = "mobile-frontend"
    desktop_frontend = "desktop-frontend"
    cli = "cli"
    worker = "worker"
    scheduler = "scheduler"
    stream_processor = "stream-processor"
    gateway = "gateway"
    bff = "bff"
    edge_function = "edge-function"
    static_site = "static-site"
    identity_provider = "identity-provider"
    primary_database = "primary-database"
    secondary_database = "secondary-database"
    cache = "cache"
    blob_store = "blob-store"
    search_index = "search-index"
    message_bus = "message-bus"
    etl_pipeline = "etl-pipeline"
    ml_inference = "ml-inference"
    external_service = "external-service"
    other = "other"


class DeploymentUnit(str, Enum):
    long_running_service = "long_running_service"
    scheduled_job = "scheduled_job"
    batch_job = "batch_job"
    static_asset = "static_asset"
    serverless_function = "serverless_function"
    container = "container"
    external_managed = "external_managed"


class DeploymentShape(str, Enum):
    container = "container"
    serverless_function = "serverless_function"
    static_asset = "static_asset"
    managed_service = "managed_service"
    long_running_service = "long_running_service"
    scheduled_job = "scheduled_job"
    batch_job = "batch_job"
    desktop_app = "desktop_app"
    mobile_app = "mobile_app"
    cli_binary = "cli_binary"


class ContainerStatus(str, Enum):
    defined = "defined"
    draft = "draft"
    confirmed = "confirmed"


class EdgeType(str, Enum):
    depends_on = "depends_on"
    calls = "calls"
    reads = "reads"
    writes = "writes"
    publishes = "publishes"
    subscribes_to = "subscribes_to"
    implements = "implements"


class ComponentArchetype(str, Enum):
    """Component archetypes — kept in lockstep with component-taxonomy.yaml
    and arch-questions.yaml component_inventory.archetype suggested_answers.
    """

    controller = "controller"
    service = "service"
    repository = "repository"
    middleware = "middleware"
    use_case = "use_case"
    view = "view"
    state_store = "state_store"
    api_client = "api_client"
    event_handler = "event_handler"
    scheduler = "scheduler"
    validator = "validator"
    serializer = "serializer"
    cache_client = "cache_client"
    blob_client = "blob_client"
    background_worker = "background_worker"
    config_loader = "config_loader"
    observability_bootstrap = "observability_bootstrap"
    error_handler = "error_handler"
    other = "other"


class PersistenceAccess(str, Enum):
    read = "read"
    write = "write"
    read_write = "read_write"


# Surface types treated as "data-bearing" for surface-coverage purposes.
# Mirrors the same set used by sdlc-api.
DATA_BEARING_SURFACE_TYPES = {
    "screen",
    "page",
    "tab",
    "modal",
    "dialog",
    "drawer",
    "panel",
    "cli_command",
    "flow_step",
    "other",
}


# =============================================================================
# Pydantic models — ARCH.yaml
# =============================================================================

_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _Base(BaseModel):
    model_config = _BASE_CONFIG


class ArchMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    arch_version: str
    last_updated: str
    generated_by: str = "sdlc-arch"
    session_id: str
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None


class ArchitecturePattern(_Base):
    pattern: Optional[ArchPattern] = None
    pattern_confidence: Optional[Confidence] = None
    rationale: Optional[str] = None
    tradeoff_notes: Optional[str] = None
    ai_builder_notes: Optional[str] = None


class IdentityAndAuth(_Base):
    identity_provider: Optional[IdentityProvider] = None
    identity_provider_confidence: Optional[Confidence] = None
    token_strategy: Optional[TokenStrategy] = None
    token_strategy_confidence: Optional[Confidence] = None
    identity_container: Optional[str] = None
    rationale: Optional[str] = None


class ContainerOwnership(_Base):
    team: Optional[str] = None
    change_cadence: Optional[str] = None


class Container(_Base):
    container_id: str
    archetype: Optional[ContainerArchetype] = None
    purpose: Optional[str] = None
    owns_api_resources: Optional[List[str]] = None
    owns_ux_surfaces: Optional[List[str]] = None
    persistence: Optional[List[str]] = None
    implements_requirements: Optional[List[str]] = None  # FR-NNN
    traces_prd_workflows: Optional[List[str]] = None      # WKF-NNN
    deployment_unit: Optional[DeploymentUnit] = None
    ownership: Optional[ContainerOwnership] = None
    external: bool = False
    status: Optional[ContainerStatus] = None
    file_path: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    notes: Optional[str] = None


class Edge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    type: Optional[EdgeType] = None
    via_resource_id: Optional[str] = None
    via_channel_id: Optional[str] = None
    via_entity: Optional[str] = None
    note: Optional[str] = None


class Arch(BaseModel):
    """Top-level docs/ARCH.yaml."""

    model_config = ConfigDict(extra="allow")

    metadata: ArchMetadata
    architecture_pattern: Optional[ArchitecturePattern] = None
    identity_and_auth: Optional[IdentityAndAuth] = None
    containers: Optional[List[Container]] = None
    edges: Optional[List[Edge]] = None
    non_container_features: Optional[List[str]] = None  # FR-NNN opt-out
    arch_warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_container_ids(self) -> "Arch":
        if self.containers:
            ids = [c.container_id for c in self.containers]
            dupes = {x for x in ids if ids.count(x) > 1}
            if dupes:
                raise ValueError(
                    f"duplicate container_id(s) in containers[]: {sorted(dupes)}"
                )
        return self


# =============================================================================
# Pydantic models — ARCH__<container>.yaml
# =============================================================================


class ContainerArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    arch_container_version: str
    last_updated: str
    generated_by: str = "sdlc-arch"
    session_id: str
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None


class TechStack(_Base):
    language: Optional[str] = None
    language_confidence: Optional[Confidence] = None
    framework: Optional[str] = None
    runtime_version: Optional[str] = None
    package_manager: Optional[str] = None
    build_tool: Optional[str] = None
    key_libraries: Optional[List[str]] = None


class PersistenceBinding(_Base):
    store_id: str
    access: Optional[PersistenceAccess] = None
    via: Optional[str] = None
    note: Optional[str] = None


class APISurfaceItem(_Base):
    resource_id: str
    note: Optional[str] = None


class APIConsumerItem(_Base):
    resource_id: str
    in_same_container: bool = False


class UXSurfaceItem(_Base):
    surface_id: str
    note: Optional[str] = None


class Scaling(_Base):
    min_replicas: Optional[int] = None
    max_replicas: Optional[int] = None
    autoscale_signal: Optional[str] = None


class Deployment(_Base):
    shape: Optional[DeploymentShape] = None
    shape_confidence: Optional[Confidence] = None
    hosting: Optional[str] = None
    scaling: Optional[Scaling] = None
    regions: Optional[List[str]] = None
    scheduling: Optional[str] = None
    notes: Optional[str] = None


class Alert(_Base):
    condition: str
    action: str


class Observability(_Base):
    logs: Optional[str] = None
    metrics: Optional[str] = None
    traces: Optional[str] = None
    alerts: Optional[List[Alert]] = None


class Ownership(_Base):
    team: Optional[str] = None
    change_cadence: Optional[str] = None
    on_call_rotation: Optional[str] = None


class FailureMode(_Base):
    id: Optional[str] = None
    description: Optional[str] = None
    likelihood: Optional[Literal["low", "medium", "high"]] = None
    impact: Optional[Literal["low", "medium", "high"]] = None
    mitigation: Optional[str] = None


# Component-level failure modes accept either a structured FailureMode dict
# or a bare string (backwards-compat with v1.0 free-text form).
ComponentFailureMode = Union[FailureMode, str]


class SecurityConcern(_Base):
    """Container-level security concern — structured form.

    Backwards-compat: a bare string is also accepted (the v1.0 shape).
    """

    id: Optional[str] = None
    threat: Optional[str] = None
    mitigation: Optional[str] = None
    related_data_classification: Optional[List[str]] = None


# Backwards-compat: security_concerns may be list of structured dicts OR strings.
ContainerSecurityConcern = Union[SecurityConcern, str]


class Component(_Base):
    component_id: str
    archetype: Optional[ComponentArchetype] = None
    purpose: Optional[str] = None
    responsibilities: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    traces_api_resources: Optional[List[str]] = None
    traces_api_operations: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    traces_data_entities: Optional[List[str]] = None
    implements_requirements: Optional[List[str]] = None  # FR-NNN
    traces_prd_workflows: Optional[List[str]] = None      # WKF-NNN
    failure_modes: Optional[List[ComponentFailureMode]] = None
    acceptance_criteria: Optional[List[str]] = None
    status: Optional[ContainerStatus] = None


class InternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    type: Optional[EdgeType] = None
    via_resource_id: Optional[str] = None
    via_operation_id: Optional[str] = None
    via_entity: Optional[str] = None
    note: Optional[str] = None


class ExternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None  # "<container_id>" or "<container_id>/<component_id>"
    type: Optional[EdgeType] = None
    via_resource_id: Optional[str] = None
    via_operation_id: Optional[str] = None
    via_channel_id: Optional[str] = None
    via_entity: Optional[str] = None
    note: Optional[str] = None


class ArchContainer(BaseModel):
    """Top-level docs/ARCH__<container>.yaml."""

    model_config = ConfigDict(extra="allow")

    metadata: ContainerArtifactMetadata
    container_id: str
    archetype: Optional[ContainerArchetype] = None
    overview: Optional[str] = None
    tech_stack: Optional[TechStack] = None
    persistence_bindings: Optional[List[PersistenceBinding]] = None
    api_surface: Optional[List[APISurfaceItem]] = None
    api_consumers: Optional[List[APIConsumerItem]] = None
    ux_surface: Optional[List[UXSurfaceItem]] = None
    deployment: Optional[Deployment] = None
    observability: Optional[Observability] = None
    ownership: Optional[Ownership] = None
    failure_modes: Optional[List[FailureMode]] = None
    security_concerns: Optional[List[ContainerSecurityConcern]] = None
    components: Optional[List[Component]] = None
    internal_edges: Optional[List[InternalEdge]] = None
    external_edges: Optional[List[ExternalEdge]] = None
    arch_warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_component_ids(self) -> "ArchContainer":
        if self.components:
            ids = [c.component_id for c in self.components]
            dupes = {x for x in ids if ids.count(x) > 1}
            if dupes:
                raise ValueError(
                    f"duplicate component_id(s) in components[]: {sorted(dupes)}"
                )
        return self


# =============================================================================
# Required-field checks
# =============================================================================

# Top-level required scalars + composite blocks. Note `edges` is intentionally
# absent — an empty `edges: []` is legitimate for trivial single-container
# systems with no persistence. We instead require the *key* to be present
# (None means "not authored yet" and forces draft).
ARCH_REQUIRED_PATHS: List[str] = [
    "architecture_pattern.pattern",
    "architecture_pattern.rationale",
    "identity_and_auth.identity_provider",
    "identity_and_auth.token_strategy",
    "containers",
]


def _get_dotted(obj: object, path: str) -> object:
    cur: object = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = getattr(cur, part, None)
    return cur


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def check_arch_required(arch: Arch) -> List[str]:
    missing: List[str] = []
    for p in ARCH_REQUIRED_PATHS:
        if _is_empty(_get_dotted(arch, p)):
            missing.append(p)
    # `edges` is required as a key (must not be None) but may be `[]`.
    if arch.edges is None:
        missing.append("edges (key must be present, [] is allowed)")
    if arch.containers:
        for i, c in enumerate(arch.containers):
            for field in ("archetype", "purpose", "owns_api_resources",
                          "owns_ux_surfaces", "persistence", "deployment_unit"):
                value = getattr(c, field, None)
                # owns_*, persistence may legitimately be empty lists (e.g.
                # backend container with no UX surfaces). Empty lists count
                # as "filled" — Python falsy but explicitly chosen.
                if value is None:
                    missing.append(f"containers[{i}].{field}")
    return missing


def check_container_required(
    c: ArchContainer,
    file_label: str,
    arch: Optional["Arch"] = None,
) -> List[str]:
    """Required-field check for one ARCH__<container>.yaml.

    External-container exemption: if the parent ARCH.yaml has the matching
    container with `external: true`, we skip tech_stack/deployment/
    observability/failure_modes/components requirements. The validator
    surfaces a separate warning that this file should not exist.
    """
    missing: List[str] = []
    parent_external = False
    if arch and arch.containers:
        parent = next(
            (p for p in arch.containers if p.container_id == c.container_id),
            None,
        )
        if parent is not None and parent.external:
            parent_external = True

    if parent_external:
        # Only check identity fields for external containers.
        for field in ("overview",):
            if _is_empty(getattr(c, field, None)):
                missing.append(f"{file_label}: {field}")
        return missing

    for field in ("overview", "tech_stack", "deployment",
                  "observability", "failure_modes", "components"):
        value = getattr(c, field, None)
        if _is_empty(value):
            missing.append(f"{file_label}: {field}")
    if c.tech_stack and _is_empty(c.tech_stack.language):
        missing.append(f"{file_label}: tech_stack.language")
    if c.deployment and _is_empty(c.deployment.shape):
        missing.append(f"{file_label}: deployment.shape")
    if c.components:
        for i, comp in enumerate(c.components):
            for field in ("archetype", "purpose", "responsibilities"):
                if _is_empty(getattr(comp, field, None)):
                    missing.append(f"{file_label}: components[{i}].{field}")
    return missing


# =============================================================================
# ID-prefix format checks (cross-skill conventions)
# =============================================================================

_FEATURE_ID_RE = re.compile(r"^FR-\d+", re.IGNORECASE)
_WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
_FR_PREFIX_RE = re.compile(r"^FR-\d{3,}$", re.IGNORECASE)
_WKF_PREFIX_RE = re.compile(r"^WKF-\d{3,}$", re.IGNORECASE)


def check_warning_ids(warnings: List[str], label: str) -> List[str]:
    """Every *_warnings entry must match 'WRN-NNN: <message>'."""
    errs: List[str] = []
    for i, w in enumerate(warnings or []):
        if not isinstance(w, str) or not _WRN_RE.match(w.strip()):
            errs.append(
                f"{label}[{i}]: '{w}' must start with 'WRN-NNN: ' "
                f"(zero-padded 3-digit number)"
            )
    return errs


def _check_id_prefix(values: object, regex: "re.Pattern[str]", path_label: str) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        return [f"{path_label}: expected a list, got {type(values).__name__}"]
    errs: List[str] = []
    for i, v in enumerate(values):
        if not isinstance(v, str) or not regex.match(v.strip()):
            errs.append(f"{path_label}[{i}]: '{v}' does not match expected ID format")
    return errs


def check_arch_id_formats(arch: Arch) -> List[str]:
    """Enforce FR-NNN / WKF-NNN format on container PRD traces and the
    top-level non_container_features opt-out list."""
    errs: List[str] = []
    errs.extend(_check_id_prefix(
        arch.non_container_features, _FR_PREFIX_RE,
        "non_container_features (expected FR-NNN)"))
    for i, c in enumerate(arch.containers or []):
        errs.extend(_check_id_prefix(
            c.implements_requirements, _FR_PREFIX_RE,
            f"containers[{i}]='{c.container_id}'.implements_requirements (expected FR-NNN)"))
        errs.extend(_check_id_prefix(
            c.traces_prd_workflows, _WKF_PREFIX_RE,
            f"containers[{i}]='{c.container_id}'.traces_prd_workflows (expected WKF-NNN)"))
    return errs


def check_container_id_formats(container: ArchContainer, file_label: str) -> List[str]:
    """Enforce FR-NNN / WKF-NNN format on per-component PRD traces."""
    errs: List[str] = []
    for i, comp in enumerate(container.components or []):
        errs.extend(_check_id_prefix(
            comp.implements_requirements, _FR_PREFIX_RE,
            f"{file_label}: components[{i}]='{comp.component_id}'.implements_requirements (expected FR-NNN)"))
        errs.extend(_check_id_prefix(
            comp.traces_prd_workflows, _WKF_PREFIX_RE,
            f"{file_label}: components[{i}]='{comp.component_id}'.traces_prd_workflows (expected WKF-NNN)"))
    return errs


# =============================================================================
# Cross-checks
# =============================================================================


def load_api_resource_ids(docs_dir: Path) -> List[str]:
    """Return resource_ids from every docs/API__*.yaml."""
    ids: List[str] = []
    for path in sorted(docs_dir.glob("API__*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(raw, dict):
            rid = raw.get("resource_id")
            if rid:
                ids.append(str(rid))
    return ids


def load_api_operation_ids(docs_dir: Path) -> Set[str]:
    """Return the union of every operation_id across all docs/API__*.yaml.

    Operation IDs come from API__<resource>.yaml endpoints[].operation_id.
    Used to validate Component.traces_api_operations and Edge.via_operation_id.
    """
    op_ids: Set[str] = set()
    for path in sorted(docs_dir.glob("API__*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(raw, dict):
            continue
        endpoints = raw.get("endpoints") or []
        if not isinstance(endpoints, list):
            continue
        for ep in endpoints:
            if isinstance(ep, dict):
                oid = ep.get("operation_id")
                if oid:
                    op_ids.add(str(oid))
    return op_ids


def load_api_channel_ids(docs_dir: Path) -> Set[str]:
    """Return API.events.channels[].channel_id from docs/API.yaml."""
    api_path = docs_dir / "API.yaml"
    if not api_path.exists():
        return set()
    try:
        raw = yaml.safe_load(api_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set()
    if not isinstance(raw, dict):
        return set()
    events = raw.get("events") or {}
    if not isinstance(events, dict):
        return set()
    channels = events.get("channels") or []
    if not isinstance(channels, list):
        return set()
    ids: Set[str] = set()
    for ch in channels:
        if isinstance(ch, dict):
            cid = ch.get("channel_id")
            if cid:
                ids.add(str(cid))
    return ids


def load_data_entity_names(data_path: Path) -> Set[str]:
    """Return entity names from DATA-MODEL.yaml.entities (top-level keys)."""
    if not data_path.exists():
        return set()
    try:
        raw = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set()
    if not isinstance(raw, dict):
        return set()
    entities = raw.get("entities") or {}
    if not isinstance(entities, dict):
        return set()
    return {str(k) for k in entities.keys()}


def load_upstream_statuses(docs_dir: Path) -> Dict[str, Optional[str]]:
    """Return metadata.status from each upstream artifact.

    Returns a dict {artifact_name: status_or_None}. None means the file
    was missing or unreadable. Used for the upstream-awareness warning
    cross-check.
    """
    out: Dict[str, Optional[str]] = {}
    for name in ("PRD.yaml", "UX.yaml", "DATA-MODEL.yaml", "API.yaml"):
        p = docs_dir / name
        if not p.exists():
            out[name] = None
            continue
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            out[name] = None
            continue
        if not isinstance(raw, dict):
            out[name] = None
            continue
        meta = raw.get("metadata") or {}
        if not isinstance(meta, dict):
            out[name] = None
            continue
        out[name] = meta.get("status")
    return out


def load_ux_data_bearing_surface_ids(docs_dir: Path) -> List[str]:
    surfaces: List[str] = []
    for path in sorted(docs_dir.glob("UX__*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(raw, dict):
            continue
        sid = raw.get("surface_id")
        stype = raw.get("surface_type")
        if not sid:
            continue
        if stype is None or stype in DATA_BEARING_SURFACE_TYPES:
            surfaces.append(str(sid))
    return surfaces


def load_data_store_ids(data_path: Path) -> Optional[List[str]]:
    """Return store IDs declared in DATA-MODEL.yaml.persistence.

    The canonical sdlc-data shape is roughly:
      persistence:
        primary_store: postgres
        secondary_stores:
          - id: redis-cache
            kind: cache
          - id: s3-blobs
            kind: blob
    Returns a list of *id values*. primary_store is included with its
    string value as the id when no explicit id is set.
    """
    if not data_path.exists():
        return None
    try:
        raw = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    persistence = raw.get("persistence") or {}
    if not isinstance(persistence, dict):
        return []
    ids: List[str] = []
    primary = persistence.get("primary_store")
    if isinstance(primary, str) and primary:
        ids.append(primary)
    elif isinstance(primary, dict):
        pid = primary.get("id") or primary.get("kind") or primary.get("name")
        if pid:
            ids.append(str(pid))
    secondaries = persistence.get("secondary_stores") or []
    if isinstance(secondaries, list):
        for s in secondaries:
            if isinstance(s, dict):
                sid = s.get("id") or s.get("kind") or s.get("name")
                if sid:
                    ids.append(str(sid))
            elif isinstance(s, str):
                ids.append(s)
    return ids


def load_prd_must_have_features(prd_path: Path) -> List[str]:
    """Return FR-NNN prefixes from PRD.functional_requirements.must_have_features.

    Each entry typically starts with 'FR-NNN: <description>'. Returns just the
    normalized FR-NNN prefix. Honors monorepo mode (pulls from every product).
    """
    if not prd_path.exists():
        return []
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    features: List[str] = []
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo")) if isinstance(metadata, dict) else False

    def _pull(node: dict) -> None:
        fr = node.get("functional_requirements") or {}
        mhf = fr.get("must_have_features") if isinstance(fr, dict) else None
        if isinstance(mhf, list):
            for item in mhf:
                m = _FEATURE_ID_RE.match(str(item).strip())
                if m:
                    features.append(m.group(0).upper())

    if monorepo:
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for prod in products.values():
                if isinstance(prod, dict):
                    _pull(prod)
    else:
        _pull(raw)
    return features


def load_prd_id_families(prd_path: Path) -> Dict[str, Set[str]]:
    """Return the union of FR-NNN and WKF-NNN ids declared anywhere in PRD.

    FR draws from must_have_features + nice_to_have_features; WKF from
    use_cases.core_workflows. Used for the existence check on
    implements_requirements / traces_prd_workflows. Honors monorepo mode.
    """
    fr: Set[str] = set()
    wkf: Set[str] = set()
    if not prd_path.exists():
        return {"FR": fr, "WKF": wkf}
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {"FR": fr, "WKF": wkf}
    if not isinstance(raw, dict):
        return {"FR": fr, "WKF": wkf}
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo")) if isinstance(metadata, dict) else False

    _fr_re = re.compile(r"^FR-\d+", re.IGNORECASE)
    _wkf_re = re.compile(r"^WKF-\d+", re.IGNORECASE)

    def _pull(node: dict) -> None:
        freqs = node.get("functional_requirements") or {}
        if isinstance(freqs, dict):
            for key in ("must_have_features", "nice_to_have_features"):
                for item in (freqs.get(key) or []):
                    m = _fr_re.match(str(item).strip())
                    if m:
                        fr.add(m.group(0).upper())
        ucs = node.get("use_cases") or {}
        if isinstance(ucs, dict):
            for item in (ucs.get("core_workflows") or []):
                m = _wkf_re.match(str(item).strip())
                if m:
                    wkf.add(m.group(0).upper())

    if monorepo:
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for prod in products.values():
                if isinstance(prod, dict):
                    _pull(prod)
    else:
        _pull(raw)
    return {"FR": fr, "WKF": wkf}


def check_feature_coverage(arch: Arch, prd_features: List[str]) -> List[str]:
    """Return PRD must-have FR-NNN ids implemented by no container and not
    opted out via non_container_features."""
    if not prd_features:
        return []
    implemented: Set[str] = set()
    for c in arch.containers or []:
        for f in c.implements_requirements or []:
            m = _FEATURE_ID_RE.match(str(f).strip())
            if m:
                implemented.add(m.group(0).upper())
    for f in arch.non_container_features or []:
        m = _FEATURE_ID_RE.match(str(f).strip())
        if m:
            implemented.add(m.group(0).upper())
    return [f for f in prd_features if f.upper() not in implemented]


def check_prd_trace_existence(
    arch: Arch,
    containers_on_disk: Dict[str, "ArchContainer"],
    prd_fr_ids: Set[str],
    prd_wkf_ids: Set[str],
) -> List[str]:
    """implements_requirements / traces_prd_workflows must resolve to PRD ids.

    Also enforces component containment: a component's implements_requirements
    must be a subset of its parent container's implements_requirements.
    Skipped silently when the PRD declares no ids (file absent / pre-convention).
    """
    errs: List[str] = []
    container_implements: Dict[str, Set[str]] = {}
    for c in arch.containers or []:
        cset: Set[str] = set()
        for f in c.implements_requirements or []:
            fu = str(f).strip().upper()
            cset.add(fu)
            if prd_fr_ids and fu not in prd_fr_ids:
                errs.append(
                    f"containers[id='{c.container_id}'].implements_requirements "
                    f"contains '{f}' which is not an FR-NNN id in PRD.yaml"
                )
        for w in c.traces_prd_workflows or []:
            wu = str(w).strip().upper()
            if prd_wkf_ids and wu not in prd_wkf_ids:
                errs.append(
                    f"containers[id='{c.container_id}'].traces_prd_workflows "
                    f"contains '{w}' which is not a WKF-NNN id in PRD.yaml"
                )
        container_implements[c.container_id] = cset

    for fname, container in containers_on_disk.items():
        parent_fr = container_implements.get(container.container_id, set())
        for i, comp in enumerate(container.components or []):
            for f in comp.implements_requirements or []:
                fu = str(f).strip().upper()
                if prd_fr_ids and fu not in prd_fr_ids:
                    errs.append(
                        f"{fname}: components[{i}]='{comp.component_id}'."
                        f"implements_requirements contains '{f}' which is not "
                        f"an FR-NNN id in PRD.yaml"
                    )
                elif parent_fr and fu not in parent_fr:
                    errs.append(
                        f"{fname}: components[{i}]='{comp.component_id}'."
                        f"implements_requirements contains '{f}' which is not in "
                        f"the parent container's implements_requirements"
                    )
            for w in comp.traces_prd_workflows or []:
                wu = str(w).strip().upper()
                if prd_wkf_ids and wu not in prd_wkf_ids:
                    errs.append(
                        f"{fname}: components[{i}]='{comp.component_id}'."
                        f"traces_prd_workflows contains '{w}' which is not a "
                        f"WKF-NNN id in PRD.yaml"
                    )
    return errs


def check_api_coverage(arch: Arch, api_ids: List[str]) -> List[str]:
    if not arch.containers:
        return api_ids[:]
    covered: set = set()
    for c in arch.containers:
        if c.owns_api_resources:
            covered.update(c.owns_api_resources)
    return [r for r in api_ids if r not in covered]


def check_ux_coverage(arch: Arch, ux_ids: List[str]) -> List[str]:
    if not arch.containers:
        return ux_ids[:]
    covered: set = set()
    for c in arch.containers:
        if c.owns_ux_surfaces:
            covered.update(c.owns_ux_surfaces)
    return [s for s in ux_ids if s not in covered]


def check_store_coverage(arch: Arch, store_ids: Optional[List[str]]) -> List[str]:
    if store_ids is None:
        return []
    if not arch.containers:
        return store_ids[:]
    covered: set = set()
    for c in arch.containers:
        if c.persistence:
            covered.update(c.persistence)
    return [s for s in store_ids if s not in covered]


def check_arch_edges(arch: Arch) -> List[str]:
    """Every edges[].from / .to must be a container_id in containers[]."""
    if not arch.edges:
        return []
    valid: set = {c.container_id for c in (arch.containers or [])}
    bad: List[str] = []
    for i, e in enumerate(arch.edges):
        if not e.from_ or e.from_ not in valid:
            bad.append(f"edges[{i}].from='{e.from_}' is not a known container_id")
        if not e.to or e.to not in valid:
            bad.append(f"edges[{i}].to='{e.to}' is not a known container_id")
    return bad


def check_container_edges(
    container: ArchContainer,
    file_label: str,
    arch: Optional[Arch],
) -> List[str]:
    """Internal edges' from/to must be component_ids in this container.
    External edges' to must resolve to <container_id> or
    <container_id>/<component_id> in the system graph.
    """
    errs: List[str] = []
    comp_ids: set = {c.component_id for c in (container.components or [])}

    for i, e in enumerate(container.internal_edges or []):
        if not e.from_ or e.from_ not in comp_ids:
            errs.append(
                f"{file_label}: internal_edges[{i}].from='{e.from_}' "
                f"is not a component in this container"
            )
        if not e.to or e.to not in comp_ids:
            errs.append(
                f"{file_label}: internal_edges[{i}].to='{e.to}' "
                f"is not a component in this container"
            )

    arch_container_ids: set = {c.container_id for c in (arch.containers or [])} if arch else set()
    for i, e in enumerate(container.external_edges or []):
        if not e.from_ or e.from_ not in comp_ids:
            errs.append(
                f"{file_label}: external_edges[{i}].from='{e.from_}' "
                f"is not a component in this container"
            )
        if not e.to:
            errs.append(f"{file_label}: external_edges[{i}].to is empty")
            continue
        # Allow "<container_id>" or "<container_id>/<component_id>".
        target_container, _, _ = e.to.partition("/")
        if arch_container_ids and target_container not in arch_container_ids:
            errs.append(
                f"{file_label}: external_edges[{i}].to='{e.to}' — "
                f"unknown container '{target_container}'"
            )
    return errs


_DEPLOYMENT_COMPAT: Dict[str, Set[str]] = {
    "long_running_service": {"long_running_service", "container"},
    "scheduled_job": {"scheduled_job"},
    "batch_job": {"batch_job"},
    "static_asset": {"static_asset"},
    "serverless_function": {"serverless_function"},
    "container": {"container", "long_running_service"},
    "external_managed": {"managed_service"},
}

# Archetype-specific shapes that override the parent compatibility map.
_ARCHETYPE_SHAPE_OVERRIDES: Dict[str, Set[str]] = {
    "desktop-frontend": {"desktop_app"},
    "mobile-frontend": {"mobile_app"},
    "cli": {"cli_binary"},
}


def check_deployment_compatibility(
    container: ArchContainer,
    arch: Optional[Arch],
    file_label: str,
) -> List[str]:
    """Check that container.deployment.shape is compatible with parent
    container.deployment_unit (per ARCH__CONTAINER schema cross-check #16).
    """
    errs: List[str] = []
    if arch is None or not arch.containers:
        return errs
    if container.deployment is None or container.deployment.shape is None:
        return errs
    parent = next(
        (c for c in arch.containers if c.container_id == container.container_id),
        None,
    )
    if parent is None or parent.deployment_unit is None:
        return errs
    shape_str = container.deployment.shape.value
    unit_str = parent.deployment_unit.value
    parent_arch_str = parent.archetype.value if parent.archetype else None
    allowed = set(_DEPLOYMENT_COMPAT.get(unit_str, set()))
    if parent_arch_str:
        allowed |= _ARCHETYPE_SHAPE_OVERRIDES.get(parent_arch_str, set())
    if shape_str not in allowed:
        errs.append(
            f"{file_label}: deployment.shape='{shape_str}' is not compatible "
            f"with parent deployment_unit='{unit_str}' "
            f"(archetype='{parent_arch_str}'). Allowed: {sorted(allowed)}"
        )
    return errs


def check_component_traces(
    container: ArchContainer,
    arch: Optional[Arch],
    file_label: str,
    api_resource_ids: Set[str],
    api_operation_ids: Set[str],
    ux_surface_ids: Set[str],
    data_entity_names: Set[str],
) -> List[str]:
    """Cross-check #14 — every Component.traces_* entry resolves to an
    upstream artifact AND, for api/ux traces, sits within the parent
    container's owns_*.
    """
    errs: List[str] = []
    if not container.components:
        return errs

    parent_owns_api: Set[str] = set()
    parent_owns_ux: Set[str] = set()
    if arch and arch.containers:
        parent = next(
            (c for c in arch.containers if c.container_id == container.container_id),
            None,
        )
        if parent is not None:
            parent_owns_api = set(parent.owns_api_resources or [])
            parent_owns_ux = set(parent.owns_ux_surfaces or [])

    for i, comp in enumerate(container.components):
        cid = comp.component_id
        # traces_api_resources
        for r in comp.traces_api_resources or []:
            if api_resource_ids and r not in api_resource_ids:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_api_resources "
                    f"contains '{r}' which is not a resource_id in any API__*.yaml"
                )
            elif parent_owns_api and r not in parent_owns_api:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_api_resources "
                    f"contains '{r}' which is not in the parent container's "
                    f"owns_api_resources"
                )
        # traces_api_operations
        for op in comp.traces_api_operations or []:
            if api_operation_ids and op not in api_operation_ids:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_api_operations "
                    f"contains '{op}' which is not an operation_id in any API__*.yaml"
                )
        # traces_ux_surfaces
        for s in comp.traces_ux_surfaces or []:
            if ux_surface_ids and s not in ux_surface_ids:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_ux_surfaces "
                    f"contains '{s}' which is not a surface_id in any UX__*.yaml"
                )
            elif parent_owns_ux and s not in parent_owns_ux:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_ux_surfaces "
                    f"contains '{s}' which is not in the parent container's "
                    f"owns_ux_surfaces"
                )
        # traces_data_entities
        for e in comp.traces_data_entities or []:
            if data_entity_names and e not in data_entity_names:
                errs.append(
                    f"{file_label}: components[{i}]='{cid}'.traces_data_entities "
                    f"contains '{e}' which is not an entity in DATA-MODEL.yaml"
                )
    return errs


def check_edge_via_fields_arch(
    arch: Arch,
    api_resource_ids: Set[str],
    api_channel_ids: Set[str],
    data_entity_names: Set[str],
) -> List[str]:
    """Cross-check #5/6/7 + #15 — every Edge.via_* (when set) resolves."""
    errs: List[str] = []
    for i, e in enumerate(arch.edges or []):
        if e.via_resource_id and api_resource_ids and e.via_resource_id not in api_resource_ids:
            errs.append(
                f"edges[{i}].via_resource_id='{e.via_resource_id}' "
                f"is not a resource_id in any API__*.yaml"
            )
        if e.via_channel_id and api_channel_ids and e.via_channel_id not in api_channel_ids:
            errs.append(
                f"edges[{i}].via_channel_id='{e.via_channel_id}' "
                f"is not a channel_id in API.yaml.events.channels[]"
            )
        if e.via_entity and data_entity_names and e.via_entity not in data_entity_names:
            errs.append(
                f"edges[{i}].via_entity='{e.via_entity}' "
                f"is not an entity in DATA-MODEL.yaml"
            )
    return errs


def check_edge_via_fields_container(
    container: ArchContainer,
    file_label: str,
    api_resource_ids: Set[str],
    api_operation_ids: Set[str],
    api_channel_ids: Set[str],
    data_entity_names: Set[str],
) -> List[str]:
    """Cross-check #15 (container scope) — every InternalEdge/ExternalEdge
    via_* (when set) resolves to upstream artifact.
    """
    errs: List[str] = []

    def _check(label: str, e: Any) -> None:
        rid = getattr(e, "via_resource_id", None)
        oid = getattr(e, "via_operation_id", None)
        cid = getattr(e, "via_channel_id", None)
        ent = getattr(e, "via_entity", None)
        if rid and api_resource_ids and rid not in api_resource_ids:
            errs.append(
                f"{file_label}: {label}.via_resource_id='{rid}' "
                f"is not a resource_id in any API__*.yaml"
            )
        if oid and api_operation_ids and oid not in api_operation_ids:
            errs.append(
                f"{file_label}: {label}.via_operation_id='{oid}' "
                f"is not an operation_id in any API__*.yaml"
            )
        if cid and api_channel_ids and cid not in api_channel_ids:
            errs.append(
                f"{file_label}: {label}.via_channel_id='{cid}' "
                f"is not a channel_id in API.yaml.events.channels[]"
            )
        if ent and data_entity_names and ent not in data_entity_names:
            errs.append(
                f"{file_label}: {label}.via_entity='{ent}' "
                f"is not an entity in DATA-MODEL.yaml"
            )

    for i, e in enumerate(container.internal_edges or []):
        _check(f"internal_edges[{i}]", e)
    for i, e in enumerate(container.external_edges or []):
        _check(f"external_edges[{i}]", e)
    return errs


def check_file_path_integrity(arch: Arch, docs_dir: Path) -> List[str]:
    """Cross-check #8 — file_path ↔ on-disk integrity.

    For every containers[].file_path that is set: the file must exist.
    For every sibling docs/ARCH__*.yaml: it must be referenced by some
    container's file_path.

    Resolution order for a relative file_path (e.g. "docs/ARCH__x.yaml"
    in production, or "ARCH__x.yaml" in a fixture subdir):
      1. `docs_dir.parent / file_path`  (canonical production layout)
      2. `docs_dir / Path(file_path).name`  (fixture / flat layout)
    The first one that exists wins.
    """
    errs: List[str] = []
    referenced: Set[Path] = set()
    if arch.containers:
        for c in arch.containers:
            if c.file_path:
                fp = Path(c.file_path)
                resolved: Optional[Path] = None
                if fp.is_absolute():
                    if fp.exists():
                        resolved = fp
                else:
                    cand1 = (docs_dir.parent / fp).resolve()
                    if cand1.exists():
                        resolved = cand1
                    else:
                        cand2 = (docs_dir / fp.name).resolve()
                        if cand2.exists():
                            resolved = cand2
                if resolved is None:
                    errs.append(
                        f"containers[id='{c.container_id}'].file_path='{c.file_path}' "
                        f"does not exist on disk"
                    )
                else:
                    referenced.add(resolved.resolve())

    on_disk = {p.resolve() for p in docs_dir.glob("ARCH__*.yaml")}
    unreferenced = on_disk - referenced
    for p in sorted(unreferenced):
        errs.append(
            f"{p.name} exists on disk but is not referenced by any "
            f"containers[].file_path"
        )
    return errs


def check_external_container_files(
    arch: Arch,
    containers_on_disk: Dict[str, "ArchContainer"],
) -> List[str]:
    """Cross-check #17 — emit a warning for any ARCH__<id>.yaml whose
    parent container has external: true.
    """
    warnings: List[str] = []
    if not arch.containers:
        return warnings
    external_ids = {c.container_id for c in arch.containers if c.external}
    for fname, container in containers_on_disk.items():
        if container.container_id in external_ids:
            warnings.append(
                f"{fname}: parent container '{container.container_id}' is "
                f"external: true — this file should not exist (external "
                f"containers don't get a deep-dive)"
            )
    return warnings


def check_upstream_status_warnings(docs_dir: Path) -> List[str]:
    """Cross-check #9 — warn if any upstream metadata.status != 'complete'."""
    warnings: List[str] = []
    statuses = load_upstream_statuses(docs_dir)
    for name, status in statuses.items():
        if status is None:
            # Missing upstreams aren't this validator's problem; the skill
            # itself refuses to run. Skip the warning here.
            continue
        if status != "complete":
            warnings.append(
                f"upstream {name}: metadata.status='{status}' "
                f"(arch should only be authored from complete upstreams)"
            )
    return warnings


def check_container_self_consistency(
    container: ArchContainer,
    arch: Optional[Arch],
    file_label: str,
) -> List[str]:
    """Cross-check container yaml fields against the parent ARCH.yaml row.
    Per ARCH__CONTAINER.schema.yaml checks 5-7:
      - api_surface resource_ids ⊆ ARCH.containers[id].owns_api_resources
      - ux_surface  surface_ids  ⊆ ARCH.containers[id].owns_ux_surfaces
      - persistence_bindings store_ids ⊆ ARCH.containers[id].persistence
    """
    errs: List[str] = []
    if arch is None or not arch.containers:
        return errs
    parent: Optional[Container] = next(
        (c for c in arch.containers if c.container_id == container.container_id), None
    )
    if parent is None:
        errs.append(
            f"{file_label}: container_id '{container.container_id}' not in ARCH.yaml.containers[]"
        )
        return errs
    parent_apis = set(parent.owns_api_resources or [])
    for i, item in enumerate(container.api_surface or []):
        if item.resource_id not in parent_apis:
            errs.append(
                f"{file_label}: api_surface[{i}].resource_id='{item.resource_id}' "
                f"not in ARCH.yaml.containers[id].owns_api_resources"
            )
    parent_ux = set(parent.owns_ux_surfaces or [])
    for i, item in enumerate(container.ux_surface or []):
        if item.surface_id not in parent_ux:
            errs.append(
                f"{file_label}: ux_surface[{i}].surface_id='{item.surface_id}' "
                f"not in ARCH.yaml.containers[id].owns_ux_surfaces"
            )
    parent_stores = set(parent.persistence or [])
    for i, item in enumerate(container.persistence_bindings or []):
        if item.store_id not in parent_stores:
            errs.append(
                f"{file_label}: persistence_bindings[{i}].store_id='{item.store_id}' "
                f"not in ARCH.yaml.containers[id].persistence"
            )
    return errs


# =============================================================================
# Loading / orchestration
# =============================================================================


def _load_yaml(path: Path) -> Tuple[Any, Optional[str]]:
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return None, f"YAML parse error in {path}: {e}"
    if raw is None:
        return None, f"{path} is empty"
    if not isinstance(raw, dict):
        return None, f"{path} top level must be a mapping, got {type(raw).__name__}"
    return raw, None


def _format_pydantic_errors(err: ValidationError) -> List[str]:
    formatted: List[str] = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()))
        msg = e.get("msg", "invalid")
        formatted.append(f"{loc}: {msg}")
    return formatted


def discover_container_files(arch_path: Path) -> List[Path]:
    return sorted(arch_path.parent.glob("ARCH__*.yaml"))


def validate_all(arch_path: Path) -> int:
    docs_dir = arch_path.parent

    # 1) ARCH.yaml
    raw, err = _load_yaml(arch_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    try:
        arch = Arch.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] ARCH.yaml FAILED schema validation ({arch_path})\n")
        print("Errors:")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    # 2) Every ARCH__<container>.yaml
    container_files = discover_container_files(arch_path)
    containers: Dict[str, ArchContainer] = {}
    for cp in container_files:
        c_raw, c_err = _load_yaml(cp)
        if c_err:
            print(f"ERROR: {c_err}", file=sys.stderr)
            return 2
        try:
            container = ArchContainer.model_validate(c_raw)
        except ValidationError as e:
            print(f"[FAIL] {cp.name} FAILED schema validation\n")
            for line in _format_pydantic_errors(e):
                print(f"  - {line}")
            return 1
        containers[cp.name] = container

    # 3) Cross-check loaders (run once, reused below)
    api_ids = load_api_resource_ids(docs_dir)
    api_ids_set: Set[str] = set(api_ids)
    api_operation_ids = load_api_operation_ids(docs_dir)
    api_channel_ids = load_api_channel_ids(docs_dir)
    ux_ids = load_ux_data_bearing_surface_ids(docs_dir)
    ux_ids_set: Set[str] = set(ux_ids)
    store_ids = load_data_store_ids(docs_dir / "DATA-MODEL.yaml")
    data_entity_names = load_data_entity_names(docs_dir / "DATA-MODEL.yaml")
    prd_path = docs_dir / "PRD.yaml"
    prd_features = load_prd_must_have_features(prd_path)
    prd_families = load_prd_id_families(prd_path)

    # 4) Required fields (with new external-container exemption)
    missing_arch = check_arch_required(arch)
    missing_containers: List[str] = []
    edge_errs_containers: List[str] = []
    consistency_errs: List[str] = []
    component_trace_errs: List[str] = []
    container_via_errs: List[str] = []
    deployment_compat_errs: List[str] = []
    warning_id_errs: List[str] = check_warning_ids(arch.arch_warnings, "arch_warnings")
    id_format_errs: List[str] = check_arch_id_formats(arch)
    for name, c in containers.items():
        missing_containers.extend(check_container_required(c, name, arch))
        edge_errs_containers.extend(check_container_edges(c, name, arch))
        consistency_errs.extend(check_container_self_consistency(c, arch, name))
        component_trace_errs.extend(
            check_component_traces(
                c, arch, name,
                api_ids_set, api_operation_ids,
                ux_ids_set, data_entity_names,
            )
        )
        container_via_errs.extend(
            check_edge_via_fields_container(
                c, name,
                api_ids_set, api_operation_ids,
                api_channel_ids, data_entity_names,
            )
        )
        deployment_compat_errs.extend(check_deployment_compatibility(c, arch, name))
        warning_id_errs.extend(check_warning_ids(c.arch_warnings, f"{name}: arch_warnings"))
        id_format_errs.extend(check_container_id_formats(c, name))

    # 5) Cross-checks (system level)
    uncovered_api = check_api_coverage(arch, api_ids)
    uncovered_ux = check_ux_coverage(arch, ux_ids)
    uncovered_stores = check_store_coverage(arch, store_ids)
    uncovered_features = check_feature_coverage(arch, prd_features)
    prd_trace_errs = check_prd_trace_existence(
        arch, containers, prd_families["FR"], prd_families["WKF"]
    )
    bad_arch_edges = check_arch_edges(arch)
    arch_via_errs = check_edge_via_fields_arch(
        arch, api_ids_set, api_channel_ids, data_entity_names
    )
    file_path_errs = check_file_path_integrity(arch, docs_dir)
    external_warnings = check_external_container_files(arch, containers)
    upstream_warnings = check_upstream_status_warnings(docs_dir)

    status = arch.metadata.status
    n_containers = len(containers)

    # New convention-driven problem categories (printed via a dedicated
    # helper so the legacy _print_problems signature stays stable).
    extra_problems: List[Tuple[str, List[str]]] = [
        ("arch_warnings / container warnings not in WRN-NNN format", warning_id_errs),
        ("PRD trace ID-format error(s) (expected FR-NNN / WKF-NNN)", id_format_errs),
        ("PRD must-have FR-NNN feature(s) implemented by no container", uncovered_features),
        ("implements_requirements / traces_prd_workflows resolution error(s)", prd_trace_errs),
    ]

    # 6) Reporting — hard problems force draft / block complete.
    # Warnings (external_warnings, upstream_warnings) are surfaced but do
    # NOT block complete on their own.
    problems = bool(
        missing_arch
        or missing_containers
        or uncovered_api
        or uncovered_ux
        or uncovered_stores
        or bad_arch_edges
        or edge_errs_containers
        or consistency_errs
        or component_trace_errs
        or container_via_errs
        or arch_via_errs
        or deployment_compat_errs
        or file_path_errs
        or any(items for _, items in extra_problems)
    )

    if status == "complete" and problems:
        print(f"[FAIL] ARCH.yaml claims status 'complete' but has errors ({arch_path})\n")
        _print_problems(
            missing_arch,
            missing_containers,
            uncovered_api,
            uncovered_ux,
            uncovered_stores,
            bad_arch_edges,
            edge_errs_containers,
            consistency_errs,
            component_trace_errs,
            arch_via_errs,
            container_via_errs,
            deployment_compat_errs,
            file_path_errs,
            store_ids,
        )
        _print_extra_problems(extra_problems)
        _print_warnings(external_warnings, upstream_warnings)
        return 1

    if status == "complete":
        store_note = (
            f"{len(store_ids)} DATA store(s) all bound" if store_ids is not None
            else "DATA-MODEL.yaml missing — store-coverage skipped"
        )
        feat_note = (
            f"{len(prd_features)} PRD FR-NNN feature(s) all implemented"
            if prd_features else "PRD.yaml missing — feature-coverage skipped"
        )
        print(
            f"[OK] ARCH.yaml is valid and complete ({arch_path}); "
            f"{n_containers} container file(s); "
            f"{len(api_ids)} API resource(s) all owned; "
            f"{len(ux_ids)} data-bearing UX surface(s) all owned; "
            f"{store_note}; {feat_note}; edges resolve."
        )
        _print_warnings(external_warnings, upstream_warnings)
        return 0

    # status == "draft"
    store_note = (
        f"{len(store_ids)} DATA store(s) found" if store_ids is not None
        else "DATA-MODEL.yaml missing"
    )
    print(
        f"[DRAFT] ARCH.yaml is a draft ({arch_path}); "
        f"{n_containers} container file(s); "
        f"{len(api_ids)} API resource(s) discovered; "
        f"{len(ux_ids)} data-bearing UX surface(s) discovered; "
        f"{store_note}."
    )
    if problems:
        _print_problems(
            missing_arch,
            missing_containers,
            uncovered_api,
            uncovered_ux,
            uncovered_stores,
            bad_arch_edges,
            edge_errs_containers,
            consistency_errs,
            component_trace_errs,
            arch_via_errs,
            container_via_errs,
            deployment_compat_errs,
            file_path_errs,
            store_ids,
        )
        _print_extra_problems(extra_problems)
    else:
        print(
            "\nAll required fields filled, coverage complete, edges resolve. "
            "Set metadata.status: complete when done."
        )
    _print_warnings(external_warnings, upstream_warnings)
    return 0


def _print_problems(
    missing_arch: List[str],
    missing_containers: List[str],
    uncovered_api: List[str],
    uncovered_ux: List[str],
    uncovered_stores: List[str],
    bad_arch_edges: List[str],
    edge_errs_containers: List[str],
    consistency_errs: List[str],
    component_trace_errs: List[str],
    arch_via_errs: List[str],
    container_via_errs: List[str],
    deployment_compat_errs: List[str],
    file_path_errs: List[str],
    store_ids: Optional[List[str]],
) -> None:
    if missing_arch:
        print(f"{len(missing_arch)} required ARCH.yaml field(s) missing:")
        for m in missing_arch:
            print(f"  - {m}")
        print()
    if missing_containers:
        print(f"{len(missing_containers)} required container-artifact field(s) missing:")
        for m in missing_containers:
            print(f"  - {m}")
        print()
    if uncovered_api:
        print(f"{len(uncovered_api)} API resource(s) not owned by any container:")
        for r in uncovered_api:
            print(f"  - {r}")
        print()
    if uncovered_ux:
        print(f"{len(uncovered_ux)} data-bearing UX surface(s) not owned:")
        for s in uncovered_ux:
            print(f"  - {s}")
        print()
    if uncovered_stores and store_ids is not None:
        print(f"{len(uncovered_stores)} DATA store(s) not bound to any container:")
        for s in uncovered_stores:
            print(f"  - {s}")
        print()
    if bad_arch_edges:
        print(f"{len(bad_arch_edges)} ARCH.yaml edge(s) with unresolved endpoints:")
        for b in bad_arch_edges:
            print(f"  - {b}")
        print()
    if edge_errs_containers:
        print(f"{len(edge_errs_containers)} container-edge endpoint error(s):")
        for b in edge_errs_containers:
            print(f"  - {b}")
        print()
    if consistency_errs:
        print(f"{len(consistency_errs)} container/system consistency error(s):")
        for b in consistency_errs:
            print(f"  - {b}")
        print()
    if component_trace_errs:
        print(f"{len(component_trace_errs)} component trace integrity error(s):")
        for b in component_trace_errs:
            print(f"  - {b}")
        print()
    if arch_via_errs:
        print(f"{len(arch_via_errs)} ARCH.yaml edge via_* resolution error(s):")
        for b in arch_via_errs:
            print(f"  - {b}")
        print()
    if container_via_errs:
        print(f"{len(container_via_errs)} container-edge via_* resolution error(s):")
        for b in container_via_errs:
            print(f"  - {b}")
        print()
    if deployment_compat_errs:
        print(f"{len(deployment_compat_errs)} deployment compatibility error(s):")
        for b in deployment_compat_errs:
            print(f"  - {b}")
        print()
    if file_path_errs:
        print(f"{len(file_path_errs)} container file_path integrity error(s):")
        for b in file_path_errs:
            print(f"  - {b}")


def _print_extra_problems(extra: List[Tuple[str, List[str]]]) -> None:
    """Print convention-driven problem categories (WRN format, PRD traces,
    feature coverage). Kept separate from the legacy _print_problems()."""
    for title, items in extra:
        if items:
            print(f"\n{len(items)} {title}:")
            for it in items:
                print(f"  - {it}")


def _print_warnings(external_warnings: List[str], upstream_warnings: List[str]) -> None:
    if external_warnings:
        print()
        print(f"WARNINGS ({len(external_warnings)} external-container file(s)):")
        for w in external_warnings:
            print(f"  - {w}")
    if upstream_warnings:
        print()
        print(f"WARNINGS ({len(upstream_warnings)} upstream-status issue(s)):")
        for w in upstream_warnings:
            print(f"  - {w}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate ARCH.yaml + every ARCH__*.yaml against the sdlc-arch schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "ARCH.yaml"),
        help="Path to ARCH.yaml (default: ./docs/ARCH.yaml). Sibling ARCH__*.yaml "
        "files in the same directory are validated automatically.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
