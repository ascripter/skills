"""Validate UX.yaml + every UX__*.yaml against the canonical sdlc-ux schema,
and run the PRD-flow coverage check.

Run from the project root:

    python sdlc/skills/ux/validate_schema.py
    python sdlc/skills/ux/validate_schema.py --path docs/UX.yaml

Validates:
    1. docs/UX.yaml (or --path) — global UX contract.
    2. Every docs/UX__*.yaml sibling — one per surface.
    3. ID-family prefix formats: SCR-NNN on surface ids, WRN-NNN on
       ux_warnings, WKF-NNN in traces_workflows, FR-NNN or NFR-NNN in
       implements_requirements, ENT-NNN in references_entities.
    4. Coverage: every WKF-NNN id in PRD use_cases.core_workflows must be
       referenced by at least one UX__*.yaml via `traces_workflows`.
       Coverage matches by WKF-NNN id (not verbatim text), so PRD text
       edits don't break UX traces.

Exit codes:
    0 — schema valid; either status='complete' (with all required fields
        filled AND coverage check passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but coverage is incomplete,
        OR status='complete' but ID-prefix format violations exist.
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
        "ERROR: pyyaml is required.\n" "Install with:  pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(3)

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
except ImportError:
    print(
        "ERROR: pydantic v2 is required.\n" "Install with:  pip install 'pydantic>=2'",
        file=sys.stderr,
    )
    sys.exit(3)


# =============================================================================
# ID-family prefix regexes (kept in lockstep with UX.schema.yaml header)
# =============================================================================

# Three-digit padding minimum; allow longer numbers for projects with many items.
ID_PATTERN = r"-\d{3,}"
SCR_ID_RE = re.compile(rf"^SCR{ID_PATTERN}$")
WRN_ITEM_RE = re.compile(rf"^WRN{ID_PATTERN}:\s+.+", re.DOTALL)  # WRN items carry message text
WKF_ID_RE = re.compile(rf"^WKF{ID_PATTERN}$")
FR_ID_RE = re.compile(rf"^FR{ID_PATTERN}$")
ENT_ID_RE = re.compile(rf"^ENT{ID_PATTERN}$")
# implements_requirements may trace BOTH functional (FR-NNN) and non-functional
# (NFR-NNN) requirements — a surface can deliver a feature and also be the place
# an NFR is realized (a per-call timeout cap, an input-containment boundary).
FR_OR_NFR_ID_RE = re.compile(rf"^(?:FR|NFR){ID_PATTERN}$")

# Extract the leading WKF-NNN id from a PRD core_workflows entry of the form
# "WKF-001: <verbatim description>". The PRD writes the verbatim form; UX
# references only the leading id.
WKF_PREFIX_EXTRACT_RE = re.compile(rf"^(WKF{ID_PATTERN})(?::|\s|$)")


# =============================================================================
# Enums (kept in lockstep with UX.schema.yaml and UX__SURFACE.schema.yaml)
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class SurfaceFamily(str, Enum):
    cli = "cli"
    web = "web"
    mobile = "mobile"
    desktop = "desktop"
    tui = "tui"          # full-screen terminal UI (curses/textual) — screen-like
    voice = "voice"      # voice / conversational, turn-based (no visual screens)
    service = "service"  # headless network service (no human UI surface)
    library = "library"  # headless code library / SDK (no human UI surface)
    mixed = "mixed"


# Headless families have no traditional visual screens: their "surfaces" are
# commands (cli), components/endpoints (service), or public API symbols
# (library). The interview emits a minimal spec for these — see
# references/surface-discovery.md.
HEADLESS_FAMILIES = {SurfaceFamily.cli, SurfaceFamily.service, SurfaceFamily.library}


class NavigationModelType(str, Enum):
    sitemap = "sitemap"
    command_tree = "command_tree"
    state_graph = "state_graph"
    hybrid = "hybrid"


class SurfaceStatus(str, Enum):
    defined = "defined"      # id + type known, no deep-dive yet
    draft = "draft"          # deep-dive started, not approved
    confirmed = "confirmed"  # deep-dive complete + user-approved
    proposed = "proposed"    # fully specced but deferred — targets a
                             # nice-to-have / post-MVP FR; kept in the inventory
                             # so the surface contract isn't lost


class SurfaceType(str, Enum):
    screen = "screen"
    modal = "modal"
    panel = "panel"
    drawer = "drawer"
    cli_command = "cli_command"
    flow_step = "flow_step"
    empty_state = "empty_state"
    toast = "toast"
    overlay = "overlay"
    tab = "tab"
    page = "page"
    dialog = "dialog"
    other = "other"


class ThemingApproach(str, Enum):
    design_tokens_dtcg = "design_tokens_dtcg"
    tailwind_utility = "tailwind_utility"
    css_variables = "css_variables"
    library_theme = "library_theme"
    none = "none"
    custom = "custom"


class WcagTarget(str, Enum):
    wcag_a = "wcag_a"
    wcag_aa = "wcag_aa"
    wcag_aaa = "wcag_aaa"
    none_yet = "none_yet"
    not_applicable_cli = "not_applicable_cli"


class CommandShape(str, Enum):
    verb_noun = "verb_noun"
    noun_verb = "noun_verb"
    flat = "flat"
    mixed = "mixed"


class ArgConventions(str, Enum):
    posix = "posix"
    gnu = "gnu"
    custom = "custom"


class HelpTextFormat(str, Enum):
    auto_generated = "auto_generated"
    authored = "authored"
    hybrid = "hybrid"


# =============================================================================
# UX.yaml — top-level theme models
# =============================================================================

# extra="allow" gives forward-compat for new question additions; enum values
# are still strictly validated.
_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _ThemeBase(BaseModel):
    model_config = _BASE_CONFIG


class DesignPrinciples(_ThemeBase):
    tenets: Optional[List[str]] = None
    anti_patterns: Optional[List[str]] = None
    inspiration_refs: Optional[List[str]] = None


class NavigationModel(_ThemeBase):
    type: Optional[NavigationModelType] = None
    type_confidence: Optional[Confidence] = None
    top_level_nodes: Optional[List[str]] = None
    deep_link_strategy: Optional[str] = None
    auth_required_routes: Optional[List[str]] = None
    sitemap: Optional[Any] = None
    command_tree: Optional[Any] = None
    state_graph: Optional[Any] = None


class SurfaceInventoryItem(_ThemeBase):
    id: Optional[str] = None  # SCR-NNN
    surface_id: Optional[str] = None
    surface_type: Optional[SurfaceType] = None
    status: Optional[SurfaceStatus] = None
    file_path: Optional[str] = None
    traces_workflows: Optional[List[str]] = None
    implements_requirements: Optional[List[str]] = None
    references_entities: Optional[List[str]] = None


class ThemingTokens(_ThemeBase):
    colors: Optional[Any] = None
    typography: Optional[Any] = None
    spacing: Optional[Any] = None
    radii: Optional[Any] = None
    shadows: Optional[Any] = None
    motion: Optional[Any] = None


class ComponentLibrary(_ThemeBase):
    name: Optional[str] = None
    name_rationale: Optional[str] = None
    name_confidence: Optional[Confidence] = None
    theming_approach: Optional[ThemingApproach] = None
    theming_approach_confidence: Optional[Confidence] = None
    theming_tokens: Optional[ThemingTokens] = None


class StatePatterns(_ThemeBase):
    default: Optional[str] = None
    loading: Optional[str] = None
    empty: Optional[str] = None
    error: Optional[str] = None
    error_confidence: Optional[Confidence] = None
    success: Optional[str] = None


class ContentRules(_ThemeBase):
    tone: Optional[str] = None
    tone_confidence: Optional[Confidence] = None
    error_message_style: Optional[str] = None
    terminology: Optional[List[Any]] = None
    copy_length_limits: Optional[Any] = None


class AccessibilityBaseline(_ThemeBase):
    wcag_target: Optional[WcagTarget] = None
    wcag_target_confidence: Optional[Confidence] = None
    keyboard_only: Optional[bool] = None
    screen_reader_notes: Optional[List[str]] = None
    color_contrast_minimum: Optional[str] = None
    motion_preferences: Optional[bool] = None


class Localisation(_ThemeBase):
    enabled: Optional[bool] = None
    default_locale: Optional[str] = None
    target_locales: Optional[List[str]] = None
    framework: Optional[str] = None
    rtl_support: Optional[bool] = None


class CliOutputFormats(_ThemeBase):
    supported: Optional[List[str]] = None
    default: Optional[str] = None


class CliConfigFile(_ThemeBase):
    location: Optional[str] = None
    precedence: Optional[str] = None
    env_prefix: Optional[str] = None


class Cli(_ThemeBase):
    root_command: Optional[str] = None
    root_command_confidence: Optional[Confidence] = None
    command_shape: Optional[CommandShape] = None
    arg_parsing_library: Optional[str] = None
    arg_parsing_library_rationale: Optional[str] = None
    arg_parsing_library_confidence: Optional[Confidence] = None
    arg_conventions: Optional[ArgConventions] = None
    help_text_format: Optional[HelpTextFormat] = None
    output_formats: Optional[CliOutputFormats] = None
    exit_code_convention: Optional[str] = None
    # exit_codes is a Dict[str, Any] so projects can use either the legacy
    # {code: "description"} string-only shape or the new
    # {code: {description, implements_requirements, ...}} mapping shape.
    # ID-prefix checks below walk the dict and validate FR-NNN refs when
    # present.
    exit_codes: Optional[Dict[str, Any]] = None
    interactive_mode: Optional[Any] = None
    config_file: Optional[CliConfigFile] = None


# -----------------------------------------------------------------------------
# Top-level UX models
# -----------------------------------------------------------------------------


class UXMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    ux_version: str
    last_updated: str
    generated_by: str = "sdlc-ux"
    session_id: str
    monorepo: bool = False
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None
    # One entry per upstream artifact consumed, each a mapping
    # {file, session_id, last_updated, sha256}. Type-checked as a list of
    # mappings only — see CLAUDE.md §7 "Upstream-change re-invocation".
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class UXProduct(_ThemeBase):
    """One product's UX contract in monorepo mode."""

    surface_family: Optional[SurfaceFamily] = None
    surface_family_confidence: Optional[Confidence] = None
    surface_family_members: Optional[List[SurfaceFamily]] = None
    device_targets: Optional[List[str]] = None
    device_targets_confidence: Optional[Confidence] = None
    viewport_breakpoints: Optional[List[str]] = None

    design_principles: Optional[DesignPrinciples] = None
    navigation_model: Optional[NavigationModel] = None
    surface_inventory: Optional[List[SurfaceInventoryItem]] = None
    component_library: Optional[ComponentLibrary] = None
    state_patterns: Optional[StatePatterns] = None
    content_rules: Optional[ContentRules] = None
    accessibility: Optional[AccessibilityBaseline] = None
    localisation: Optional[Localisation] = None
    cli: Optional[Cli] = None


