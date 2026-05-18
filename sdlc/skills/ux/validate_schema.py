"""Validate UX.yaml + every UX__*.yaml against the canonical sdlc-ux schema,
and run the PRD-flow coverage check.

Run from the project root:

    python sdlc/skills/ux/validate_schema.py
    python sdlc/skills/ux/validate_schema.py --path docs/UX.yaml
    python sdlc/skills/ux/validate_schema.py --docs-dir other/docs

Validates:
    1. docs/UX.yaml (or --path) — global UX contract.
    2. Every docs/UX__*.yaml sibling — one per surface.
    3. Coverage: every PRD use_cases.core_workflows entry is referenced by
       at least one UX__*.yaml via `traces_prd_flows`. Uncovered flows
       appear in UX.yaml's `ux_warnings`. If UX.yaml claims status:complete
       but coverage is incomplete, validation fails.

Exit codes:
    0 — schema valid; either status='complete' (with all required fields
        filled AND coverage check passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but coverage is incomplete.
    2 — could not read or parse one of the files (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
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
    mixed = "mixed"


class NavigationModelType(str, Enum):
    sitemap = "sitemap"
    command_tree = "command_tree"
    state_graph = "state_graph"
    hybrid = "hybrid"


class SurfaceStatus(str, Enum):
    defined = "defined"
    draft = "draft"
    confirmed = "confirmed"


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
    surface_id: Optional[str] = None
    surface_type: Optional[SurfaceType] = None
    status: Optional[SurfaceStatus] = None
    file_path: Optional[str] = None
    traces_prd_flows: Optional[List[str]] = None


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
    exit_codes: Optional[Any] = None
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
    status: Literal["draft", "complete"] = "draft"


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


class UXSurface(BaseModel):
    """Top-level per-surface document."""

    model_config = ConfigDict(extra="allow")

    metadata: SurfaceMetadata

    surface_id: Optional[str] = None
    surface_type: Optional[SurfaceType] = None
    parent_surface: Optional[str] = None
    route: Optional[str] = None
    cli_invocation: Optional[str] = None
    entry_conditions: Optional[List[str]] = None
    exit_conditions: Optional[List[str]] = None
    layout: Optional[SurfaceLayout] = None
    states: Optional[SurfaceStates] = None
    interactions: Optional[List[Any]] = None
    components: Optional[List[Any]] = None
    validation_rules: Optional[List[Any]] = None
    accessibility_notes: Optional[Any] = None  # list[string] | "inherit" | null
    traces_prd_flows: Optional[List[str]] = None
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
    "surface_id",
    "surface_type",
    "layout",
    "traces_prd_flows",
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
        if _is_empty(_get_dotted(surface, path)):
            missing.append(f"{file_label}: {path}")
    return missing


# =============================================================================
# PRD-flow coverage check.
# Every PRD use_cases.core_workflows entry must be referenced by at least one
# UX__*.yaml via traces_prd_flows. Uncovered flows are returned for surfacing.
# =============================================================================


def load_prd_core_workflows(prd_path: Path) -> List[str]:
    """Return list of core_workflows from PRD.yaml. Empty if file missing or
    flows section absent. In monorepo mode, returns the union across products.
    """
    if not prd_path.exists():
        return []
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []

    flows: List[str] = []
    metadata = raw.get("metadata") or {}
    monorepo = bool(metadata.get("monorepo"))

    if monorepo:
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for _, prod in products.items():
                if not isinstance(prod, dict):
                    continue
                uc = prod.get("use_cases") or {}
                cw = uc.get("core_workflows") if isinstance(uc, dict) else None
                if isinstance(cw, list):
                    flows.extend([str(x) for x in cw if x])
    else:
        uc = raw.get("use_cases") or {}
        cw = uc.get("core_workflows") if isinstance(uc, dict) else None
        if isinstance(cw, list):
            flows.extend([str(x) for x in cw if x])

    return flows


def collect_traced_flows(surfaces: Dict[str, UXSurface]) -> List[str]:
    traced: List[str] = []
    for _, surface in surfaces.items():
        if surface.traces_prd_flows:
            traced.extend([str(x) for x in surface.traces_prd_flows if x])
    return traced


def check_coverage(prd_flows: List[str], traced_flows: List[str]) -> List[str]:
    """Return list of PRD flows with no surface trace."""
    traced_set = {f.strip() for f in traced_flows}
    return [f for f in prd_flows if f.strip() not in traced_set]


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
    surface_errors: List[str] = []
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
        # Use file-name-derived key for traceability
        surfaces[sp.name] = surface

    # 3) Required-field checks
    missing_ux = check_ux_required(ux)
    missing_surface: List[str] = []
    for name, surface in surfaces.items():
        missing_surface.extend(check_surface_required(surface, name))

    # 4) Coverage check
    prd_path = Path("docs", "PRD.yaml")
    prd_flows = load_prd_core_workflows(prd_path)
    traced_flows = collect_traced_flows(surfaces)
    uncovered = check_coverage(prd_flows, traced_flows) if prd_flows else []

    status = ux.metadata.status
    n_surfaces = len(surfaces)

    if status == "complete":
        problems_found = bool(missing_ux or missing_surface or uncovered)
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
            if uncovered:
                print(f"{len(uncovered)} PRD core_workflow(s) with no surface trace:")
                for f in uncovered:
                    print(f"  - {f}")
            return 1
        print(
            f"[OK] UX.yaml is valid and complete ({ux_path}); "
            f"{n_surfaces} surface file(s); "
            f"{len(prd_flows)} PRD core_workflow(s) all covered."
        )
        return 0

    # status == "draft"
    print(
        f"[DRAFT] UX.yaml is a draft ({ux_path}); "
        f"{n_surfaces} surface file(s); "
        f"{len(prd_flows)} PRD core_workflow(s) discovered."
    )
    if missing_ux:
        print(f"\n{len(missing_ux)} required UX.yaml field(s) missing:")
        for m in missing_ux:
            print(f"  - {m}")
    if missing_surface:
        print(f"\n{len(missing_surface)} required surface field(s) missing:")
        for m in missing_surface:
            print(f"  - {m}")
    if uncovered:
        print(f"\n{len(uncovered)} PRD core_workflow(s) with no surface trace:")
        for f in uncovered:
            print(f"  - {f}")
    if not (missing_ux or missing_surface or uncovered):
        print("\nAll required fields filled and coverage complete. "
              "Set metadata.status: complete when done.")
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
