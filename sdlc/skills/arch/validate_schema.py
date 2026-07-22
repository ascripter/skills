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
       - FR-NNN or NFR-NNN on every implements_requirements entry
         (containers + components); FR-NNN on non_container_features.
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
       - PRD feature coverage: every PRD FR-NNN (the flat `features` list,
         or the legacy must/nice union) appears in some container's
         implements_requirements OR in ARCH.yaml.non_container_features.
         Skipped if PRD.yaml absent.
    6. Edge + trace integrity (block status: complete):
       - Edge endpoint integrity: every edge's `from` / `to` is a valid
         container_id (system level) or component_id (container level),
         and external_edges' `to` resolves against the on-disk graph.
       - Edge via_* resolution against API / DATA upstreams.
       - Component traces (api/ux/data/work_units) resolve upstream and
         sit within the parent container's owns_*.
       - implements_requirements / traces_prd_workflows resolve to PRD
         FR-NNN/NFR-NNN / WKF-NNN ids; component features ⊆ parent
         container's.
    7. Component work_units (block status: complete):
       - #21 per-unit integrity (unique name, summary, trace subsets) AND
         — the blocking upgrade — a NON-TRIVIAL component (archetype outside
         the plumbing set, carrying implements_requirements or a traced
         contract) that declares no work_units blocks complete unless it
         records an explicit `work_units_waiver`. work_units are parsed from
         the YAML (block- or flow-style entries both count) — never grepped.
       - #22 callable-level FR coverage: for every component that declares
         work_units, each FR-NNN in its implements_requirements must appear in
         at least one of its work_units[].implements_requirements (waivable per
         component). Rolls up to a per-container report of FRs unreachable
         through any work_unit.
       - #23 DEFER-OR-DECLARE interface contract: a non-callable work_unit
         (kind: module | content | tooling — the deliverable is a file) is
         exempt; otherwise a work_unit that traces NO
         schema-bearing upstream contract (no traces_api_operation) must
         DECLARE its interface contract — `inputs`, `output`, and `raises` all
         present (explicit empties `inputs: []` / `raises: []` / `output:
         "None"` count as declared). A unit with traces_api_operation may
         defer to the API schema. FAMILY (opt-in, any project with uniform
         unit families): if the container declares
         `work_unit_family_contracts`, a unit belonging to a family inherits
         that family's shared contract and may omit its own (declare one
         contract per uniform unit family instead of repeating it per
         member). Blocking; a component-level `work_units_waiver` downgrades
         it to a warning. Advisory (SK-21): a component where >= 3 callable
         DECLARE units are >= 80% all-empty gets one emptiness roll-up
         warning (an emitter stamping the shape).
    8. Edge-table consistency (block status: complete):
       - #24 container→system edge roll-up: every external_edges[] entry in a
         container file implies a system-level ARCH.yaml.edges row
         (from=this container, to=the target container, same type). A
         container-sourced edge that never propagated to the system edge
         table is an error.
       - external_edges[].via_unit (when set) resolves to a work_units[].name
         on the target `<container>/<component>` (the internal-call analogue
         of via_operation_id for sibling containers with no API between them).
    9. Advisory warnings (never block):
       - #25 FR-named deliverable paths: a concrete repo path named as inline
         code (backticks) in the text of an FR that some container/component
         claims must fall inside some component's code_location — otherwise
         downstream `task` can never schedule work that builds it (build-time
         deliverables: schema layers, repo tools/, templates/, shipped
         content). Only backtick-delimited tokens with path shape (a trailing
         '/' or a file extension) are scanned; bare prose slashes and backticked
         non-paths (and/or, PyPI/npm, ID-lists like FR-046/047, pass/fail) are
         ignored.
       - #26 api_consumers mirror: an external `calls` edge with
         via_resource_id should be mirrored in the container's
         api_consumers[].

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
import fnmatch
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
    # Build-time deliverable classes — components whose output is shipped by
    # the build/authoring process rather than executed as a runtime callable.
    # They exist so FR-named deliverables (a schema layer, repo tools/,
    # templates/, prompt packs) get a component + code_location + work_units
    # and downstream `task` can actually schedule building them.
    schema_model = "schema_model"          # typed domain-model / schema layer shipped as code
    dev_tool = "dev_tool"                  # repo tools/ validators, generators, migration scripts
    content_asset = "content_asset"        # shipped content: templates, prompts, question packs
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
    # One entry per upstream artifact consumed, each a mapping
    # {file, session_id, last_updated, sha256}. Type-checked as a list of
    # mappings only — see CLAUDE.md §7 "Upstream-change re-invocation".
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


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
    implements_requirements: Optional[List[str]] = None  # FR-NNN or NFR-NNN
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
    invocation: Optional[Any] = None     # caller-side INPUT binding for a process/
                                         # subprocess seam: the mode selector + resolved
                                         # args/params this caller invokes the callee with.
                                         # The callee's entrypoint work_unit is the shared
                                         # contract; this records how THIS caller binds it.
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
    # One entry per upstream artifact consumed at the time this container was
    # drilled, each a mapping {file, session_id, last_updated, sha256}. Lets a
    # later /sdlc:arch <container> detect upstream drift since the last drill.
    # See CLAUDE.md §7 "Upstream-change re-invocation".
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


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


class WorkUnit(_Base):
    """A single named callable a component exposes (C4 interface level; cross-check #21).

    Addressed as (component, name) — there is NO id family. `name` is the callable
    (method / function / Class.method), unique within its owning component; it is the
    stable handle the downstream `task` skill references as a Task.target_symbol to
    slice EXACTLY ONE atomic implementation task per work_unit. name + summary are
    required; every trace field is optional. The interface contract
    (inputs/output/raises/signature) is DEFER-OR-DECLARE: a work_unit realizing a
    schema-bearing traced contract may leave them empty and defer; a domain callable
    declares them so atomic tasks compose against a frozen interface. `output` is left
    untyped (str) since it is a free-form return hint.
    """

    name: Optional[str] = None
    summary: Optional[str] = None
    kind: Optional[str] = None                          # callable (default) | module |
                                                        # content | tooling | entrypoint — the
                                                        # deliverable class (demo FR-013 v1.30).
                                                        # entrypoint = the composition/dispatch
                                                        # root of a single-file/multi-mode
                                                        # deliverable. Checked against
                                                        # _WORK_UNIT_KINDS in #21 so a draft
                                                        # with a typo stays loadable.
    traces_api_operation: Optional[str] = None          # operation_id in API__*.yaml
    implements_requirements: Optional[List[str]] = None  # FR-NNN/NFR-NNN ⊆ component
    touches_entities: Optional[List[str]] = None         # ⊆ component traces_data_entities
    satisfies_acceptance: Optional[List[str]] = None
    inputs: Optional[List[str]] = None
    output: Optional[Any] = None
    raises: Optional[List[str]] = None
    signature: Optional[str] = None
    status: Optional[ContainerStatus] = None


