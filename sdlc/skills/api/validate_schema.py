"""Validate API.yaml + every API__*.yaml against the canonical sdlc-api schema,
and run feature/surface coverage + DATA entity-link checks + ID-prefix format
checks.

Run from the project root:

    python sdlc/skills/api/validate_schema.py
    python sdlc/skills/api/validate_schema.py --path docs/API.yaml
    python sdlc/skills/api/validate_schema.py --docs-dir other/docs

Validates:
    1. docs/API.yaml (or --path) — global API contract.
    2. Every docs/API__*.yaml sibling — one per resource.
    3. ID-prefix format checks:
       - WRN-NNN on every api_warnings entry.
       - OPR-NNN on every endpoint's `id` field (when present).
       - FR-NNN on every traces_prd_features entry and every
         non_api_features entry.
       - SCR-NNN on every traces_ux_surfaces entry.
       - WKF-NNN on every traces_prd_workflows entry (when present).
       Hard error in status:complete.
    4. Coverage checks (all skipped when api_kind: none):
       - Feature coverage: every PRD must_have_features FR-NNN appears in
         some resource's traces_prd_features OR in API.yaml.non_api_features.
       - Surface coverage: every data-bearing UX surface (matched by the
         SCR-NNN id) appears in some resource's traces_ux_surfaces.
       - Entity-link: every resource's primary_entity (PascalCase entity
         name) exists in DATA-MODEL.yaml.entities.

OpenAPI 3.1 deep-validation of embedded operations is OUT of scope for v1
(see references/openapi-embedding.md). The Pydantic models here enforce the
shape (required keys: method, path, responses) but do not call out to an
OpenAPI validator. Downstream codegen agents may re-validate.

Exit codes:
    0 — schema valid; either status='complete' (with all required fields
        filled AND all enabled checks passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but any coverage check
        failed.
    2 — could not read or parse one of the files (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

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
# Enums — kept in lockstep with API.schema.yaml and API__RESOURCE.schema.yaml
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class ApiKind(str, Enum):
    rest = "rest"
    graphql = "graphql"
    grpc = "grpc"
    mixed = "mixed"
    none = "none"


class TransportStyle(str, Enum):
    rest = "rest"
    graphql = "graphql"
    grpc = "grpc"
    websocket = "websocket"
    server_sent_events = "server_sent_events"
    webhooks_out = "webhooks_out"


class VersioningStrategy(str, Enum):
    path = "path"
    header = "header"
    content_type = "content_type"
    none = "none"


class AuthScheme(str, Enum):
    api_key = "api_key"
    bearer_jwt = "bearer_jwt"
    oauth2 = "oauth2"
    session_cookie = "session_cookie"
    mtls = "mtls"
    none = "none"


class DefaultVisibility(str, Enum):
    public = "public"
    authenticated = "authenticated"
    mixed = "mixed"


class ErrorEnvelope(str, Enum):
    rfc7807 = "rfc7807"
    custom = "custom"


class PaginationStrategy(str, Enum):
    offset = "offset"
    cursor = "cursor"
    none = "none"


class RateLimitScope(str, Enum):
    per_ip = "per_ip"
    per_user = "per_user"
    per_key = "per_key"
    glob = "global"  # python keyword clash; serialized value is "global"

    @classmethod
    def _missing_(cls, value: object):
        if value == "global":
            return cls.glob
        return None


class DeliveryGuarantee(str, Enum):
    at_most_once = "at_most_once"
    at_least_once = "at_least_once"
    exactly_once = "exactly_once"


class ResourceStatus(str, Enum):
    defined = "defined"
    draft = "draft"
    confirmed = "confirmed"


# Surface types treated as "data-bearing" for surface-coverage purposes.
# Mirrors the SurfaceType enum in sdlc-ux but excludes purely-visual states.
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
# API.yaml — top-level theme models
# =============================================================================

_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _ThemeBase(BaseModel):
    model_config = _BASE_CONFIG


class Versioning(_ThemeBase):
    strategy: Optional[VersioningStrategy] = None
    strategy_confidence: Optional[Confidence] = None
    current_version: Optional[str] = None
    deprecation_policy: Optional[str] = None


class Auth(_ThemeBase):
    schemes: Optional[List[AuthScheme]] = None
    schemes_confidence: Optional[Confidence] = None
    roles: Optional[List[str]] = None
    scopes: Optional[List[str]] = None
    default_visibility: Optional[DefaultVisibility] = None
    default_visibility_confidence: Optional[Confidence] = None


class ErrorCode(_ThemeBase):
    code: Optional[str] = None
    http_status: Optional[int] = None
    description: Optional[str] = None


class Errors(_ThemeBase):
    envelope: Optional[ErrorEnvelope] = None
    envelope_confidence: Optional[Confidence] = None
    localisation: Optional[bool] = None
    retry_semantics: Optional[str] = None
    error_codes: Optional[List[ErrorCode]] = None


class Pagination(_ThemeBase):
    strategy: Optional[PaginationStrategy] = None
    strategy_confidence: Optional[Confidence] = None
    default_page_size: Optional[int] = None
    max_page_size: Optional[int] = None
    stable_sort_field: Optional[str] = None


class Idempotency(_ThemeBase):
    idempotent_methods: Optional[List[str]] = None
    header: Optional[str] = None
    cache_window: Optional[str] = None


class RateLimiting(_ThemeBase):
    scopes: Optional[List[RateLimitScope]] = None
    burst: Optional[str] = None
    sustained: Optional[str] = None
    response: Optional[str] = None


class EventChannel(_ThemeBase):
    channel_id: Optional[str] = None
    transport: Optional[str] = None
    direction: Optional[str] = None
    payload_schema_ref: Optional[str] = None
    auth_ref: Optional[str] = None


class Events(_ThemeBase):
    channels: Optional[List[EventChannel]] = None
    payload_conventions: Optional[str] = None
    delivery_guarantees: Optional[DeliveryGuarantee] = None
    consumer_auth: Optional[str] = None


class ExternalDependency(_ThemeBase):
    name: Optional[str] = None
    auth: Optional[str] = None
    rate_limit: Optional[str] = None
    retry_policy: Optional[str] = None
    docs_url: Optional[str] = None


class SdkAndClients(_ThemeBase):
    generated_sdks: Optional[str] = None
    client_languages: Optional[List[str]] = None
    distribution: Optional[str] = None


class ResourceInventoryItem(_ThemeBase):
    resource_id: Optional[str] = None
    base_path: Optional[str] = None
    status: Optional[ResourceStatus] = None
    file_path: Optional[str] = None
    primary_entity: Optional[str] = None
    traces_prd_features: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    traces_prd_workflows: Optional[List[str]] = None


# -----------------------------------------------------------------------------
# Top-level API models
# -----------------------------------------------------------------------------


class APIMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_version: str
    last_updated: str
    generated_by: str = "sdlc-api"
    session_id: str
    monorepo: bool = False
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None
    # One entry per upstream artifact consumed, each a mapping
    # {file, session_id, last_updated, sha256}. Type-checked as a list of
    # mappings only — see CLAUDE.md §7 "Upstream-change re-invocation".
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class APIProduct(_ThemeBase):
    """One product's API contract in monorepo mode."""

    api_kind: Optional[ApiKind] = None
    api_kind_confidence: Optional[Confidence] = None
    rationale: Optional[str] = None

    transport_styles: Optional[List[TransportStyle]] = None
    transport_styles_confidence: Optional[Confidence] = None

    versioning: Optional[Versioning] = None
    auth: Optional[Auth] = None
    errors: Optional[Errors] = None
    pagination: Optional[Pagination] = None
    idempotency: Optional[Idempotency] = None
    rate_limiting: Optional[RateLimiting] = None
    events: Optional[Events] = None
    external_dependencies: Optional[List[ExternalDependency]] = None
    sdk_and_clients: Optional[SdkAndClients] = None
    shared_schemas: Optional[Dict[str, Any]] = None
    resource_inventory: Optional[List[ResourceInventoryItem]] = None
    non_api_features: Optional[List[str]] = None