class UX(BaseModel):
    """Top-level UX.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: UXMetadata
    ux_warnings: List[str] = Field(default_factory=list)

    # Single-product mode — all theme blocks live at top level
    surface_family: Optional[SurfaceFamily] = None
    surface_family_confidence: Optional[Confidence] = None
    surface_family_members: Optional[List[SurfaceFamily]] = None
    device_targets: Optional[List[str]] = None
    device_targets_confidence: Optional[Confidence] = None
    viewport_breakpoints: Optional[List[str]] = None

    design_principles: Optional[DesignPrinciples] = None
    navigation_model: Optional[NavigationModel] = None
    surface_inventory: Optional[List[SurfaceInventoryItem]] = None
    component_library: Optional[ComponentLibrary] = None
    state_patterns: Optional[StatePatterns] = None
    content_rules: Optional[ContentRules] = None
    accessibility: Optional[AccessibilityBaseline] = None
    localisation: Optional[Localisation] = None
    cli: Optional[Cli] = None

    # Multi-product mode
    products: Optional[Dict[str, UXProduct]] = None

    @model_validator(mode="after")
    def _check_mode(self) -> "UX":
        single_themes = [
            self.surface_family,
            self.design_principles,
            self.navigation_model,
            self.surface_inventory,
            self.component_library,
            self.state_patterns,
            self.content_rules,
            self.accessibility,
            self.localisation,
            self.cli,
        ]
        any_single = any(t is not None for t in single_themes)

        if self.metadata.monorepo:
            if not self.products:
                raise ValueError(
                    "metadata.monorepo is true but `products` is missing or empty"
                )
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
# UX__<surface>.yaml — per-surface model
# =============================================================================


class SurfaceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    ux_surface_version: str
    last_updated: str
    generated_by: str = "sdlc-ux"
    session_id: str
    # "proposed" = the surface is fully specced but its owning FR is
    # nice-to-have / post-MVP, so it is intentionally deferred (a terminal,
    # non-draft state). Downstream consumers that gate on `complete` will skip
    # a `proposed` surface — which is the intent. The top-level UX.yaml stays
    # draft|complete; only per-surface artifacts may be `proposed`.
    status: Literal["draft", "complete", "proposed"] = "draft"
    changelog: Optional[List[str]] = None


class SurfaceLayout(_ThemeBase):
    region_tree: Optional[Any] = None
    cli_args: Optional[List[Any]] = None


class SurfaceStateBlock(_ThemeBase):
    description: Optional[str] = None
    content_outline: Optional[Any] = None
    recovery_action: Optional[str] = None  # only used by `error`


class SurfaceStates(_ThemeBase):
    default: Optional[Any] = None  # "inherit" | SurfaceStateBlock | null
    loading: Optional[Any] = None
    empty: Optional[Any] = None
    error: Optional[Any] = None
    success: Optional[Any] = None


class SurfaceInteraction(_ThemeBase):
    """One event handler downstream — typed so every run emits the same shape."""

    id: Optional[str] = None                    # kebab-case, unique per surface
    actor: Optional[str] = None                 # user | system
    trigger: Optional[str] = None               # click | submit | keypress | ... | cli_invoke
    trigger_target: Optional[str] = None        # component_id | "surface"
    preconditions: Optional[List[str]] = None
    effects: Optional[List[str]] = None
    target_surface: Optional[str] = None        # SCR-NNN | surface_id | null
    error_paths: Optional[List[str]] = None


class SurfaceComponent(_ThemeBase):
    """One component to instantiate — typed so codegen sees a stable contract."""

    id: Optional[str] = None                    # kebab-case, unique per surface
    type: Optional[str] = None                  # button | input | table | ... | custom
    library_ref: Optional[str] = None
    variants: Optional[List[str]] = None
    content_slots: Optional[Dict[str, Any]] = None
    aria_role: Optional[str] = None
    keyboard_shortcuts: Optional[List[str]] = None
    binds: Optional[List[str]] = None           # "Entity.field" data bindings — which
                                                # DATA-MODEL field each input/display
                                                # component reads or writes


class SurfaceValidationRule(_ThemeBase):
    field: Optional[str] = None                 # component_id of the input
    rules: Optional[List[str]] = None           # ["required", "max_length=140", ...]
    error_message: Optional[str] = None


class UXSurface(BaseModel):
    """Top-level per-surface document."""

    model_config = ConfigDict(extra="allow")

    metadata: SurfaceMetadata

    id: Optional[str] = None  # SCR-NNN
    surface_id: Optional[str] = None
    surface_type: Optional[SurfaceType] = None
    parent_surface: Optional[str] = None
    route: Optional[str] = None
    cli_invocation: Optional[str] = None
    entry_conditions: Optional[List[str]] = None
    exit_conditions: Optional[List[str]] = None
    layout: Optional[SurfaceLayout] = None
    states: Optional[SurfaceStates] = None
    interactions: Optional[List[SurfaceInteraction]] = None
    components: Optional[List[SurfaceComponent]] = None
    validation_rules: Optional[List[SurfaceValidationRule]] = None
    accessibility_notes: Optional[Any] = None  # list[string] | "inherit" | null
    traces_workflows: Optional[List[str]] = None
    implements_requirements: Optional[List[str]] = None
    references_entities: Optional[List[str]] = None
    notes: Optional[str] = None


# =============================================================================
# Required-field checks. Validation behaviour depends on metadata.status:
# drafts are tolerated, but `status: complete` requires every required path
# to be non-empty.
# =============================================================================

# UX.yaml required paths (relative to a product in monorepo mode, or top level).
UX_REQUIRED_PATHS: List[str] = [
    "surface_family",
    "design_principles.tenets",
    "navigation_model.type",
    "navigation_model.top_level_nodes",
    "surface_inventory",
    "component_library.name",
    "state_patterns.error",
    "content_rules.tone",
    "accessibility.wcag_target",
]

# CLI-specific required paths (only enforced when surface_family is cli or mixed).
UX_CLI_REQUIRED_PATHS: List[str] = [
    "cli.root_command",
    "cli.arg_parsing_library",
    "cli.output_formats.supported",
    "cli.output_formats.default",
]

# UX__<surface>.yaml required paths.
SURFACE_REQUIRED_PATHS: List[str] = [
    "id",
    "surface_id",
    "surface_type",
    "layout",
    "traces_workflows",
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


def check_ux_required(ux: UX) -> List[str]:
    """Return list of missing required UX.yaml field paths."""
    missing: List[str] = []

    def _check(scope_label: str, root: object) -> None:
        for path in UX_REQUIRED_PATHS:
            if _is_empty(_get_dotted(root, path)):
                missing.append(f"{scope_label}{path}")
        # CLI-specific
        family = getattr(root, "surface_family", None)
        if family in (SurfaceFamily.cli, SurfaceFamily.mixed):
            for path in UX_CLI_REQUIRED_PATHS:
                if _is_empty(_get_dotted(root, path)):
                    missing.append(f"{scope_label}{path}")
        # Per-inventory-item required fields. Each surface in
        # surface_inventory must carry id/surface_id/surface_type/file_path
        # by the time the artifact claims complete; traces_workflows must
        # be non-None (empty list [] is allowed — see check_surface_required).
        inv: Optional[List[SurfaceInventoryItem]] = getattr(
            root, "surface_inventory", None
        )
        if inv:
            for i, item in enumerate(inv):
                where = f"{scope_label}surface_inventory[{i}]"
                if _is_empty(item.id):
                    missing.append(f"{where}.id")
                if _is_empty(item.surface_id):
                    missing.append(f"{where}.surface_id")
                if _is_empty(item.surface_type):
                    missing.append(f"{where}.surface_type")
                if _is_empty(item.file_path):
                    missing.append(f"{where}.file_path")
                if item.traces_workflows is None:
                    missing.append(f"{where}.traces_workflows")

    if ux.metadata.monorepo and ux.products:
        for slug, product in ux.products.items():
            _check(f"products.{slug}.", product)
    else:
        _check("", ux)

    return missing


def check_surface_required(surface: UXSurface, file_label: str) -> List[str]:
    """Return list of missing required fields for one surface yaml."""
    missing: List[str] = []
    for path in SURFACE_REQUIRED_PATHS:
        # traces_workflows: [] is allowed (non-flow surfaces) — only None/missing
        # counts as unfilled here; the coverage check handles flow obligations.
        if path == "traces_workflows":
            if _get_dotted(surface, path) is None:
                missing.append(f"{file_label}: {path}")
            continue
        if _is_empty(_get_dotted(surface, path)):
            missing.append(f"{file_label}: {path}")
    return missing


# =============================================================================
# ID-prefix format checks.
# All values are tested against the appropriate family's regex. Violations are
# returned as human-readable strings so the caller can print them.
# =============================================================================


def _check_list_prefix(
    values: Optional[List[str]],
    pattern: re.Pattern[str],
    expected: str,
    where: str,
) -> List[str]:
    """Return one error string per value that fails `pattern`."""
    if not values:
        return []
    errors: List[str] = []
    for v in values:
        if not isinstance(v, str) or not pattern.match(v.strip()):
            errors.append(
                f"{where}: '{v}' does not match {expected}"
            )
    return errors


def check_ux_id_prefixes(ux: UX) -> List[str]:
    """Validate SCR/WRN/WKF/FR/ENT prefixes inside UX.yaml. Returns error
    strings; an empty list means all formats are valid.
    """
    errors: List[str] = []

    # ux_warnings — every entry "WRN-NNN: <message>"
    for i, w in enumerate(ux.ux_warnings or []):
        if not isinstance(w, str) or not WRN_ITEM_RE.match(w.strip()):
            errors.append(
                f"ux_warnings[{i}]: '{w}' must match 'WRN-NNN: <message>'"
            )

    def _check_product(scope: str, product: object) -> None:
        inv: Optional[List[SurfaceInventoryItem]] = getattr(
            product, "surface_inventory", None
        )
        if inv:
            for i, item in enumerate(inv):
                where = f"{scope}surface_inventory[{i}]"
                if item.id is not None and not SCR_ID_RE.match(item.id.strip()):
                    errors.append(
                        f"{where}.id: '{item.id}' must match 'SCR-NNN'"
                    )
                errors.extend(
                    _check_list_prefix(
                        item.traces_workflows,
                        WKF_ID_RE,
                        "'WKF-NNN'",
                        f"{where}.traces_workflows",
                    )
                )
                errors.extend(
                    _check_list_prefix(
                        item.implements_requirements,
                        FR_OR_NFR_ID_RE,
                        "'FR-NNN' or 'NFR-NNN'",
                        f"{where}.implements_requirements",
                    )
                )
                errors.extend(
                    _check_list_prefix(
                        item.references_entities,
                        ENT_ID_RE,
                        "'ENT-NNN'",
                        f"{where}.references_entities",
                    )
                )
        cli: Optional[Cli] = getattr(product, "cli", None)
        if cli and cli.exit_codes:
            for code, spec in cli.exit_codes.items():
                if isinstance(spec, dict):
                    fr_refs = spec.get("implements_requirements")
                    errors.extend(
                        _check_list_prefix(
                            fr_refs if isinstance(fr_refs, list) else None,
                            FR_OR_NFR_ID_RE,
                            "'FR-NNN' or 'NFR-NNN'",
                            f"{scope}cli.exit_codes['{code}'].implements_requirements",
                        )
                    )

    if ux.metadata.monorepo and ux.products:
        for slug, product in ux.products.items():
            _check_product(f"products.{slug}.", product)
    else:
        _check_product("", ux)

    return errors


def check_surface_id_prefixes(surface: UXSurface, file_label: str) -> List[str]:
    """Validate prefixes inside a UX__<surface>.yaml file."""
    errors: List[str] = []

    if surface.id is not None and not SCR_ID_RE.match(surface.id.strip()):
        errors.append(f"{file_label}: id: '{surface.id}' must match 'SCR-NNN'")
    errors.extend(
        _check_list_prefix(
            surface.traces_workflows,
            WKF_ID_RE,
            "'WKF-NNN'",
            f"{file_label}: traces_workflows",
        )
    )
    errors.extend(
        _check_list_prefix(
            surface.implements_requirements,
            FR_OR_NFR_ID_RE,
            "'FR-NNN' or 'NFR-NNN'",
            f"{file_label}: implements_requirements",
        )
    )
    errors.extend(
        _check_list_prefix(
            surface.references_entities,
            ENT_ID_RE,
            "'ENT-NNN'",
            f"{file_label}: references_entities",
        )
    )
    return errors


# =============================================================================
# PRD-flow coverage check.
# Coverage matches by WKF-NNN id (not verbatim text). PRD core_workflows
# entries are of the form "WKF-NNN: <description>"; the leading id is
# extracted and compared against UX surface traces_workflows (which carry
# WKF-NNN ids only).
# =============================================================================


def load_prd_core_workflow_ids(prd_path: Path) -> List[str]:
    """Return list of WKF-NNN ids parsed out of PRD.use_cases.core_workflows.
    Empty if file missing or flows section absent. In monorepo mode, returns
    the union across products. Entries that don't begin with a WKF-NNN id are
    skipped (they'd fail PRD validation anyway).
    """
    if not prd_path.exists():
        return []
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []

    ids: List[str] = []
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo"))

    def _collect(workflows: Any) -> None:
        if not isinstance(workflows, list):
            return
        for entry in workflows:
            if not isinstance(entry, str):
                continue
            m = WKF_PREFIX_EXTRACT_RE.match(entry.strip())
            if m:
                ids.append(m.group(1))

    if monorepo:
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for _, prod in products.items():
                if not isinstance(prod, dict):
                    continue
                uc = prod.get("use_cases") or {}
                cw = uc.get("core_workflows") if isinstance(uc, dict) else None
                _collect(cw)
    else:
        uc = raw.get("use_cases") or {}
        cw = uc.get("core_workflows") if isinstance(uc, dict) else None
        _collect(cw)

    return ids


def collect_traced_workflow_ids(surfaces: Dict[str, UXSurface]) -> List[str]:
    traced: List[str] = []
    for _, surface in surfaces.items():
        if surface.traces_workflows:
            traced.extend(
                str(x).strip() for x in surface.traces_workflows if x
            )
    return traced


def check_coverage(prd_ids: List[str], traced_ids: List[str]) -> List[str]:
    """Return list of PRD WKF-NNN ids with no surface trace."""
    traced_set = set(traced_ids)
    return [w for w in prd_ids if w not in traced_set]


_FR_HEAD_EXTRACT_RE = re.compile(r"^(FR-\d+)(?::|\s|$)")
_FR_TOKEN_RE = re.compile(r"\bFR-\d+\b", re.IGNORECASE)


def load_prd_fr_ids(prd_path: Path) -> List[str]:
    """Gating FR-NNN ids from PRD functional_requirements (union across products
    in monorepo mode). D2 gating subset (FR_GATE, CLAUDE.md §10): the flat
    `features` list when present, else the legacy `must_have_features` ONLY —
    a legacy PRD's nice_to_have backlog stays outside the coverage advisory,
    preserving pre-D2 behavior. Empty when PRD is absent."""
    if not prd_path.exists():
        return []
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    ids: List[str] = []

    def _collect(scope: Any) -> None:
        if not isinstance(scope, dict):
            return
        fr = scope.get("functional_requirements") or {}
        if not isinstance(fr, dict):
            return
        entries = fr.get("features")
        if not entries:  # legacy: must_have only (nice_to_have stays ungated)
            entries = fr.get("must_have_features") or []
        for entry in entries or []:
            if isinstance(entry, str):
                m = _FR_HEAD_EXTRACT_RE.match(entry.strip())
                if m:
                    ids.append(m.group(1))

    if (raw.get("metadata") or {}).get("monorepo"):
        for prod in (raw.get("products") or {}).values():
            _collect(prod)
    else:
        _collect(raw)
    return ids


def check_fr_coverage(
    prd_fr_ids: List[str], ux: "UX", surfaces: Dict[str, UXSurface]
) -> List[str]:
    """ADVISORY (never blocks) — FRs no surface implements.

    Trace-or-defer: an FR is covered when some surface (file or inventory
    entry) lists it in implements_requirements, OR a ux_warnings entry names
    it (an intentional 'not a UI concern' deferral). WKF coverage stays the
    blocking gate; this advisory catches the FRs with no workflow AND no
    surface — the ones silently unrepresented at the UX layer.
    """
    covered = {
        str(x).strip().upper()
        for surface in surfaces.values()
        for x in (surface.implements_requirements or [])
    }
    for inv in _iter_inventory_items(ux):
        for x in getattr(inv, "implements_requirements", None) or []:
            covered.add(str(x).strip().upper())
    deferred = {
        m.upper()
        for w in _iter_ux_warnings(ux)
        for m in _FR_TOKEN_RE.findall(w)
    }
    return [f for f in prd_fr_ids if f.upper() not in covered | deferred]


def _iter_inventory_items(ux: "UX"):
    for scope in _iter_ux_scopes(ux):
        for item in getattr(scope, "surface_inventory", None) or []:
            yield item


def _iter_ux_warnings(ux: "UX"):
    for scope in _iter_ux_scopes(ux):
        for w in getattr(scope, "ux_warnings", None) or []:
            if isinstance(w, str):
                yield w


def _iter_ux_scopes(ux: "UX"):
    yield ux
    for prod in (getattr(ux, "products", None) or {}).values():
        yield prod


# =============================================================================
# File loading / validation orchestration
# =============================================================================


def check_downstream_claims(ux: UX, docs_dir: Path) -> List[str]:
    """Advisory (never blocks) — surface-status maturity vs downstream claims.

    When a sibling docs/ARCH.yaml claims a surface (some container's
    owns_ux_surfaces lists it), the architecture treats that surface as real:
    it gets components, edges, and eventually tests. An inventory entry still
    marked `proposed` (specced but deferred) — or never advanced past
    `defined`/`draft` — is then stale lifecycle metadata that misleads every
    downstream reader about what is actually being built. The skill's
    re-invocation flow reconciles these (SKILL.md Phase 2 → downstream-claim
    reconciliation); this warning is the standing detector.
    """
    warns: List[str] = []
    arch_path = docs_dir / "ARCH.yaml"
    if not arch_path.exists():
        return warns
    try:
        arch_raw = yaml.safe_load(arch_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return warns
    if not isinstance(arch_raw, dict):
        return warns
    claimed: Dict[str, str] = {}  # surface_id -> claiming container_id
    for c in arch_raw.get("containers") or []:
        if isinstance(c, dict):
            for sid in c.get("owns_ux_surfaces") or []:
                claimed.setdefault(str(sid), str(c.get("container_id")))
    if not claimed:
        return warns

    def _sweep(items: Optional[List[SurfaceInventoryItem]], scope: str) -> None:
        for item in items or []:
            sid = (item.surface_id or "").strip()
            status = item.status.value if item.status else None
            if sid in claimed and status != "confirmed":
                warns.append(
                    f"{scope}surface '{sid}' ({item.id}) has status "
                    f"'{status}' but ARCH container '{claimed[sid]}' claims it "
                    f"(owns_ux_surfaces) — reconcile the lifecycle: re-run "
                    f"/sdlc:ux to confirm the surface or correct the ARCH claim"
                )

    _sweep(ux.surface_inventory, "")
    for slug, product in (ux.products or {}).items():
        _sweep(product.surface_inventory, f"products.{slug}.")
    return warns


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


def discover_surface_files(ux_path: Path) -> List[Path]:
    """Return sorted list of docs/UX__*.yaml siblings of ux_path."""
    parent = ux_path.parent
    return sorted(parent.glob("UX__*.yaml"))


def validate_all(ux_path: Path) -> int:
    """Validate UX.yaml, all UX__*.yaml siblings, and run coverage check."""

    # 1) UX.yaml
    raw, err = _load_yaml(ux_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    try:
        ux = UX.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] UX.yaml FAILED schema validation ({ux_path})\n")
        print("Errors:")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    # 2) Each UX__<surface>.yaml
    surface_files = discover_surface_files(ux_path)
    surfaces: Dict[str, UXSurface] = {}
    for sp in surface_files:
        s_raw, s_err = _load_yaml(sp)
        if s_err:
            print(f"ERROR: {s_err}", file=sys.stderr)
            return 2
        try:
            surface = UXSurface.model_validate(s_raw)
        except ValidationError as e:
            print(f"[FAIL] {sp.name} FAILED schema validation\n")
            for line in _format_pydantic_errors(e):
                print(f"  - {line}")
            return 1
        surfaces[sp.name] = surface

    # 3) Required-field checks
    missing_ux = check_ux_required(ux)
    missing_surface: List[str] = []
    for name, surface in surfaces.items():
        missing_surface.extend(check_surface_required(surface, name))

    # 4) ID-prefix format checks
    id_errors = check_ux_id_prefixes(ux)
    for name, surface in surfaces.items():
        id_errors.extend(check_surface_id_prefixes(surface, name))

    # 5) Coverage check (WKF-NNN id-based)
    # PRD.yaml is a sibling of UX.yaml in the same docs/ directory; resolve it
    # relative to the artifact, not the CWD, so the validator works regardless
    # of where it is invoked from (fixtures, staged eval test-projects, etc.).
    prd_path = ux_path.parent / "PRD.yaml"
    prd_ids = load_prd_core_workflow_ids(prd_path)
    traced_ids = collect_traced_workflow_ids(surfaces)
    uncovered = check_coverage(prd_ids, traced_ids) if prd_ids else []

    # 6) Downstream-claim maturity check (advisory, never blocks)
    downstream_warnings = check_downstream_claims(ux, ux_path.parent)

    # 7) FR-coverage advisory (never blocks): FRs with no surface
    # implements_requirements trace and no ux_warnings deferral.
    fr_gaps = check_fr_coverage(load_prd_fr_ids(prd_path), ux, surfaces)

    def _print_downstream_warnings() -> None:
        if downstream_warnings:
            print(f"\nWARNINGS ({len(downstream_warnings)} surface(s) claimed downstream but not 'confirmed'):")
            for w in downstream_warnings:
                print(f"  - {w}")
        if fr_gaps:
            print(f"\nAdvisory (never blocks): {len(fr_gaps)} FR(s) implemented by no surface and deferred by no ux_warnings entry:")
            for f in fr_gaps:
                print(f"  - {f}")

    status = ux.metadata.status
    n_surfaces = len(surfaces)

    if status == "complete":
        problems_found = bool(missing_ux or missing_surface or id_errors or uncovered)
        if problems_found:
            print(f"[FAIL] UX.yaml claims status 'complete' but has errors ({ux_path})\n")
            if missing_ux:
                print(f"{len(missing_ux)} required UX.yaml field(s) missing:")
                for m in missing_ux:
                    print(f"  - {m}")
                print()
            if missing_surface:
                print(f"{len(missing_surface)} required surface field(s) missing:")
                for m in missing_surface:
                    print(f"  - {m}")
                print()
            if id_errors:
                print(f"{len(id_errors)} ID-prefix format violation(s):")
                for m in id_errors:
                    print(f"  - {m}")
                print()
            if uncovered:
                print(f"{len(uncovered)} PRD WKF-NNN(s) with no surface trace:")
                for f in uncovered:
                    print(f"  - {f}")
            _print_downstream_warnings()
            return 1
        print(
            f"[OK] UX.yaml is valid and complete ({ux_path}); "
            f"{n_surfaces} surface file(s); "
            f"{len(prd_ids)} PRD WKF-NNN(s) all covered."
        )
        _print_downstream_warnings()
        return 0

    # status == "draft"
    print(
        f"[DRAFT] UX.yaml is a draft ({ux_path}); "
        f"{n_surfaces} surface file(s); "
        f"{len(prd_ids)} PRD WKF-NNN(s) discovered."
    )
    if missing_ux:
        print(f"\n{len(missing_ux)} required UX.yaml field(s) missing:")
        for m in missing_ux:
            print(f"  - {m}")
    if missing_surface:
        print(f"\n{len(missing_surface)} required surface field(s) missing:")
        for m in missing_surface:
            print(f"  - {m}")
    if id_errors:
        print(f"\n{len(id_errors)} ID-prefix format violation(s) (warnings in draft):")
        for m in id_errors:
            print(f"  - {m}")
    if uncovered:
        print(f"\n{len(uncovered)} PRD WKF-NNN(s) with no surface trace:")
        for f in uncovered:
            print(f"  - {f}")
    if not (missing_ux or missing_surface or id_errors or uncovered):
        print("\nAll required fields filled and coverage complete. "
              "Set metadata.status: complete when done.")
    _print_downstream_warnings()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate UX.yaml + every UX__*.yaml against the sdlc-ux schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "UX.yaml"),
        help="Path to UX.yaml (default: ./docs/UX.yaml). Sibling UX__*.yaml "
        "files in the same directory are validated automatically.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