class Component(_Base):
    component_id: str
    archetype: Optional[ComponentArchetype] = None
    purpose: Optional[str] = None
    responsibilities: Optional[List[str]] = None
    code_location: Optional[List[str]] = None  # repo-relative dirs/files; the
                                               # component→code-module seam.
    inputs: Optional[List[str]] = None
    outputs: Optional[List[str]] = None
    traces_api_resources: Optional[List[str]] = None
    traces_api_operations: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    traces_data_entities: Optional[List[str]] = None
    implements_requirements: Optional[List[str]] = None  # FR-NNN or NFR-NNN
    traces_prd_workflows: Optional[List[str]] = None      # WKF-NNN
    failure_modes: Optional[List[ComponentFailureMode]] = None
    acceptance_criteria: Optional[List[str]] = None
    work_units: Optional[List[WorkUnit]] = None           # named callables (component,name)
    work_units_waiver: Optional[str] = None               # recorded reason a non-trivial
                                                          # component legitimately declares no
                                                          # work_units, or realizes some FR
                                                          # purely by wiring (waives #21/#22).
    status: Optional[ContainerStatus] = None


class InternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    type: Optional[EdgeType] = None
    via_resource_id: Optional[str] = None
    via_unit: Optional[str] = None       # work_units[].name on the `to` component
    via_entity: Optional[str] = None
    note: Optional[str] = None


class ExternalEdge(_Base):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None  # "<container_id>" or "<container_id>/<component_id>"
    type: Optional[EdgeType] = None
    via_resource_id: Optional[str] = None
    via_operation_id: Optional[str] = None
    via_unit: Optional[str] = None       # for `calls` into a sibling container with no
                                         # API between them: the work_units[].name on the
                                         # target "<container_id>/<component_id>" component
                                         # (point it at the callee's `entrypoint` unit for a
                                         # subprocess/CLI seam — that unit pins argv/mode ⇄
                                         # exit-code/stdout/stderr for BOTH sides).
    via_channel_id: Optional[str] = None
    via_entity: Optional[str] = None
    invocation: Optional[Any] = None     # caller-side INPUT binding: the mode selector +
                                         # resolved args/params this caller invokes with.
    note: Optional[str] = None


class WorkUnitFamilyContract(BaseModel):
    """One DEFER-OR-DECLARE contract shared by a uniform work_unit *family*.

    An opt-in pattern for ANY project whose units form uniform families
    (>= 3 units sharing one contract shape: gate units, stage-node bodies,
    CLI verb handlers, subgraph/sub-agent runners); the meta-corpus dialect
    merely required it first (a CLI factory with NO API layer has no OPR for
    a unit to DEFER to). Declare ONE shared inputs/output/raises contract per
    family instead of repeating it on every terse member — and prefer this
    over stamping empty contracts across members (the #23 emptiness advisory
    flags that shape). A member INHERITS its family's contract unless it
    overrides with its own inputs/output/raises.

    Declaring a non-empty `work_unit_family_contracts` list opts the container
    in: cross-check 23 then treats a family member as DECLARED even when it
    omits inputs/output/raises. A container with no such block keeps the
    strict per-unit DECLARE requirement. Membership is the UNION of the
    selectors provided — a unit matches when its owning component_id is in
    `member_components`, OR that component's archetype is in `member_archetypes`,
    OR its `name` matches any glob in `member_name_globs`.
    """

    model_config = ConfigDict(extra="allow")

    family: str                                    # the family label (e.g. "gate-units")
    contract: Optional[str] = None                 # prose description of the shared contract
    inputs: Optional[List[str]] = None             # shared input contract
    output: Optional[Any] = None                   # shared output contract
    raises: Optional[List[str]] = None             # shared error contract
    member_components: Optional[List[str]] = None  # component_ids whose units belong
    member_archetypes: Optional[List[str]] = None  # component archetypes whose units belong
    member_name_globs: Optional[List[str]] = None  # fnmatch globs on work_unit.name


def _unit_matches_family(
    comp: "Component",
    unit_name: Optional[str],
    families: List[WorkUnitFamilyContract],
) -> bool:
    """True if the unit belongs to any declared family contract (meta-corpus
    dialect). A unit matches when its component_id is listed in a family's
    `member_components`, its owning component's archetype is listed in
    `member_archetypes`, or its `name` matches a family `member_name_globs`
    pattern."""
    cid = comp.component_id
    archetype = comp.archetype.value if getattr(comp, "archetype", None) else None
    for fc in families:
        if fc.member_components and cid in fc.member_components:
            return True
        if fc.member_archetypes and archetype and archetype in fc.member_archetypes:
            return True
        if fc.member_name_globs and unit_name:
            if any(fnmatch.fnmatchcase(unit_name, g) for g in fc.member_name_globs):
                return True
    return False


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
    # Meta-corpus dialect (optional, opt-in): a non-empty list declares one
    # shared DEFER-OR-DECLARE contract per uniform work_unit family, so terse
    # members inherit it (cross-check 23 arm b). Absent for a generated app.
    work_unit_family_contracts: Optional[List[WorkUnitFamilyContract]] = None
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
# implements_requirements may trace BOTH functional (FR-NNN) and non-functional
# (NFR-NNN) requirements — a container can be the home of an NFR (a timeout cap,
# an input-containment boundary) just as it implements features. FR-coverage
# (every FR) is unaffected: it only counts FR-NNN entries.
_FR_OR_NFR_PREFIX_RE = re.compile(r"^(?:FR|NFR)-\d{3,}$", re.IGNORECASE)
_NFR_ID_RE = re.compile(r"^NFR-\d+", re.IGNORECASE)


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
            c.implements_requirements, _FR_OR_NFR_PREFIX_RE,
            f"containers[{i}]='{c.container_id}'.implements_requirements (expected FR-NNN or NFR-NNN)"))
        errs.extend(_check_id_prefix(
            c.traces_prd_workflows, _WKF_PREFIX_RE,
            f"containers[{i}]='{c.container_id}'.traces_prd_workflows (expected WKF-NNN)"))
    return errs


def check_container_id_formats(container: ArchContainer, file_label: str) -> List[str]:
    """Enforce FR-NNN/NFR-NNN / WKF-NNN format on per-component PRD traces."""
    errs: List[str] = []
    for i, comp in enumerate(container.components or []):
        errs.extend(_check_id_prefix(
            comp.implements_requirements, _FR_OR_NFR_PREFIX_RE,
            f"{file_label}: components[{i}]='{comp.component_id}'.implements_requirements (expected FR-NNN or NFR-NNN)"))
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
    Used to validate Component.traces_api_operations, WorkUnit.traces_api_operation,
    and ExternalEdge.via_operation_id.
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


def load_data_enum_names(data_path: Path) -> Set[str]:
    """Return enum type names from DATA-MODEL.yaml.enums_and_lookups.enums.

    Enums are value types (closed sets), NOT entities. Used only to turn the
    'not an entity' error into targeted guidance when a component traces an
    enum by mistake. Mirrors load_data_entity_names (top-level / system mode);
    in monorepo mode entities live under products.<slug>, so the entity set is
    empty there and the trace cross-check is skipped anyway.
    """
    if not data_path.exists():
        return set()
    try:
        raw = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set()
    if not isinstance(raw, dict):
        return set()
    block = raw.get("enums_and_lookups") or {}
    if not isinstance(block, dict):
        return set()
    enums = block.get("enums") or {}
    if not isinstance(enums, dict):
        return set()
    return {str(k) for k in enums.keys()}


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