class API(BaseModel):
    """Top-level API.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: APIMetadata
    api_warnings: List[str] = Field(default_factory=list)

    # Single-product mode — all theme blocks live at top level
    api_kind: Optional[ApiKind] = None
    api_kind_confidence: Optional[Confidence] = None
    rationale: Optional[str] = None

    transport_styles: Optional[List[TransportStyle]] = None
    transport_styles_confidence: Optional[Confidence] = None

    versioning: Optional[Versioning] = None
    auth: Optional[Auth] = None
    errors: Optional[Errors] = None
    pagination: Optional[Pagination] = None
    idempotency: Optional[Idempotency] = None
    rate_limiting: Optional[RateLimiting] = None
    events: Optional[Events] = None
    external_dependencies: Optional[List[ExternalDependency]] = None
    sdk_and_clients: Optional[SdkAndClients] = None
    shared_schemas: Optional[Dict[str, Any]] = None
    resource_inventory: Optional[List[ResourceInventoryItem]] = None
    non_api_features: Optional[List[str]] = None

    # Multi-product mode
    products: Optional[Dict[str, APIProduct]] = None

    @model_validator(mode="after")
    def _check_mode(self) -> "API":
        single_themes = [
            self.api_kind,
            self.transport_styles,
            self.versioning,
            self.auth,
            self.errors,
            self.pagination,
            self.idempotency,
            self.rate_limiting,
            self.events,
            self.external_dependencies,
            self.sdk_and_clients,
            self.shared_schemas,
            self.resource_inventory,
        ]
        any_single = any(t is not None for t in single_themes)

        if self.metadata.monorepo:
            if not self.products:
                raise ValueError("metadata.monorepo is true but `products` is missing or empty")
            if any_single:
                raise ValueError(
                    "monorepo mode set but top-level theme blocks are present; "
                    "in monorepo mode every theme must live under `products.<slug>`"
                )
        else:
            if self.products:
                raise ValueError(
                    "`products` is set but metadata.monorepo is false; "
                    "either set monorepo: true or move themes to top level"
                )
        return self


# =============================================================================
# API__<resource>.yaml — per-resource model
# =============================================================================


class ResourceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_resource_version: str
    last_updated: str
    generated_by: str = "sdlc-api"
    session_id: str
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None


class Endpoint(_ThemeBase):
    """One API endpoint = one (method, path) operation.

    The model is intentionally permissive on OpenAPI sub-shape. Deep OpenAPI
    3.1 conformance is out of scope for v1 — see references/openapi-embedding.md.
    """

    id: Optional[str] = None  # OPR-NNN stable id (SDLC sibling; stripped before OpenAPI round-trip)
    operation_id: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    parameters: Optional[List[Any]] = None
    requestBody: Optional[Any] = None
    responses: Optional[Dict[str, Any]] = None
    security: Optional[List[Any]] = None
    # SDLC siblings:
    idempotent: Optional[bool] = None
    rate_limit_override: Optional[str] = None
    auth_override: Optional[str] = None


class APIResource(BaseModel):
    """Top-level per-resource document."""

    model_config = ConfigDict(extra="allow")

    metadata: ResourceMetadata

    resource_id: Optional[str] = None
    base_path: Optional[str] = None
    primary_entity: Optional[str] = None
    traces_prd_features: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    traces_prd_workflows: Optional[List[str]] = None
    endpoints: Optional[List[Endpoint]] = None
    schemas: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


# =============================================================================
# Required-field checks
# =============================================================================

# Required when api_kind != none. (For api_kind == none, only api_kind and
# rationale are required.)
API_REQUIRED_PATHS: List[str] = [
    "api_kind",
    "transport_styles",
    "versioning.strategy",
    "versioning.current_version",
    "auth.schemes",
    "auth.default_visibility",
    "errors.envelope",
    "pagination.strategy",
    "idempotency.idempotent_methods",
    "rate_limiting.scopes",
    "resource_inventory",
]

# Always required:
API_REQUIRED_PATHS_ALWAYS: List[str] = ["api_kind"]

# Conditionally required (api_kind == none): rationale
API_NONE_REQUIRED_PATHS: List[str] = ["api_kind", "rationale"]

# Per-resource required fields:
RESOURCE_REQUIRED_PATHS: List[str] = [
    "resource_id",
    "base_path",
    "traces_prd_features",
    "traces_ux_surfaces",
    "endpoints",
]

# Per-endpoint required keys for status=complete:
ENDPOINT_REQUIRED_KEYS: List[str] = ["id", "operation_id", "method", "path", "summary", "responses"]


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


def check_api_required(api: API) -> List[str]:
    """Return list of missing required API.yaml field paths.

    Behaviour depends on api_kind:
      - api_kind == none: only api_kind + rationale required.
      - api_kind != none: full API_REQUIRED_PATHS list required.
    """
    missing: List[str] = []

    def _check(scope_label: str, root: object) -> None:
        kind = getattr(root, "api_kind", None)
        if kind == ApiKind.none:
            for path in API_NONE_REQUIRED_PATHS:
                if _is_empty(_get_dotted(root, path)):
                    missing.append(f"{scope_label}{path}")
            return
        for path in API_REQUIRED_PATHS:
            if _is_empty(_get_dotted(root, path)):
                missing.append(f"{scope_label}{path}")

    if api.metadata.monorepo and api.products:
        for slug, product in api.products.items():
            _check(f"products.{slug}.", product)
    else:
        _check("", api)
    return missing


def check_resource_required(resource: APIResource, file_label: str) -> List[str]:
    """Return list of missing required fields for one resource yaml.

    Also walks endpoints[] and flags any endpoint missing the canonical
    OpenAPI keys (operation_id, method, path, summary, responses).
    """
    missing: List[str] = []
    for path in RESOURCE_REQUIRED_PATHS:
        if _is_empty(_get_dotted(resource, path)):
            missing.append(f"{file_label}: {path}")

    if resource.endpoints:
        for i, ep in enumerate(resource.endpoints):
            for key in ENDPOINT_REQUIRED_KEYS:
                if _is_empty(getattr(ep, key, None)):
                    missing.append(f"{file_label}: endpoints[{i}].{key}")
    return missing


# =============================================================================
# Coverage checks
# =============================================================================


_FEATURE_ID_RE = re.compile(r"^FR-\d+", re.IGNORECASE)
_WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
_FR_PREFIX_RE = re.compile(r"^FR-\d{3,}$", re.IGNORECASE)
_SCR_PREFIX_RE = re.compile(r"^SCR-\d{3,}$", re.IGNORECASE)
_WKF_PREFIX_RE = re.compile(r"^WKF-\d{3,}$", re.IGNORECASE)
_OPR_PREFIX_RE = re.compile(r"^OPR-\d{3,}$", re.IGNORECASE)


def check_warning_ids(warnings: List[str], label: str) -> List[str]:
    """Every warnings entry must match WRN-NNN: <message>."""
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


def check_api_id_formats(api: API) -> List[str]:
    """Enforce <PREFIX>-NNN format on every trace list + non_api_features."""
    errs: List[str] = []

    def _check_root(scope: str, root: object) -> None:
        non_api = getattr(root, "non_api_features", None)
        errs.extend(_check_id_prefix(non_api, _FR_PREFIX_RE,
                                     f"{scope}non_api_features (expected FR-NNN)"))
        inv = getattr(root, "resource_inventory", None) or []
        for i, item in enumerate(inv):
            errs.extend(_check_id_prefix(
                getattr(item, "traces_prd_features", None), _FR_PREFIX_RE,
                f"{scope}resource_inventory[{i}].traces_prd_features (expected FR-NNN)"))
            errs.extend(_check_id_prefix(
                getattr(item, "traces_ux_surfaces", None), _SCR_PREFIX_RE,
                f"{scope}resource_inventory[{i}].traces_ux_surfaces (expected SCR-NNN)"))
            errs.extend(_check_id_prefix(
                getattr(item, "traces_prd_workflows", None), _WKF_PREFIX_RE,
                f"{scope}resource_inventory[{i}].traces_prd_workflows (expected WKF-NNN)"))

    if api.metadata.monorepo and api.products:
        for slug, product in api.products.items():
            _check_root(f"products.{slug}.", product)
    else:
        _check_root("", api)
    return errs


def check_resource_id_formats(resource: APIResource, label: str) -> List[str]:
    """Enforce ID prefix format on per-resource yaml lists and endpoint ids."""
    errs: List[str] = []
    errs.extend(_check_id_prefix(
        resource.traces_prd_features, _FR_PREFIX_RE,
        f"{label}: traces_prd_features (expected FR-NNN)"))
    errs.extend(_check_id_prefix(
        resource.traces_ux_surfaces, _SCR_PREFIX_RE,
        f"{label}: traces_ux_surfaces (expected SCR-NNN)"))
    errs.extend(_check_id_prefix(
        resource.traces_prd_workflows, _WKF_PREFIX_RE,
        f"{label}: traces_prd_workflows (expected WKF-NNN)"))
    # OPR ids on endpoints. `id` may be unset on draft endpoints; only check
    # values that are present.
    for i, ep in enumerate(resource.endpoints or []):
        ep_id = getattr(ep, "id", None)
        if ep_id is None:
            continue
        if not isinstance(ep_id, str) or not _OPR_PREFIX_RE.match(ep_id.strip()):
            errs.append(
                f"{label}: endpoints[{i}].id: '{ep_id}' must match OPR-NNN format"
            )
    return errs


def load_prd_must_have_features(prd_path: Path) -> List[str]:
    """Return list of FR-NNN strings from PRD.functional_requirements.must_have_features.

    Each must_have_features entry typically starts with "FR-NNN: <description>".
    We extract just the FR-NNN prefix for matching.
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
    monorepo = bool(metadata.get("monorepo"))

    def _pull(node: dict) -> None:
        fr = node.get("functional_requirements") or {}
        mhf = fr.get("must_have_features") if isinstance(fr, dict) else None
        if isinstance(mhf, list):
            for item in mhf:
                s = str(item).strip()
                m = _FEATURE_ID_RE.match(s)
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


