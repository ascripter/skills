"""Validate ARCH.yaml + every ARCH__*.yaml against the sdlc-arch schemas,
and run four cross-checks: API-resource coverage, UX-surface coverage,
DATA-store coverage, and edge endpoint integrity.

Run from the project root:

    python sdlc/skills/arch/validate_schema.py
    python sdlc/skills/arch/validate_schema.py --path docs/ARCH.yaml
    python sdlc/skills/arch/validate_schema.py --docs-dir other/docs

Validates:
    1. docs/ARCH.yaml (or --path) — system architecture.
    2. Every docs/ARCH__*.yaml sibling — one per container.
    3. Required-field checks (status: complete gate).
    4. Cross-checks:
       - API-resource coverage: every API__*.yaml resource_id appears
         in some container's owns_api_resources.
       - UX-surface coverage: every UX__*.yaml data-bearing surface_id
         appears in some container's owns_ux_surfaces.
       - DATA-store coverage: every store id in
         DATA-MODEL.yaml.persistence.*_stores appears in some
         container's persistence.
       - Edge endpoint integrity: every edge's `from` / `to` is a valid
         container_id (system level) or component_id (container level),
         and external_edges' `to` resolves against the on-disk graph.

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
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

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
    deployment_unit: Optional[DeploymentUnit] = None
    ownership: Optional[ContainerOwnership] = None
    external: bool = False
    status: Optional[ContainerStatus] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None


class Edge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    type: Optional[EdgeType] = None
    note: Optional[str] = None


class Arch(BaseModel):
    """Top-level docs/ARCH.yaml."""

    model_config = ConfigDict(extra="allow")

    metadata: ArchMetadata
    architecture_pattern: Optional[ArchitecturePattern] = None
    identity_and_auth: Optional[IdentityAndAuth] = None
    containers: Optional[List[Container]] = None
    edges: Optional[List[Edge]] = None
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


class Component(_Base):
    component_id: str
    archetype: Optional[str] = None
    purpose: Optional[str] = None
    responsibilities: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    traces_api_resources: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    traces_data_entities: Optional[List[str]] = None
    failure_modes: Optional[List[str]] = None
    status: Optional[ContainerStatus] = None


class InternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    type: Optional[EdgeType] = None
    note: Optional[str] = None


class ExternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None  # "<container_id>" or "<container_id>/<component_id>"
    type: Optional[EdgeType] = None
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
    security_concerns: Optional[List[str]] = None
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

ARCH_REQUIRED_PATHS: List[str] = [
    "architecture_pattern.pattern",
    "architecture_pattern.rationale",
    "identity_and_auth.identity_provider",
    "identity_and_auth.token_strategy",
    "containers",
    "edges",
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


def check_container_required(c: ArchContainer, file_label: str) -> List[str]:
    missing: List[str] = []
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

    # 3) Required fields
    missing_arch = check_arch_required(arch)
    missing_containers: List[str] = []
    edge_errs_containers: List[str] = []
    consistency_errs: List[str] = []
    for name, c in containers.items():
        missing_containers.extend(check_container_required(c, name))
        edge_errs_containers.extend(check_container_edges(c, name, arch))
        consistency_errs.extend(check_container_self_consistency(c, arch, name))

    # 4) Cross-checks
    api_ids = load_api_resource_ids(docs_dir)
    ux_ids = load_ux_data_bearing_surface_ids(docs_dir)
    store_ids = load_data_store_ids(docs_dir / "DATA-MODEL.yaml")

    uncovered_api = check_api_coverage(arch, api_ids)
    uncovered_ux = check_ux_coverage(arch, ux_ids)
    uncovered_stores = check_store_coverage(arch, store_ids)
    bad_arch_edges = check_arch_edges(arch)

    status = arch.metadata.status
    n_containers = len(containers)

    # 5) Reporting
    problems = bool(
        missing_arch
        or missing_containers
        or uncovered_api
        or uncovered_ux
        or uncovered_stores
        or bad_arch_edges
        or edge_errs_containers
        or consistency_errs
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
            store_ids,
        )
        return 1

    if status == "complete":
        store_note = (
            f"{len(store_ids)} DATA store(s) all bound" if store_ids is not None
            else "DATA-MODEL.yaml missing — store-coverage skipped"
        )
        print(
            f"[OK] ARCH.yaml is valid and complete ({arch_path}); "
            f"{n_containers} container file(s); "
            f"{len(api_ids)} API resource(s) all owned; "
            f"{len(ux_ids)} data-bearing UX surface(s) all owned; "
            f"{store_note}; edges resolve."
        )
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
            store_ids,
        )
    else:
        print(
            "\nAll required fields filled, coverage complete, edges resolve. "
            "Set metadata.status: complete when done."
        )
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