def load_prd_features(prd_path: Path) -> List[str]:
    """Return the gating FR-NNN prefixes from PRD.functional_requirements.

    D2 gating subset (FR_GATE, CLAUDE.md §10): the flat `features` list when
    present, else the legacy `must_have_features` ONLY — a legacy PRD's
    nice_to_have backlog stays outside the container-coverage check (check #4),
    preserving pre-D2 behavior so a widened scope can't hard-fail legacy ARCHs.
    Each entry typically starts with 'FR-NNN: <description>'; returns just the
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
        if not isinstance(fr, dict):
            return
        feats = fr.get("features")
        if not feats:  # legacy: must_have only (nice_to_have stays ungated)
            feats = fr.get("must_have_features") or []
        if isinstance(feats, list):
            for item in feats:
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
    """Return the union of FR-NNN, NFR-NNN and WKF-NNN ids declared in PRD.

    FR draws from the flat `features` list (or the legacy must_have_features +
    nice_to_have_features union); NFR from
    non_functional_requirements.performance_targets + .other; WKF from
    use_cases.core_workflows. Used for the existence check on
    implements_requirements (FR or NFR) / traces_prd_workflows. Honors
    monorepo mode.
    """
    fr: Set[str] = set()
    nfr: Set[str] = set()
    wkf: Set[str] = set()
    empty = {"FR": fr, "NFR": nfr, "WKF": wkf}
    if not prd_path.exists():
        return empty
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return empty
    if not isinstance(raw, dict):
        return empty
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo")) if isinstance(metadata, dict) else False

    _fr_re = re.compile(r"^FR-\d+", re.IGNORECASE)
    _nfr_re = re.compile(r"^NFR-\d+", re.IGNORECASE)
    _wkf_re = re.compile(r"^WKF-\d+", re.IGNORECASE)

    def _pull(node: dict) -> None:
        freqs = node.get("functional_requirements") or {}
        if isinstance(freqs, dict):
            for key in ("features", "must_have_features", "nice_to_have_features"):
                for item in (freqs.get(key) or []):
                    m = _fr_re.match(str(item).strip())
                    if m:
                        fr.add(m.group(0).upper())
        nfreqs = node.get("non_functional_requirements") or {}
        if isinstance(nfreqs, dict):
            for key in ("performance_targets", "other"):
                for item in (nfreqs.get(key) or []):
                    m = _nfr_re.match(str(item).strip())
                    if m:
                        nfr.add(m.group(0).upper())
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
    return {"FR": fr, "NFR": nfr, "WKF": wkf}


def check_feature_coverage(arch: Arch, prd_features: List[str]) -> List[str]:
    """Return PRD FR-NNN ids implemented by no container and not
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
    prd_nfr_ids: "Set[str] | None" = None,
) -> List[str]:
    """implements_requirements / traces_prd_workflows must resolve to PRD ids.

    `implements_requirements` may carry FR-NNN (resolved against PRD features)
    or NFR-NNN (resolved against PRD non-functional requirements). Also enforces
    component containment: a component's implements_requirements must be a subset
    of its parent container's. Each family check is skipped silently when the PRD
    declares no ids of that family (file absent / pre-convention).
    """
    prd_nfr_ids = prd_nfr_ids or set()
    errs: List[str] = []

    def _resolve(value: str, where: str) -> None:
        vu = str(value).strip().upper()
        if vu.startswith("NFR-"):
            if prd_nfr_ids and vu not in prd_nfr_ids:
                errs.append(f"{where} contains '{value}' which is not an NFR-NNN id in PRD.yaml")
        elif prd_fr_ids and vu not in prd_fr_ids:
            errs.append(f"{where} contains '{value}' which is not an FR-NNN id in PRD.yaml")

    container_implements: Dict[str, Set[str]] = {}
    for c in arch.containers or []:
        cset: Set[str] = set()
        for f in c.implements_requirements or []:
            cset.add(str(f).strip().upper())
            _resolve(f, f"containers[id='{c.container_id}'].implements_requirements")
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
                where = (
                    f"{fname}: components[{i}]='{comp.component_id}'."
                    f"implements_requirements"
                )
                before = len(errs)
                _resolve(f, where)
                if len(errs) == before and parent_fr and fu not in parent_fr:
                    errs.append(
                        f"{where} contains '{f}' which is not in "
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
    data_enum_names: Optional[Set[str]] = None,
) -> List[str]:
    """Cross-check #14 — every Component.traces_* entry resolves to an
    upstream artifact AND, for api/ux traces, sits within the parent
    container's owns_*.
    """
    data_enum_names = data_enum_names or set()
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
        # traces_data_entities — must resolve to an ENTITY. Enums
        # (enums_and_lookups.enums) are value types, not entities: a component
        # that "uses" an enum actually reads/writes the entity that carries it,
        # so the trace must point at that entity.
        for e in comp.traces_data_entities or []:
            if data_entity_names and e not in data_entity_names:
                if e in data_enum_names:
                    errs.append(
                        f"{file_label}: components[{i}]='{cid}'.traces_data_entities "
                        f"contains '{e}', which is an enum "
                        f"(DATA-MODEL.yaml enums_and_lookups.enums), not an entity. "
                        f"traces_data_entities references entities only — trace the "
                        f"entity that carries this enum-typed field instead."
                    )
                else:
                    errs.append(
                        f"{file_label}: components[{i}]='{cid}'.traces_data_entities "
                        f"contains '{e}' which is not an entity in DATA-MODEL.yaml"
                    )
    return errs


# A `<placeholder>` token inside a code_location path — an unresolved
# parameterized/templated binding (`.../<stack>/...`) that codegen would have
# to re-derive. Cross-check #20 warns on it (Gap-6).
_TEMPLATE_TOKEN_RE = re.compile(r"<[^<>/\s]+>")


def _looks_like_file(token: str) -> bool:
    """A code_location token names a single FILE (not a directory) when it does
    not end with '/' and its final segment carries an extension. Used by #21 to
    spot a single-file, multi-callable component that needs an `entrypoint`
    work_unit to own its top-level control flow (Gap-1)."""
    token = token.strip()
    if not token or token.endswith("/"):
        return False
    return "." in token.rsplit("/", 1)[-1]

# Plumbing component archetypes that don't need an explicit code_location —
# their placement is conventional and uninteresting to downstream codegen.
_PLUMBING_COMPONENT_ARCHETYPES = {
    "config_loader",
    "serializer",
    "observability_bootstrap",
    "error_handler",
}

# WorkUnit deliverable classes (demo FR-013 v1.30 / DATA-MODEL v2.21
# WorkUnitKind). `callable` is the default when `kind` is omitted; the
# non-callable kinds deliver a FILE (module = a source module whose definition
# set is the interface; content = a shipped content file; tooling = a repo
# tool/validator script) and are exempt from the #23 DEFER-OR-DECLARE
# interface-contract check. `entrypoint` is the composition/dispatch root of a
# single-file or multi-run-mode deliverable (a CLI/shell entrypoint) — it owns
# arg/mode parsing, step-sequencing, setup/teardown and exit semantics. It is
# CALLABLE-dialect (argv/env in, exit code out), so it is NOT in the
# non-callable set and #23 requires it to DECLARE inputs/output/raises.
_WORK_UNIT_KINDS = {"callable", "module", "content", "tooling", "entrypoint"}
_NON_CALLABLE_WORK_UNIT_KINDS = {"module", "content", "tooling"}