def load_ux_data_bearing_surfaces(docs_dir: Path) -> List[str]:
    """Return list of UX surface SCR-NNN ids whose surface_type is data-bearing.

    Reads every docs/UX__*.yaml file. Returns each surface's stable `id`
    field (SCR-NNN). Surfaces without a recognized type are treated as
    data-bearing (conservative — better a false positive in coverage than
    a silent miss).

    For backward compatibility, falls back to the per-surface
    `surface_id` slug ONLY when the file pre-dates the SCR-NNN convention
    (i.e. `id` is missing). When that fallback fires, the agent should
    propose migrating the surface file.
    """
    surfaces: List[str] = []
    for path in sorted(docs_dir.glob("UX__*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(raw, dict):
            continue
        # Prefer the SCR-NNN stable id; fall back to surface_id slug.
        scr_id = raw.get("id")
        slug = raw.get("surface_id")
        stype = raw.get("surface_type")
        chosen = scr_id if isinstance(scr_id, str) and scr_id.strip() else slug
        if not chosen:
            continue
        if stype is None or stype in DATA_BEARING_SURFACE_TYPES:
            surfaces.append(str(chosen))
    return surfaces


def load_data_model_entities(data_path: Path) -> Optional[List[str]]:
    """Return list of DATA-MODEL entity names, or None if the file is absent.

    The canonical shape (produced by sdlc-data) is a dict keyed by
    PascalCase entity name:

      entities:
        User: { ... }
        Order: { ... }

    A list-of-`{name: ...}` shape is also accepted for resilience against
    older or hand-written fixtures, but the dict shape is the source of
    truth.
    """
    if not data_path.exists():
        return None
    try:
        raw = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None

    entities = raw.get("entities")
    if isinstance(entities, dict):
        return [str(k) for k in entities.keys()]
    if isinstance(entities, list):
        names: List[str] = []
        for item in entities:
            if isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
            elif isinstance(item, str):
                names.append(item)
        return names
    return []


def collect_resource_traces(
    api: API, resources: Dict[str, APIResource]
) -> tuple[List[str], List[str], List[Optional[str]]]:
    """Walk both the inventory and the per-resource files; aggregate traces.

    Returns (all_feature_traces, all_surface_traces, all_primary_entities).
    """
    feats: List[str] = []
    surfs: List[str] = []
    ents: List[Optional[str]] = []

    inventory: List[ResourceInventoryItem] = []
    if api.metadata.monorepo and api.products:
        for prod in api.products.values():
            inventory.extend(prod.resource_inventory or [])
    else:
        inventory.extend(api.resource_inventory or [])

    for item in inventory:
        if item.traces_prd_features:
            feats.extend(item.traces_prd_features)
        if item.traces_ux_surfaces:
            surfs.extend(item.traces_ux_surfaces)
        if item.primary_entity:
            ents.append(item.primary_entity)

    for res in resources.values():
        if res.traces_prd_features:
            feats.extend(res.traces_prd_features)
        if res.traces_ux_surfaces:
            surfs.extend(res.traces_ux_surfaces)
        if res.primary_entity:
            ents.append(res.primary_entity)

    return feats, surfs, ents


def check_feature_coverage(
    prd_features: List[str],
    traced_features: List[str],
    non_api_features: Optional[List[str]],
) -> List[str]:
    """Return list of FR-NNN IDs that are neither traced nor opted out."""
    traced_norm = {
        _FEATURE_ID_RE.match(str(f).strip()).group(0).upper()
        for f in traced_features
        if _FEATURE_ID_RE.match(str(f).strip())
    }
    opt_out: set = set()
    if non_api_features:
        for f in non_api_features:
            m = _FEATURE_ID_RE.match(str(f).strip())
            if m:
                opt_out.add(m.group(0).upper())
    return [f for f in prd_features if f.upper() not in traced_norm and f.upper() not in opt_out]


def check_surface_coverage(ux_surfaces: List[str], traced_surfaces: List[str]) -> List[str]:
    traced_set = {s.strip() for s in traced_surfaces}
    return [s for s in ux_surfaces if s.strip() not in traced_set]


def check_entity_links(
    primary_entities: List[Optional[str]], data_entities: Optional[List[str]]
) -> List[str]:
    """Return list of primary_entity names that don't exist in DATA-MODEL.

    If data_entities is None (DATA-MODEL.yaml missing), this check is
    skipped — return [].
    """
    if data_entities is None:
        return []
    data_set = set(data_entities)
    missing: List[str] = []
    for ent in primary_entities:
        if ent and ent not in data_set:
            missing.append(ent)
    return missing


# =============================================================================
# File loading / validation orchestration
# =============================================================================


def _load_yaml(path: Path) -> tuple[Any, Optional[str]]:
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


def discover_resource_files(api_path: Path) -> List[Path]:
    """Return sorted list of docs/API__*.yaml siblings of api_path."""
    parent = api_path.parent
    return sorted(parent.glob("API__*.yaml"))


def validate_all(api_path: Path) -> int:
    """Validate API.yaml, all API__*.yaml siblings, and run coverage checks."""

    # 1) API.yaml
    raw, err = _load_yaml(api_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    try:
        api = API.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] API.yaml FAILED schema validation ({api_path})\n")
        print("Errors:")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    # 2) Each API__<resource>.yaml
    resource_files = discover_resource_files(api_path)
    resources: Dict[str, APIResource] = {}
    for rp in resource_files:
        r_raw, r_err = _load_yaml(rp)
        if r_err:
            print(f"ERROR: {r_err}", file=sys.stderr)
            return 2
        try:
            resource = APIResource.model_validate(r_raw)
        except ValidationError as e:
            print(f"[FAIL] {rp.name} FAILED schema validation\n")
            for line in _format_pydantic_errors(e):
                print(f"  - {line}")
            return 1
        resources[rp.name] = resource

    # 3) Required-field checks
    missing_api = check_api_required(api)
    missing_resource: List[str] = []
    for name, resource in resources.items():
        missing_resource.extend(check_resource_required(resource, name))

    # 3b) ID-prefix format checks (WRN on warnings, FR/SCR/WKF on traces, OPR on endpoint ids)
    warning_id_errs = check_warning_ids(api.api_warnings or [], "api_warnings")
    id_format_errs = check_api_id_formats(api)
    for name, resource in resources.items():
        id_format_errs.extend(check_resource_id_formats(resource, name))

    # 4) Coverage + entity-link checks — skipped when api_kind: none
    docs_dir = api_path.parent
    prd_path = docs_dir / "PRD.yaml"
    data_path = docs_dir / "DATA-MODEL.yaml"

    is_none_kind = api.api_kind == ApiKind.none or (
        api.metadata.monorepo
        and api.products
        and all((p.api_kind == ApiKind.none) for p in api.products.values())
    )

    if is_none_kind:
        prd_features: List[str] = []
        ux_surfaces: List[str] = []
        data_entities: Optional[List[str]] = []
        uncovered_features: List[str] = []
        uncovered_surfaces: List[str] = []
        bad_entities: List[str] = []
    else:
        prd_features = load_prd_must_have_features(prd_path)
        ux_surfaces = load_ux_data_bearing_surfaces(docs_dir)
        data_entities = load_data_model_entities(data_path)

        traced_feats, traced_surfs, primary_ents = collect_resource_traces(api, resources)
        non_api = api.non_api_features
        if api.metadata.monorepo and api.products:
            non_api = []
            for prod in api.products.values():
                if prod.non_api_features:
                    non_api.extend(prod.non_api_features)
        uncovered_features = check_feature_coverage(prd_features, traced_feats, non_api)
        uncovered_surfaces = check_surface_coverage(ux_surfaces, traced_surfs)
        bad_entities = check_entity_links(primary_ents, data_entities)

    status = api.metadata.status
    n_resources = len(resources)

    # 5) Reporting
    if status == "complete":
        problems = bool(
            missing_api
            or missing_resource
            or warning_id_errs
            or id_format_errs
            or uncovered_features
            or uncovered_surfaces
            or bad_entities
        )
        if problems:
            print(f"[FAIL] API.yaml claims status 'complete' but has errors ({api_path})\n")
            if missing_api:
                print(f"{len(missing_api)} required API.yaml field(s) missing:")
                for m in missing_api:
                    print(f"  - {m}")
                print()
            if missing_resource:
                print(f"{len(missing_resource)} required resource field(s) missing:")
                for m in missing_resource:
                    print(f"  - {m}")
                print()
            if warning_id_errs:
                print(f"{len(warning_id_errs)} api_warnings ID-format error(s):")
                for e_ in warning_id_errs:
                    print(f"  - {e_}")
                print()
            if id_format_errs:
                print(f"{len(id_format_errs)} ID-format error(s) (FR/SCR/WKF/OPR):")
                for e_ in id_format_errs:
                    print(f"  - {e_}")
                print()
            if uncovered_features:
                print(
                    f"{len(uncovered_features)} PRD FR-NNN feature(s) with no resource trace "
                    f"(and not in non_api_features):"
                )
                for f in uncovered_features:
                    print(f"  - {f}")
                print()
            if uncovered_surfaces:
                print(f"{len(uncovered_surfaces)} UX surface(s) with no endpoint trace:")
                for s in uncovered_surfaces:
                    print(f"  - {s}")
                print()
            if bad_entities:
                print(f"{len(bad_entities)} primary_entity reference(s) not in DATA-MODEL:")
                for e_ in bad_entities:
                    print(f"  - {e_}")
            return 1
        if is_none_kind:
            print(
                f"[OK] API.yaml is valid and complete (api_kind: none) ({api_path}); "
                f"coverage checks skipped."
            )
        else:
            data_note = (
                f"{len(data_entities)} DATA entit(y/ies)"
                if data_entities is not None
                else "DATA-MODEL.yaml missing — entity-link check skipped"
            )
            print(
                f"[OK] API.yaml is valid and complete ({api_path}); "
                f"{n_resources} resource file(s); "
                f"{len(prd_features)} PRD FR-NNN feature(s) all covered; "
                f"{len(ux_surfaces)} data-bearing UX surface(s) all served; "
                f"{data_note}."
            )
        return 0

    # status == "draft"
    if is_none_kind:
        print(
            f"[DRAFT] API.yaml is a draft (api_kind: none) ({api_path}); "
            f"coverage checks skipped."
        )
    else:
        data_note = (
            f"{len(data_entities)} DATA entit(y/ies) found"
            if data_entities is not None
            else "DATA-MODEL.yaml missing"
        )
        print(
            f"[DRAFT] API.yaml is a draft ({api_path}); "
            f"{n_resources} resource file(s); "
            f"{len(prd_features)} PRD FR-NNN feature(s) discovered; "
            f"{len(ux_surfaces)} data-bearing UX surface(s) discovered; "
            f"{data_note}."
        )
    if missing_api:
        print(f"\n{len(missing_api)} required API.yaml field(s) missing:")
        for m in missing_api:
            print(f"  - {m}")
    if missing_resource:
        print(f"\n{len(missing_resource)} required resource field(s) missing:")
        for m in missing_resource:
            print(f"  - {m}")
    if warning_id_errs:
        print(f"\n{len(warning_id_errs)} api_warnings ID-format error(s):")
        for e_ in warning_id_errs:
            print(f"  - {e_}")
    if id_format_errs:
        print(f"\n{len(id_format_errs)} ID-format error(s) (FR/SCR/WKF/OPR):")
        for e_ in id_format_errs:
            print(f"  - {e_}")
    if uncovered_features:
        print(f"\n{len(uncovered_features)} PRD FR-NNN feature(s) with no resource trace:")
        for f in uncovered_features:
            print(f"  - {f}")
    if uncovered_surfaces:
        print(f"\n{len(uncovered_surfaces)} UX surface(s) with no endpoint trace:")
        for s in uncovered_surfaces:
            print(f"  - {s}")
    if bad_entities:
        print(f"\n{len(bad_entities)} primary_entity reference(s) not in DATA-MODEL:")
        for e_ in bad_entities:
            print(f"  - {e_}")
    if not (
        missing_api
        or missing_resource
        or warning_id_errs
        or id_format_errs
        or uncovered_features
        or uncovered_surfaces
        or bad_entities
    ):
        print(
            "\nAll required fields filled, coverage complete, entity links resolved. "
            "Set metadata.status: complete when done."
        )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate API.yaml + every API__*.yaml against the sdlc-api schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "API.yaml"),
        help="Path to API.yaml (default: ./docs/API.yaml). Sibling API__*.yaml "
        "files in the same directory are validated automatically.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