# Container archetypes whose DELIVERABLE is an invoked executable (a CLI/shell
# tool, a build script). Only these get the Gap-1 "single-file needs an
# entrypoint" nudge — a framework-routed service/controller dispatches through
# its web framework, not a hand-written composition root, so it must NOT warn.
_ENTRYPOINT_CONTAINER_ARCHETYPES = {"cli", "other"}


def check_component_code_location(
    container: ArchContainer,
    file_label: str,
) -> List[str]:
    """Cross-check #20 (advisory, non-blocking) — a non-trivial component that
    carries at least one upstream trace but no `code_location` gets a WARNING:
    downstream `task`/codegen will have to invent its file placement.
    """
    warnings: List[str] = []
    for i, comp in enumerate(container.components or []):
        archetype = comp.archetype.value if comp.archetype else None
        # Gap-6 (advisory, any archetype): a parameterized/templated code_location
        # (`.../<stack>/...`) forces codegen to re-derive the binding. Bind the
        # concrete MVP variant and model further variants as their own tasks.
        for loc in comp.code_location or []:
            if _TEMPLATE_TOKEN_RE.search(str(loc)):
                warnings.append(
                    f"{file_label}: components[{i}]='{comp.component_id}'."
                    f"code_location '{loc}' contains an unresolved template "
                    f"placeholder — bind the concrete MVP-variant path and model "
                    f"other variants as their own components/work_units (or defer "
                    f"via WRN); don't leave codegen to re-derive the binding"
                )
        if archetype in _PLUMBING_COMPONENT_ARCHETYPES:
            continue
        has_trace = any([
            comp.traces_api_resources,
            comp.traces_api_operations,
            comp.traces_ux_surfaces,
            comp.traces_data_entities,
            comp.implements_requirements,
        ])
        if has_trace and not comp.code_location:
            warnings.append(
                f"{file_label}: components[{i}]='{comp.component_id}' has no "
                f"code_location — downstream task/codegen must infer its file "
                f"placement (set code_location to its source dir(s))"
            )
    return warnings


def check_component_work_units(
    container: ArchContainer,
    file_label: str,
    api_operation_ids: Set[str],
    data_entity_names: Set[str],
) -> Tuple[List[str], List[str]]:
    """Cross-check #21 — validate each component's work_units[] (the named callables
    the downstream `task` skill slices exactly one atomic task per).

    Returns (errs, warns). Errs force draft / block complete; warns are advisory.

      errs:
        * name is non-empty and UNIQUE within its owning component (work_units are
          addressed as (component, name) — there is no id family).
        * summary is non-empty.
        * traces_api_operation resolves to an API operation_id (when API present).
        * implements_requirements are FR/NFR format AND ⊆ the OWNING component's
          implements_requirements.
        * touches_entities ⊆ the owning component's traces_data_entities (and a
          DATA-MODEL entity when present).
        * a NON-TRIVIAL component (archetype outside the plumbing set AND carrying
          implements_requirements or a traced contract) that declares no work_units
          and records no `work_units_waiver` — this BLOCKS complete. Without it a
          container could be "complete" while downstream `task` silently seeds no
          implementation task for a third of it. The escape hatch is an explicit
          per-component waiver: `work_units: []` plus a non-empty `work_units_waiver`
          note (e.g. "realized purely by wiring"), which downgrades this to advisory.
      warns:
        * a non-trivial component that declares no work_units but records a
          `work_units_waiver` — surfaced so a reviewer sees the waiver, non-blocking.
        * SK-22 missing-key: units touch entities but the component's
          `traces_data_entities` is missing/empty — the subset check above has
          no base to fire against, so the drift would go unseen. Advisory; the
          fix is the Phase 7 derive rule (component list = curated entries
          UNION the units' touches).
        * Gap-2 (per unit) and Gap-1 (per component) advisories — see the
          inline comments below.

    Name uniqueness is checked here (not as a raising model_validator) so a draft
    with duplicate names stays loadable and reports a fixable error.
    """
    errs: List[str] = []
    warns: List[str] = []
    container_archetype = container.archetype.value if container.archetype else None
    for i, comp in enumerate(container.components or []):
        cid = comp.component_id
        archetype = comp.archetype.value if comp.archetype else None
        comp_reqs = {str(r).strip().upper() for r in (comp.implements_requirements or [])}
        comp_ents = {str(e).strip() for e in (comp.traces_data_entities or [])}
        units = comp.work_units or []
        waiver = (comp.work_units_waiver or "").strip()
        seen_names: Set[str] = set()            # names seen within THIS component
        touched_ents: Set[str] = set()          # union of units' touches_entities
        if not units and archetype not in _PLUMBING_COMPONENT_ARCHETYPES:
            has_trace = any([
                comp.traces_api_resources, comp.traces_api_operations,
                comp.traces_ux_surfaces, comp.traces_data_entities,
                comp.implements_requirements,
            ])
            if has_trace:
                if waiver:
                    warns.append(
                        f"{file_label}: components[{i}]='{cid}' declares no work_units "
                        f"but records work_units_waiver ('{waiver}') — waived, non-blocking"
                    )
                else:
                    errs.append(
                        f"{file_label}: components[{i}]='{cid}' is non-trivial "
                        f"(archetype '{archetype}' with traced requirements/contracts) but "
                        f"declares no work_units — downstream `task` would seed no atomic "
                        f"implementation task for it. Enumerate its public/contract-bearing "
                        f"callables in work_units, or record an explicit work_units_waiver."
                    )
        for j, op in enumerate(units):
            where = f"{file_label}: components[{i}]='{cid}'.work_units[{j}]"
            if op.kind is not None and op.kind not in _WORK_UNIT_KINDS:
                errs.append(
                    f"{where}: kind '{op.kind}' is not one of "
                    f"{sorted(_WORK_UNIT_KINDS)} (omit for the default 'callable')"
                )
            name = (op.name or "").strip()
            if not name:
                errs.append(f"{where}: missing name")
            else:
                key = name.lower()
                if key in seen_names:
                    errs.append(
                        f"{where}.name='{name}' is duplicated within component "
                        f"'{cid}' (work_unit names must be unique per component)"
                    )
                else:
                    seen_names.add(key)
            if not (op.summary or "").strip():
                errs.append(f"{where}: missing summary")
            if op.traces_api_operation:
                t = str(op.traces_api_operation).strip()
                if api_operation_ids and t not in api_operation_ids:
                    errs.append(
                        f"{where}.traces_api_operation='{t}' is not an operation_id "
                        f"in any API__*.yaml"
                    )
            for r in op.implements_requirements or []:
                ru = str(r).strip().upper()
                if not _FR_OR_NFR_PREFIX_RE.match(ru):
                    errs.append(
                        f"{where}.implements_requirements '{r}' is not an "
                        f"FR-NNN/NFR-NNN id"
                    )
                elif comp_reqs and ru not in comp_reqs:
                    errs.append(
                        f"{where}.implements_requirements '{r}' is not in the owning "
                        f"component '{cid}' implements_requirements"
                    )
            for e in op.touches_entities or []:
                es = str(e).strip()
                touched_ents.add(es)
                if data_entity_names and es not in data_entity_names:
                    errs.append(
                        f"{where}.touches_entities '{e}' is not an entity in "
                        f"DATA-MODEL.yaml"
                    )
                elif comp_ents and es not in comp_ents:
                    errs.append(
                        f"{where}.touches_entities '{e}' is not in the owning "
                        f"component '{cid}' traces_data_entities - complete the "
                        f"component's traces_data_entities to the union of its "
                        f"units' touches_entities (Phase 7 derive rule)"
                    )
            # Gap-2 (advisory): a DECLARE-dialect unit that declares nothing to
            # emit (no inputs, output "None", raises nothing) is usually a policy
            # honored externally, not a callable — model it as a security_concern /
            # acceptance_criterion + a test, not a work_unit (which becomes a
            # codegen task with no code).
            out = op.output
            if (
                op.kind not in _NON_CALLABLE_WORK_UNIT_KINDS
                and not op.traces_api_operation
                and isinstance(out, str)
                and out.strip().lower() == "none"
                and not (op.inputs or [])
                and not (op.raises or [])
            ):
                warns.append(
                    f"{where}.name='{op.name}' declares no inputs, no return "
                    f"(output: \"None\"), and raises nothing — nothing to emit. "
                    f"If this captures a policy enforced externally (platform / "
                    f"runtime / deploy), model it as a security_concern (+ "
                    f"mitigation) and/or acceptance_criterion and cover it with a "
                    f"test, not a work_unit"
                )
        # SK-22 (advisory): units name entities the component list doesn't
        # even carry. The subset law is maintained by DERIVATION (Phase 7:
        # traces_data_entities = curated entries UNION the units' touches), so
        # a missing/empty key alongside touching units means the derive step
        # was skipped — the check above can't fire (empty subset base) and the
        # drift would go unseen.
        if touched_ents and not comp_ents:
            warns.append(
                f"{file_label}: components[{i}]='{cid}' has work_units touching "
                f"{len(touched_ents)} entit(ies) but traces_data_entities is "
                f"missing/empty - add the key and complete it to the union of "
                f"its units' touches_entities (Phase 7 derive rule)"
            )
        # Gap-1 (advisory): in an EXECUTABLE-deliverable container (CLI/shell), a
        # single-file component with >=2 work_units and no `entrypoint` unit
        # leaves the file's top-level control flow unowned. Gated on the
        # container archetype AND on the units not being API-routed handlers, so
        # a framework-routed controller (whose web framework owns dispatch) never
        # warns.
        locs = comp.code_location or []
        if (
            container_archetype in _ENTRYPOINT_CONTAINER_ARCHETYPES
            and len(units) >= 2
            and len(locs) == 1
            and _looks_like_file(str(locs[0]))
            and not any((op.kind or "") == "entrypoint" for op in units)
            and not any(op.traces_api_operation for op in units)
        ):
            warns.append(
                f"{file_label}: components[{i}]='{cid}' is one file "
                f"('{locs[0]}') with {len(units)} work_units but no `entrypoint` "
                f"unit — add one to own arg/mode dispatch + step-sequencing + "
                f"setup so downstream task/code build the composition root"
            )
    return errs, warns


def check_component_fr_work_unit_coverage(
    container: ArchContainer,
    file_label: str,
) -> Tuple[List[str], List[str]]:
    """Cross-check #22 — callable-level FR coverage.

    Containment (#21) only checks that each work_unit's implements_requirements is
    a SUBSET of its component's — so a component can claim an FR at the container
    seam yet realize it in NO work_unit, leaving callable-level coverage vacuous
    and the downstream `task` graph with no atomic task that actually builds the
    feature. #22 closes that: for every component that declares at least one
    work_unit, every FR-NNN in its implements_requirements must appear in at least
    one of its own work_units[].implements_requirements.

    Returns (errs, rollup). `errs` block complete (each is one component's FR that
    no work_unit realizes). `rollup` is one advisory line per container naming the
    distinct FRs unreachable through ANY work_unit in the container.

    Waivable per component: a non-empty `work_units_waiver` (e.g. "FR-012 is
    realized purely by composition-root wiring, not a standalone callable") skips
    the component — both its blocking errors and its contribution to the rollup.
    NFR-NNN are intentionally out of scope: they are frequently cross-cutting and
    realized by wiring rather than a named callable. Zero-work_unit components are
    handled by #21, not here.
    """
    errs: List[str] = []
    declared: Set[str] = set()      # FRs any non-waived component claims
    unit_reached: Set[str] = set()  # FRs some work_unit (any non-waived comp) realizes
    for i, comp in enumerate(container.components or []):
        cid = comp.component_id
        units = comp.work_units or []
        if (comp.work_units_waiver or "").strip():
            continue
        comp_frs = {
            str(r).strip().upper() for r in (comp.implements_requirements or [])
            if _FR_PREFIX_RE.match(str(r).strip())
        }
        this_unit_frs: Set[str] = set()
        for op in units:
            for r in op.implements_requirements or []:
                ru = str(r).strip().upper()
                if _FR_PREFIX_RE.match(ru):
                    this_unit_frs.add(ru)
        declared |= comp_frs
        unit_reached |= this_unit_frs
        if not units:
            continue  # zero-work_unit components are #21's job, not #22's
        for fr in sorted(comp_frs - this_unit_frs):
            errs.append(
                f"{file_label}: components[{i}]='{cid}'.implements_requirements '{fr}' "
                f"is realized by none of the component's work_units — push it down to "
                f"the callable that implements it (or record a work_units_waiver if it "
                f"is realized purely by wiring)"
            )
    rollup: List[str] = []
    unreachable = sorted(declared - unit_reached)
    if unreachable:
        rollup.append(
            f"{file_label}: {len(unreachable)} FR(s) unreachable through any work_unit "
            f"in this container: {unreachable}"
        )
    return errs, rollup


def check_work_unit_contracts(
    container: ArchContainer,
    file_label: str,
) -> Tuple[List[str], List[str]]:
    """Cross-check #23 — DEFER-OR-DECLARE interface contract lint.

    Downstream `task` slices one independently-generated atomic task per
    work_unit; those tasks can only compose if each unit's interface is frozen
    somewhere. Two legal states per unit:

      DEFER   — the unit traces a schema-bearing upstream contract
                (`traces_api_operation` is set): inputs/output/raises may stay
                empty; the API request/response schema IS the contract.
      DECLARE — no schema-bearing traced contract: the unit must declare all
                three of `inputs`, `output`, `raises`. Explicit empties count
                as declared (`inputs: []` for a no-arg callable, `raises: []`
                for "raises nothing beyond language defaults", `output:
                "None"` for no return) — what fails is the field being ABSENT,
                i.e. nobody decided.
      FILE    — the unit's `kind` is non-callable (module / content / tooling,
                demo FR-013 v1.30): the deliverable IS a file whose definition
                set / content is the interface, so inputs/output/raises are
                not applicable and the check does not apply.
      FAMILY  — opt-in by declaring `work_unit_family_contracts` (first
                required by the meta-corpus dialect, but ANY project with
                uniform unit families may use it): the unit belongs to a
                declared family, so it inherits that family's shared contract
                and may omit its own inputs/output/raises. A container that
                declares no such block keeps strict per-unit DECLARE.

    Advisory (SK-21, emptiness roll-up): explicit empties are legal per unit,
    but a component where >= 3 callable DECLARE units are >= 80% all-empty
    (`inputs: []` + `output: "None"` + `raises: []`) gets ONE roll-up warning
    — that shape is an emitter filling the fields, not deciding interfaces.
    Complements the per-unit Gap-2 "nothing to emit" advisory in #21: Gap-2
    flags the single policy unit; this flags blanket-stamping across a
    component.

    `signature` is DELIBERATELY optional and unchecked (PLAN2-D1: the corpus
    contracts were authored without signature fields; the schema fills it
    "verbatim only when the signature IS the contract" — codegen renders it
    from inputs/output + the tech stack otherwise). Do not "fix" this by
    adding a signature check.

    Returns (errs, warns). Errs block complete. A component-level
    `work_units_waiver` downgrades that component's contract gaps to warnings
    (consistent with #21/#22).
    """
    errs: List[str] = []
    warns: List[str] = []
    families = container.work_unit_family_contracts or []
    if families:
        known_ids = {c.component_id for c in (container.components or [])}
        for fc in families:
            for mc in fc.member_components or []:
                if mc not in known_ids:
                    warns.append(
                        f"{file_label}: work_unit_family_contracts['{fc.family}']"
                        f".member_components names '{mc}' which is not a component_id "
                        f"in this container"
                    )
    for i, comp in enumerate(container.components or []):
        cid = comp.component_id
        waived = bool((comp.work_units_waiver or "").strip())
        n_declare = 0    # callable DECLARE-case units in this component
        n_all_empty = 0  # ... whose declared contract is entirely empty
        for j, op in enumerate(comp.work_units or []):
            if op.kind in _NON_CALLABLE_WORK_UNIT_KINDS:
                continue  # FILE case — the deliverable is the file itself
            if op.traces_api_operation:
                continue  # DEFER case — contract lives in API__*.yaml
            n_declare += 1
            out = op.output
            if (
                op.inputs == []
                and op.raises == []
                and isinstance(out, str)
                and out.strip().lower() == "none"
            ):
                n_all_empty += 1
            missing = [
                f
                for f, v in (
                    ("inputs", op.inputs),
                    ("output", op.output),
                    ("raises", op.raises),
                )
                if v is None
            ]
            if not missing:
                continue
            if families and _unit_matches_family(comp, op.name, families):
                continue  # FAMILY case — inherits a declared family contract
            msg = (
                f"{file_label}: components[{i}]='{cid}'.work_units[{j}]"
                f"='{op.name}' traces no schema-bearing contract "
                f"(no traces_api_operation) but leaves {missing} undeclared — "
                f"DECLARE the interface contract (explicit empties are fine: "
                f"inputs: [], raises: [], output: \"None\"), or add it to a "
                f"work_unit_family_contracts family, so atomic tasks compose "
                f"against a frozen interface"
            )
            if waived:
                warns.append(msg + " [waived via work_units_waiver]")
            else:
                errs.append(msg)
        # SK-21 (advisory): one legitimately-trivial callable is fine; a
        # component where nearly EVERY callable declares the all-empty
        # contract is an emitter stamping the shape, not deciding interfaces.
        if n_declare >= 3 and n_all_empty / n_declare >= 0.8:
            warns.append(
                f"{file_label}: component '{cid}': {n_all_empty}/{n_declare} "
                f"callable units declare empty contracts (inputs: [], output: "
                f"\"None\", raises: []) - likely an emitter filling the shape, "
                f"not deciding interfaces; verify each contract or declare a "
                f"shared work_unit_family_contracts family"
            )
    return errs, warns


def check_external_edge_rollup(
    arch: Optional[Arch],
    containers: Dict[str, ArchContainer],
) -> List[str]:
    """Cross-check #24 — every container-sourced external edge must be
    reflected in the system edge table.

    A container file's external_edges[] entry (component → other container)
    implies a container-level dependency that downstream test/deploy read from
    ARCH.yaml.edges. If it only exists in the container file, the system graph
    silently under-reports the topology. Requires a system edge with
    from=<this container>, to=<target container>, same type. Blocking.
    """
    errs: List[str] = []
    if arch is None or arch.edges is None:
        return errs
    system_edges = {
        (e.from_, e.to, e.type.value if e.type else None)
        for e in arch.edges
        if e.from_ and e.to
    }
    for name, container in containers.items():
        cid = container.container_id
        for i, e in enumerate(container.external_edges or []):
            if not e.to or not e.type:
                continue  # endpoint/type errors are cross-check #13's job
            target_container, _, _ = e.to.partition("/")
            if target_container == cid:
                continue
            if (cid, target_container, e.type.value) not in system_edges:
                errs.append(
                    f"{name}: external_edges[{i}] ({e.from_} -> {e.to}, "
                    f"{e.type.value}) has no corresponding ARCH.yaml.edges row "
                    f"(from: {cid}, to: {target_container}, type: {e.type.value}) "
                    f"— container-sourced edges must roll up to the system edge "
                    f"table (run `/sdlc:arch -d` or add the edge)"
                )
    return errs


def check_external_via_units(
    containers: Dict[str, ArchContainer],
) -> List[str]:
    """Extension of cross-check #15 — external_edges[].via_unit resolution.

    `via_unit` on an external `calls` edge names the callee's work_unit when
    the target is a sibling container's component with no API between them
    (the intra-system analogue of via_operation_id). It requires the
    `<container_id>/<component_id>` target form and resolves against that
    component's work_units[].name in the target container's on-disk file.
    Unresolvable when the target container is not drilled yet — skipped then
    (the endpoint check still applies).
    """
    errs: List[str] = []
    by_container_id: Dict[str, ArchContainer] = {
        c.container_id: c for c in containers.values()
    }
    for name, container in containers.items():
        for i, e in enumerate(container.external_edges or []):
            unit = getattr(e, "via_unit", None)
            if not unit or not e.to:
                continue
            target_cid, _, target_comp = e.to.partition("/")
            if not target_comp:
                errs.append(
                    f"{name}: external_edges[{i}].via_unit='{unit}' requires a "
                    f"'<container_id>/<component_id>' target, got to='{e.to}'"
                )
                continue
            target = by_container_id.get(target_cid)
            if target is None:
                continue  # target container not drilled — nothing to resolve against
            comp = next(
                (c for c in (target.components or []) if c.component_id == target_comp),
                None,
            )
            if comp is None:
                continue  # unknown component is cross-check #13's job
            known = {str(op.name).strip() for op in (comp.work_units or []) if op.name}
            if known and unit not in known:
                errs.append(
                    f"{name}: external_edges[{i}].via_unit='{unit}' is not a "
                    f"work_units[].name on component '{target_comp}' in "
                    f"container '{target_cid}'"
                )
    return errs


def check_unpinned_call_seams(
    containers: Dict[str, ArchContainer],
) -> List[str]:
    """Cross-check #27 (advisory, Gap-5) — a cross-container `calls` external
    edge with no pinned invocation seam.

    When container A calls container B and neither `via_operation_id` (an API
    endpoint), `via_resource_id` (an API resource), nor `via_unit` (the callee's
    work_unit) is set, the INPUT contract (mode selector + parameterization) is
    unpinned and codegen must guess it — the exact gap where a subprocess/CLI
    seam had only its (exit_code, stdout, stderr) return authored, on the caller
    side. Point `via_unit` at the callee's `entrypoint` work_unit (which pins
    argv/mode IN ⇄ exit-code/stdout/stderr OUT for BOTH sides) and record the
    caller-side binding in `invocation`.
    """
    warns: List[str] = []
    for name, container in containers.items():
        cid = container.container_id
        for i, e in enumerate(container.external_edges or []):
            if not (e.type and e.type.value == "calls" and e.to):
                continue
            target_cid, _, _ = e.to.partition("/")
            if target_cid == cid:
                continue  # intra-container calls are internal_edges' job
            if not (
                e.via_operation_id
                or e.via_resource_id
                or getattr(e, "via_unit", None)
            ):
                warns.append(
                    f"{name}: external_edges[{i}] ({e.from_} -> {e.to}, calls) "
                    f"has no pinned invocation seam (no via_operation_id / "
                    f"via_resource_id / via_unit) — point via_unit at the callee's "
                    f"`entrypoint` work_unit and record the caller binding in "
                    f"`invocation` so the INPUT contract is frozen for both sides"
                )
    return warns


def check_api_consumer_mirror(
    container: ArchContainer,
    file_label: str,
) -> List[str]:
    """Cross-check #26 (advisory) — external `calls` edges with a
    via_resource_id should be mirrored in this container's api_consumers[],
    so codegen reading only the container header still learns which client
    SDKs the container needs.
    """
    warns: List[str] = []
    consumed = {c.resource_id for c in (container.api_consumers or [])}
    for i, e in enumerate(container.external_edges or []):
        if e.type and e.type.value == "calls" and e.via_resource_id:
            if e.via_resource_id not in consumed:
                warns.append(
                    f"{file_label}: external_edges[{i}] calls resource "
                    f"'{e.via_resource_id}' but api_consumers[] does not list it "
                    f"— mirror the consumption so the container header is "
                    f"self-describing"
                )
    return warns


# Path-like tokens in FR text: at least one internal slash, repo-relative,
# not a URL. Trailing punctuation is stripped after matching.
_FR_PATH_TOKEN_RE = re.compile(r"(?<![\w:/])((?:[\w.\-]+/)+[\w.\-*]*)")

# #25 looks for path tokens ONLY inside inline-code (backtick) spans of FR
# text. Bare prose slashes (and/or, PyPI/npm, ID-lists like FR-046/047, analogy
# references) are NOT paths — a literal deliverable path must be marked as code.
# This is the author-controlled 'escape paths, prose is prose' boundary.
_FR_CODE_SPAN_RE = re.compile(r"`+([^`]+?)`+")


def _looks_like_path(token: str) -> bool:
    """A backticked slash-token is a deliverable PATH only if it has path
    shape: it ends with '/' (a directory) or its final segment carries a file
    extension (a '.' in the last segment). This rejects backticked enum
    listings and ID-lists that carry slashes but are not paths — `pass/fail`,
    `high/medium/low`, `tier/effort`, `FR-043/FR-045`. Backticks say 'this is
    literal'; path shape says 'this literal is a path'."""
    if token.endswith("/"):
        return True
    last = token.rstrip("/").rsplit("/", 1)[-1]
    return "." in last


def load_prd_feature_texts(prd_path: Path) -> Dict[str, str]:
    """Return {FR-NNN: full item text} from PRD functional_requirements.
    D2-tolerant: flat `features` list, else legacy must/nice union. Honors
    monorepo mode."""
    out: Dict[str, str] = {}
    if not prd_path.exists():
        return out
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return out
    if not isinstance(raw, dict):
        return out
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo")) if isinstance(metadata, dict) else False

    def _pull(node: dict) -> None:
        fr = node.get("functional_requirements") or {}
        if not isinstance(fr, dict):
            return
        keys = ("features",) if fr.get("features") else ("must_have_features", "nice_to_have_features")
        for key in keys:
            for item in (fr.get(key) or []):
                text = str(item).strip()
                m = _FEATURE_ID_RE.match(text)
                if m:
                    out[m.group(0).upper()] = text

    if monorepo:
        for prod in (raw.get("products") or {}).values():
            if isinstance(prod, dict):
                _pull(prod)
    else:
        _pull(raw)
    return out


def check_fr_deliverable_paths(
    arch: Optional[Arch],
    containers: Dict[str, ArchContainer],
    prd_path: Path,
) -> List[str]:
    """Cross-check #25 (advisory) — every concrete repo path named as inline
    code (backticks) in the text of a CLAIMED FR must fall inside some
    component's code_location.

    Build-time deliverables (a schema layer, repo-root tools/ validators,
    templates/, shipped content packs) are named by FRs but produce no runtime
    callable, so runtime-driven component derivation misses them — and then no
    component/code_location/work_unit exists for `task` to ever schedule
    building them. Scope: FRs that appear in some container's or component's
    implements_requirements (the architecture claims them). Only runs when at
    least one container file declares components.

    Path detection keys on **backtick-delimited** tokens with **path shape**:
    a literal deliverable path is written as inline code AND either ends in `/`
    or has a file extension on its last segment. So bare prose slashes
    (`and/or`, `PyPI/npm`, analogy references) AND backticked non-path tokens
    (enum listings `high/medium/low`, ID-lists `FR-046/047`, field pairs
    `pass/fail`) are both ignored rather than mis-read as paths. Non-blocking:
    the whole check is advisory, so an un-backticked path is a harmless
    false-negative.
    """
    warns: List[str] = []
    if not containers or not any(c.components for c in containers.values()):
        return warns
    feature_texts = load_prd_feature_texts(prd_path)
    if not feature_texts:
        return warns

    claimed: Set[str] = set()
    for c in (arch.containers or []) if arch else []:
        for r in c.implements_requirements or []:
            m = _FEATURE_ID_RE.match(str(r).strip())
            if m:
                claimed.add(m.group(0).upper())
    for container in containers.values():
        for comp in container.components or []:
            for r in comp.implements_requirements or []:
                m = _FEATURE_ID_RE.match(str(r).strip())
                if m:
                    claimed.add(m.group(0).upper())

    locations: List[str] = []
    for container in containers.values():
        for comp in container.components or []:
            for loc in comp.code_location or []:
                locations.append(str(loc).strip())

    def _covered(token: str) -> bool:
        t = token.rstrip("/")
        for loc in locations:
            l = loc.rstrip("/")
            if t == l or t.startswith(l + "/") or l.startswith(t + "/"):
                return True
        return False

    for fr in sorted(claimed):
        text = feature_texts.get(fr)
        if not text:
            continue
        for span in _FR_CODE_SPAN_RE.finditer(text):
            for m in _FR_PATH_TOKEN_RE.finditer(span.group(1)):
                token = m.group(1).rstrip(".,;:)")
                if "://" in token or token.startswith("/"):
                    continue
                if not _looks_like_path(token):
                    continue
                if not _covered(token):
                    warns.append(
                        f"{fr} names backticked path '{token}' but no component's "
                        f"code_location covers it — a build-time deliverable with "
                        f"no owning component means `task` can never schedule "
                        f"building it (add a schema_model/dev_tool/content_asset "
                        f"component or extend an existing code_location)"
                    )
    return warns


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
    via_* (when set) resolves to an upstream artifact.

    Internal edges name the callee's method via `via_unit` (a work_units[].name on
    the edge's `to` component). External edges name a called API endpoint via
    `via_operation_id` (an API operation_id). The shared via_* fields
    (via_resource_id / via_channel_id / via_entity) resolve as before.
    """
    errs: List[str] = []

    # work_unit names declared per component in this container.
    units_by_component: Dict[str, Set[str]] = {}
    for comp in container.components or []:
        names = {str(op.name).strip() for op in (comp.work_units or []) if op.name}
        units_by_component[comp.component_id] = names

    def _check_shared(label: str, e: Any) -> None:
        rid = getattr(e, "via_resource_id", None)
        cid = getattr(e, "via_channel_id", None)
        ent = getattr(e, "via_entity", None)
        if rid and api_resource_ids and rid not in api_resource_ids:
            errs.append(
                f"{file_label}: {label}.via_resource_id='{rid}' "
                f"is not a resource_id in any API__*.yaml"
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
        label = f"internal_edges[{i}]"
        _check_shared(label, e)
        # via_unit → a work_unit name on the edge's `to` component (which lives in
        # this container). Only checkable when the `to` component is known here.
        unit = getattr(e, "via_unit", None)
        if unit and e.to and e.to in units_by_component:
            known = units_by_component[e.to]
            if known and unit not in known:
                errs.append(
                    f"{file_label}: {label}.via_unit='{unit}' is not a "
                    f"work_units[].name on component '{e.to}'"
                )
    for i, e in enumerate(container.external_edges or []):
        label = f"external_edges[{i}]"
        _check_shared(label, e)
        # via_operation_id → an API endpoint on the called (external) container.
        oid = getattr(e, "via_operation_id", None)
        if oid and api_operation_ids and oid not in api_operation_ids:
            errs.append(
                f"{file_label}: {label}.via_operation_id='{oid}' "
                f"is not an operation_id in any API__*.yaml"
            )
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
    data_enum_names = load_data_enum_names(docs_dir / "DATA-MODEL.yaml")
    prd_path = docs_dir / "PRD.yaml"
    prd_features = load_prd_features(prd_path)
    prd_families = load_prd_id_families(prd_path)

    # 4) Required fields (with new external-container exemption)
    missing_arch = check_arch_required(arch)
    missing_containers: List[str] = []
    edge_errs_containers: List[str] = []
    consistency_errs: List[str] = []
    component_trace_errs: List[str] = []
    container_via_errs: List[str] = []
    deployment_compat_errs: List[str] = []
    code_location_warnings: List[str] = []
    component_op_errs: List[str] = []
    component_op_warnings: List[str] = []
    fr_wu_errs: List[str] = []
    fr_wu_rollup: List[str] = []
    contract_errs: List[str] = []
    contract_warns: List[str] = []
    api_mirror_warns: List[str] = []
    warning_id_errs: List[str] = check_warning_ids(arch.arch_warnings, "arch_warnings")
    id_format_errs: List[str] = check_arch_id_formats(arch)
    for name, c in containers.items():
        missing_containers.extend(check_container_required(c, name, arch))
        edge_errs_containers.extend(check_container_edges(c, name, arch))
        consistency_errs.extend(check_container_self_consistency(c, arch, name))
        code_location_warnings.extend(check_component_code_location(c, name))
        op_errs, op_warns = check_component_work_units(
            c, name, api_operation_ids, data_entity_names
        )
        component_op_errs.extend(op_errs)
        component_op_warnings.extend(op_warns)
        fr_errs, fr_roll = check_component_fr_work_unit_coverage(c, name)
        fr_wu_errs.extend(fr_errs)
        fr_wu_rollup.extend(fr_roll)
        ct_errs, ct_warns = check_work_unit_contracts(c, name)
        contract_errs.extend(ct_errs)
        contract_warns.extend(ct_warns)
        api_mirror_warns.extend(check_api_consumer_mirror(c, name))
        component_trace_errs.extend(
            check_component_traces(
                c, arch, name,
                api_ids_set, api_operation_ids,
                ux_ids_set, data_entity_names,
                data_enum_names,
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
        arch, containers, prd_families["FR"], prd_families["WKF"],
        prd_families.get("NFR"),
    )
    bad_arch_edges = check_arch_edges(arch)
    arch_via_errs = check_edge_via_fields_arch(
        arch, api_ids_set, api_channel_ids, data_entity_names
    )
    file_path_errs = check_file_path_integrity(arch, docs_dir)
    external_warnings = check_external_container_files(arch, containers)
    upstream_warnings = check_upstream_status_warnings(docs_dir)
    rollup_errs = check_external_edge_rollup(arch, containers)
    container_via_errs.extend(check_external_via_units(containers))
    unpinned_seam_warns = check_unpinned_call_seams(containers)
    deliverable_path_warns = check_fr_deliverable_paths(arch, containers, prd_path)

    status = arch.metadata.status
    n_containers = len(containers)

    # New convention-driven problem categories (printed via a dedicated
    # helper so the legacy _print_problems signature stays stable).
    extra_problems: List[Tuple[str, List[str]]] = [
        ("arch_warnings / container warnings not in WRN-NNN format", warning_id_errs),
        ("PRD trace ID-format error(s) (expected FR-NNN / WKF-NNN)", id_format_errs),
        ("PRD FR-NNN feature(s) implemented by no container", uncovered_features),
        ("implements_requirements / traces_prd_workflows resolution error(s)", prd_trace_errs),
        ("component work_unit integrity error(s) (cross-check 21)", component_op_errs),
        ("component FR->work_unit coverage error(s) (cross-check 22)", fr_wu_errs),
        ("work_unit DEFER-OR-DECLARE contract error(s) (cross-check 23)", contract_errs),
        ("container->system edge roll-up error(s) (cross-check 24)", rollup_errs),
    ]

    titled_warnings: List[Tuple[str, List[str]]] = [
        ("work_unit contract advisorie(s) [waived gaps / emptiness roll-up]", contract_warns),
        ("FR-named deliverable path(s) outside every code_location (cross-check 25)", deliverable_path_warns),
        ("external calls edge(s) not mirrored in api_consumers (cross-check 26)", api_mirror_warns),
        ("cross-container calls edge(s) with no pinned invocation seam (cross-check 27)", unpinned_seam_warns),
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
        _print_warnings(external_warnings, upstream_warnings, code_location_warnings, component_op_warnings, fr_wu_rollup, titled_warnings)
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
        _print_warnings(external_warnings, upstream_warnings, code_location_warnings, component_op_warnings, fr_wu_rollup, titled_warnings)
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
    _print_warnings(external_warnings, upstream_warnings, code_location_warnings, component_op_warnings, fr_wu_rollup, titled_warnings)
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


def _print_warnings(
    external_warnings: List[str],
    upstream_warnings: List[str],
    code_location_warnings: Optional[List[str]] = None,
    operation_warnings: Optional[List[str]] = None,
    fr_work_unit_rollup: Optional[List[str]] = None,
    titled: Optional[List[Tuple[str, List[str]]]] = None,
) -> None:
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
    if code_location_warnings:
        print()
        print(f"WARNINGS ({len(code_location_warnings)} component(s) without code_location):")
        for w in code_location_warnings:
            print(f"  - {w}")
    if operation_warnings:
        print()
        print(f"WARNINGS ({len(operation_warnings)} component work_units advisorie(s) [waivers / Gap-1 / Gap-2 / traces derive]):")
        for w in operation_warnings:
            print(f"  - {w}")
    if fr_work_unit_rollup:
        print()
        print(f"WARNINGS ({len(fr_work_unit_rollup)} container(s) with FR(s) unreachable through any work_unit):")
        for w in fr_work_unit_rollup:
            print(f"  - {w}")
    for title, items in titled or []:
        if items:
            print()
            print(f"WARNINGS ({len(items)} {title}):")
            for w in items:
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
