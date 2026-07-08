"""Validate DESIGN.yaml + its conditional sub-files against the sdlc-design schema.

Run from the project root:

    python sdlc/skills/design/validate_schema.py
    python sdlc/skills/design/validate_schema.py --path docs/DESIGN.yaml

Validates:
    1. docs/DESIGN.yaml (or --path) — the global design-system contract.
    2. docs/DESIGN__tokens.yaml — iff token_based_ui ∈ functional_structure.
    3. docs/DESIGN__assets.yaml — iff asset_pipeline ∈ functional_structure OR
       aesthetic_direction.requires_custom_assets.
       (In monorepo mode: docs/DESIGN__<slug>__tokens.yaml / __assets.yaml.)
    4. ID-family prefix formats: AST-NNN on asset ids, WRN-NNN on design_warnings,
       FR-NNN/NFR-NNN in implements_requirements, SCR-NNN in traces_ux_surfaces,
       ENT-NNN in references_entities.
    5. Composition consistency: `headless` is exclusive; the tokens file exists
       iff token_based_ui is selected; the assets file exists iff asset_pipeline
       is selected or an aesthetic needs custom assets; aesthetic_direction is
       present unless the structure is purely headless.
    6. Asset-brief coverage (trace-or-defer): every asset with
       source == "to_be_generated" carries a non-null generation_brief OR is
       deferred via a "WRN-NNN: … AST-NNN …" entry in DESIGN.yaml.design_warnings.

Exit codes:
    0 — schema valid; either status='complete' (all required fields filled,
        composition consistent, and to-be-generated coverage satisfied) or
        status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, composition is inconsistent, ID-prefix format is
        violated, or a to-be-generated asset is uncovered.
    2 — could not read or parse one of the files (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import re
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
# ID-family prefix regexes (kept in lockstep with DESIGN.schema.yaml header)
# =============================================================================

ID_PATTERN = r"-\d{3,}"  # three-digit minimum; longer allowed for big projects
AST_ID_RE = re.compile(rf"^AST{ID_PATTERN}$")
WRN_ITEM_RE = re.compile(rf"^WRN{ID_PATTERN}:\s+.+", re.DOTALL)
SCR_ID_RE = re.compile(rf"^SCR{ID_PATTERN}$")
ENT_ID_RE = re.compile(rf"^ENT{ID_PATTERN}$")
# implements_requirements traces BOTH functional (FR) and non-functional (NFR)
# requirements — a design can realize a feature and also honour a constraint.
FR_OR_NFR_ID_RE = re.compile(rf"^(?:FR|NFR){ID_PATTERN}$")
# Any AST-NNN token, used to scan free-text WRN entries for a deferral reference.
AST_ANYWHERE_RE = re.compile(rf"AST{ID_PATTERN}")


# =============================================================================
# Enums (kept in lockstep with the three schema yamls)
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class FunctionalStructure(str, Enum):
    token_based_ui = "token_based_ui"
    asset_pipeline = "asset_pipeline"
    headless = "headless"


class MotionCharacter(str, Enum):
    none = "none"
    subtle = "subtle"
    expressive = "expressive"
    playful = "playful"


class TokenSource(str, Enum):
    dtcg_authored = "dtcg_authored"
    import_shadcn = "import_shadcn"
    import_tokens_studio = "import_tokens_studio"
    import_tailwind = "import_tailwind"
    import_other = "import_other"


class AssetSource(str, Enum):
    to_be_generated = "to_be_generated"
    user_supplied = "user_supplied"
    placeholder = "placeholder"


class AssetModality(str, Enum):
    image = "image"
    audio = "audio"
    model_3d = "model_3d"
    font = "font"
    shader = "shader"
    vfx = "vfx"
    animation = "animation"


# =============================================================================
# DESIGN.yaml models
# =============================================================================

# extra="allow" gives forward-compat for new question additions; enum values
# are still strictly validated.
_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _Block(BaseModel):
    model_config = _BASE_CONFIG


class AestheticDirection(_Block):
    style_family: Optional[str] = None  # OPEN vocabulary — free-form string
    style_family_confidence: Optional[Confidence] = None
    mood_keywords: Optional[List[str]] = None
    palette_intent: Optional[str] = None
    style_references: Optional[List[str]] = None
    typographic_voice: Optional[str] = None
    motion_character: Optional[MotionCharacter] = None
    texture_and_finish: Optional[str] = None
    requires_custom_assets: Optional[bool] = None


class SubArtifacts(_Block):
    tokens: Optional[str] = None
    assets: Optional[str] = None


class BrandIdentity(_Block):
    logo_usage: Optional[str] = None
    brand_palette: Optional[List[str]] = None
    brand_voice: Optional[str] = None
    imagery_style: Optional[str] = None


class SurfaceOverride(_Block):
    """Per-surface styling deviation on top of the global system. Keyed by
    SCR-NNN in surface_overrides. Presence of an entry = concrete per-surface
    design work `task` derives (in addition to the global theme/token task)."""

    density: Optional[Literal["compact", "comfortable", "spacious"]] = None
    token_overrides: Optional[Dict[str, Any]] = None
    component_variants: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class DesignMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    design_version: str
    last_updated: str
    generated_by: str = "sdlc-design"
    session_id: str
    monorepo: bool = False
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


class DesignProduct(_Block):
    """One product's design contract in monorepo mode (also the shape of the
    single-product top level)."""

    functional_structure: Optional[List[FunctionalStructure]] = None
    functional_structure_confidence: Optional[Confidence] = None
    functional_structure_rationale: Optional[str] = None
    aesthetic_direction: Optional[AestheticDirection] = None
    sub_artifacts: Optional[SubArtifacts] = None
    brand_identity: Optional[BrandIdentity] = None
    implements_requirements: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    surface_overrides: Optional[Dict[str, SurfaceOverride]] = None


class Design(BaseModel):
    """Top-level DESIGN.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: DesignMetadata
    design_warnings: List[str] = Field(default_factory=list)

    # Single-product mode — axis blocks at top level
    functional_structure: Optional[List[FunctionalStructure]] = None
    functional_structure_confidence: Optional[Confidence] = None
    functional_structure_rationale: Optional[str] = None
    aesthetic_direction: Optional[AestheticDirection] = None
    sub_artifacts: Optional[SubArtifacts] = None
    brand_identity: Optional[BrandIdentity] = None
    implements_requirements: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None
    surface_overrides: Optional[Dict[str, SurfaceOverride]] = None

    # Multi-product mode
    products: Optional[Dict[str, DesignProduct]] = None

    @model_validator(mode="after")
    def _check_mode(self) -> "Design":
        single = [
            self.functional_structure,
            self.aesthetic_direction,
            self.sub_artifacts,
            self.brand_identity,
            self.implements_requirements,
            self.traces_ux_surfaces,
            self.surface_overrides,
        ]
        any_single = any(t is not None for t in single)
        if self.metadata.monorepo:
            if not self.products:
                raise ValueError(
                    "metadata.monorepo is true but `products` is missing or empty"
                )
            if any_single:
                raise ValueError(
                    "monorepo mode set but top-level axis blocks are present; "
                    "in monorepo mode every block must live under `products.<slug>`"
                )
        else:
            if self.products:
                raise ValueError(
                    "`products` is set but metadata.monorepo is false; "
                    "either set monorepo: true or move blocks to top level"
                )
        return self


# =============================================================================
# DESIGN__tokens.yaml model
# =============================================================================


class TokensMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    design_tokens_version: str
    last_updated: str
    generated_by: str = "sdlc-design"
    session_id: str
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None


class DesignTokens(BaseModel):
    """Top-level DESIGN__tokens.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: TokensMetadata
    token_source: Optional[TokenSource] = None
    imported_from: Optional[str] = None
    component_library: Optional[str] = None
    theme_modes: Optional[List[str]] = None
    color: Optional[Dict[str, Any]] = None
    typography: Optional[Dict[str, Any]] = None
    spacing: Optional[Dict[str, Any]] = None
    radius: Optional[Dict[str, Any]] = None
    elevation: Optional[Dict[str, Any]] = None
    motion: Optional[Dict[str, Any]] = None
    contrast_notes: Optional[str] = None


# =============================================================================
# DESIGN__assets.yaml models
# =============================================================================


class AssetGenerationBrief(_Block):
    target_modality: Optional[AssetModality] = None
    recommended_tools: Optional[List[str]] = None
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    style_anchors: Optional[List[str]] = None
    technical_constraints: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    variation_notes: Optional[str] = None


class AssetSpec(_Block):
    id: Optional[str] = None  # AST-NNN
    asset_type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    format_hint: Optional[str] = None
    source: Optional[AssetSource] = None
    traces_ux_surfaces: Optional[List[str]] = None
    references_entities: Optional[List[str]] = None
    generation_brief: Optional[AssetGenerationBrief] = None


class AssetsMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    design_assets_version: str
    last_updated: str
    generated_by: str = "sdlc-design"
    session_id: str
    status: Literal["draft", "complete"] = "draft"
    changelog: Optional[List[str]] = None


class DesignAssets(BaseModel):
    """Top-level DESIGN__assets.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: AssetsMetadata
    asset_taxonomy: Optional[List[str]] = None
    render_pipeline: Optional[str] = None
    style_guide: Optional[str] = None
    assets: Optional[List[AssetSpec]] = None


# =============================================================================
# Helpers
# =============================================================================


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


def _is_pure_headless(fs: Optional[List[FunctionalStructure]]) -> bool:
    return bool(fs) and all(m == FunctionalStructure.headless for m in fs)


def _has(fs: Optional[List[FunctionalStructure]], member: FunctionalStructure) -> bool:
    return bool(fs) and member in fs


# A "scope" is the single top-level product, or one entry under products.<slug>.
# slug is None for single-product mode.
Scope = Tuple[str, object, Optional[str]]


def scopes_of(design: Design) -> List[Scope]:
    if design.metadata.monorepo and design.products:
        return [
            (f"products.{slug}.", product, slug)
            for slug, product in design.products.items()
        ]
    return [("", design, None)]


# =============================================================================
# Required-field checks
# =============================================================================

# DESIGN.yaml required paths for any non-pure-headless scope.
DESIGN_VISUAL_REQUIRED: List[str] = [
    "aesthetic_direction.style_family",
    "aesthetic_direction.mood_keywords",
]
TOKENS_REQUIRED: List[str] = ["token_source", "theme_modes", "color", "typography", "spacing"]
ASSETS_REQUIRED: List[str] = ["asset_taxonomy", "assets"]
BRIEF_REQUIRED: List[str] = [
    "target_modality",
    "recommended_tools",
    "prompt",
    "style_anchors",
    "acceptance_criteria",
]


def check_design_required(design: Design) -> List[str]:
    missing: List[str] = []
    for label, scope, _slug in scopes_of(design):
        fs = getattr(scope, "functional_structure", None)
        if _is_empty(fs):
            missing.append(f"{label}functional_structure")
            continue  # nothing else can be judged without the axes
        if not _is_pure_headless(fs):
            for path in DESIGN_VISUAL_REQUIRED:
                if _is_empty(_get_dotted(scope, path)):
                    missing.append(f"{label}{path}")
            # requires_custom_assets is a bool — None means unfilled (False is OK)
            ad = getattr(scope, "aesthetic_direction", None)
            if ad is None or getattr(ad, "requires_custom_assets", None) is None:
                missing.append(f"{label}aesthetic_direction.requires_custom_assets")
    return missing


def check_tokens_required(tokens: DesignTokens, label: str) -> List[str]:
    return [f"{label}: {p}" for p in TOKENS_REQUIRED if _is_empty(_get_dotted(tokens, p))]


def check_assets_required(assets: DesignAssets, label: str) -> List[str]:
    missing = [f"{label}: {p}" for p in ASSETS_REQUIRED if _is_empty(_get_dotted(assets, p))]
    for i, a in enumerate(assets.assets or []):
        where = f"{label}: assets[{i}]"
        if _is_empty(a.id):
            missing.append(f"{where}.id")
        if _is_empty(a.asset_type):
            missing.append(f"{where}.asset_type")
        if _is_empty(a.name):
            missing.append(f"{where}.name")
        if _is_empty(a.description):
            missing.append(f"{where}.description")
        if _is_empty(a.source):
            missing.append(f"{where}.source")
        # A to-be-generated asset that *has* a brief must have it fully filled.
        if a.source == AssetSource.to_be_generated and a.generation_brief is not None:
            for p in BRIEF_REQUIRED:
                if _is_empty(_get_dotted(a.generation_brief, p)):
                    missing.append(f"{where}.generation_brief.{p}")
    return missing


# =============================================================================
# ID-prefix format checks
# =============================================================================


def _check_list_prefix(
    values: Optional[List[str]], pattern: re.Pattern[str], expected: str, where: str
) -> List[str]:
    if not values:
        return []
    errors: List[str] = []
    for v in values:
        if not isinstance(v, str) or not pattern.match(v.strip()):
            errors.append(f"{where}: '{v}' does not match {expected}")
    return errors


def check_design_id_prefixes(design: Design) -> List[str]:
    errors: List[str] = []
    for i, w in enumerate(design.design_warnings or []):
        if not isinstance(w, str) or not WRN_ITEM_RE.match(w.strip()):
            errors.append(f"design_warnings[{i}]: '{w}' must match 'WRN-NNN: <message>'")
    for label, scope, _slug in scopes_of(design):
        errors.extend(
            _check_list_prefix(
                getattr(scope, "implements_requirements", None),
                FR_OR_NFR_ID_RE,
                "'FR-NNN' or 'NFR-NNN'",
                f"{label}implements_requirements",
            )
        )
        errors.extend(
            _check_list_prefix(
                getattr(scope, "traces_ux_surfaces", None),
                SCR_ID_RE,
                "'SCR-NNN'",
                f"{label}traces_ux_surfaces",
            )
        )
        overrides = getattr(scope, "surface_overrides", None)
        if overrides:
            for key in overrides:
                if not isinstance(key, str) or not SCR_ID_RE.match(key.strip()):
                    errors.append(
                        f"{label}surface_overrides: key '{key}' must be an 'SCR-NNN' id"
                    )
    return errors


def check_assets_id_prefixes(assets: DesignAssets, label: str) -> List[str]:
    errors: List[str] = []
    for i, a in enumerate(assets.assets or []):
        where = f"{label}: assets[{i}]"
        if a.id is not None and not AST_ID_RE.match(a.id.strip()):
            errors.append(f"{where}.id: '{a.id}' must match 'AST-NNN'")
        errors.extend(
            _check_list_prefix(a.traces_ux_surfaces, SCR_ID_RE, "'SCR-NNN'", f"{where}.traces_ux_surfaces")
        )
        errors.extend(
            _check_list_prefix(a.references_entities, ENT_ID_RE, "'ENT-NNN'", f"{where}.references_entities")
        )
    return errors


def check_asset_type_taxonomy(assets: DesignAssets, label: str) -> List[str]:
    """Soft check: asset_type should be one of asset_taxonomy. Advisory only."""
    taxonomy = set(assets.asset_taxonomy or [])
    if not taxonomy:
        return []
    soft: List[str] = []
    for i, a in enumerate(assets.assets or []):
        if a.asset_type and a.asset_type not in taxonomy:
            soft.append(
                f"{label}: assets[{i}].asset_type '{a.asset_type}' is not in asset_taxonomy "
                f"{sorted(taxonomy)}"
            )
    return soft


# =============================================================================
# Sub-file discovery + composition + coverage
# =============================================================================


def discover_sub_files(design_path: Path) -> Dict[Tuple[str, Optional[str]], Path]:
    """Map (kind, slug) -> path for every DESIGN__*.yaml sibling.
    kind ∈ {"tokens","assets"}; slug is None (single-product) or the product slug."""
    out: Dict[Tuple[str, Optional[str]], Path] = {}
    for p in sorted(design_path.parent.glob("DESIGN__*.yaml")):
        middle = p.name[len("DESIGN__"):-len(".yaml")]
        for kind in ("tokens", "assets"):
            if middle == kind:
                out[(kind, None)] = p
            elif middle.endswith(f"__{kind}"):
                out[(kind, middle[: -len(f"__{kind}")])] = p
    return out


def check_composition(
    design: Design, sub_files: Dict[Tuple[str, Optional[str]], Path]
) -> List[str]:
    """Composition consistency, per scope. Returns error strings."""
    errors: List[str] = []
    for label, scope, slug in scopes_of(design):
        fs = getattr(scope, "functional_structure", None)
        if _is_empty(fs):
            continue
        # headless exclusivity
        if _has(fs, FunctionalStructure.headless) and len(fs) > 1:
            errors.append(
                f"{label}functional_structure: 'headless' is exclusive and cannot "
                f"co-occur with token_based_ui/asset_pipeline (got {[m.value for m in fs]})"
            )
        ad = getattr(scope, "aesthetic_direction", None)
        sub = getattr(scope, "sub_artifacts", None)

        # aesthetic_direction present unless purely headless
        if not _is_pure_headless(fs):
            if ad is None or _is_empty(getattr(ad, "style_family", None)):
                errors.append(
                    f"{label}aesthetic_direction is required when the structure is not "
                    f"purely headless"
                )

        needs_tokens = _has(fs, FunctionalStructure.token_based_ui)
        requires_assets = _has(fs, FunctionalStructure.asset_pipeline) or bool(
            ad is not None and getattr(ad, "requires_custom_assets", None)
        )

        tokens_path = (sub.tokens if sub else None)
        assets_path = (sub.assets if sub else None)
        tokens_on_disk = (("tokens", slug) in sub_files)
        assets_on_disk = (("assets", slug) in sub_files)

        # tokens
        if needs_tokens:
            if not tokens_path:
                errors.append(f"{label}sub_artifacts.tokens must be set (token_based_ui selected)")
            if not tokens_on_disk:
                errors.append(
                    f"{label}token_based_ui selected but no DESIGN__tokens.yaml found on disk"
                )
        else:
            if tokens_path:
                errors.append(
                    f"{label}sub_artifacts.tokens is set but token_based_ui is not in "
                    f"functional_structure (orphan tokens reference)"
                )
            if tokens_on_disk:
                errors.append(
                    f"{label}a DESIGN__tokens.yaml exists but token_based_ui is not selected "
                    f"(orphan tokens file)"
                )

        # assets
        if requires_assets:
            if not assets_path:
                errors.append(
                    f"{label}sub_artifacts.assets must be set (asset_pipeline selected or "
                    f"requires_custom_assets is true)"
                )
            if not assets_on_disk:
                errors.append(
                    f"{label}assets required (asset_pipeline / requires_custom_assets) but no "
                    f"DESIGN__assets.yaml found on disk"
                )
        else:
            if assets_path:
                errors.append(
                    f"{label}sub_artifacts.assets is set but neither asset_pipeline nor "
                    f"requires_custom_assets applies (orphan assets reference)"
                )
            if assets_on_disk:
                errors.append(
                    f"{label}a DESIGN__assets.yaml exists but neither asset_pipeline nor "
                    f"requires_custom_assets applies (orphan assets file)"
                )
    return errors


def check_asset_brief_coverage(
    design: Design, assets_by_slug: Dict[Optional[str], DesignAssets]
) -> List[str]:
    """Trace-or-defer: every to_be_generated asset has a brief OR is deferred via
    a WRN entry in DESIGN.yaml.design_warnings that names its AST id."""
    deferred_ids = set()
    for w in design.design_warnings or []:
        if isinstance(w, str):
            deferred_ids.update(AST_ANYWHERE_RE.findall(w))

    uncovered: List[str] = []
    for slug, assets in assets_by_slug.items():
        label = (
            "DESIGN__assets.yaml" if slug is None else f"DESIGN__{slug}__assets.yaml"
        )
        for i, a in enumerate(assets.assets or []):
            if a.source == AssetSource.to_be_generated and a.generation_brief is None:
                aid = (a.id or "").strip()
                if aid and aid in deferred_ids:
                    continue  # explicitly deferred — counts as covered
                uncovered.append(
                    f"{label}: assets[{i}] ({aid or 'no-id'}) is to_be_generated but has no "
                    f"generation_brief and no WRN deferral"
                )
    return uncovered


# =============================================================================
# File loading / orchestration
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
    out: List[str] = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()))
        out.append(f"{loc}: {e.get('msg', 'invalid')}")
    return out


def validate_all(design_path: Path) -> int:
    # 1) DESIGN.yaml
    raw, err = _load_yaml(design_path)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    try:
        design = Design.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] DESIGN.yaml FAILED schema validation ({design_path})\n")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    # 2) sub-files
    sub_files = discover_sub_files(design_path)
    tokens_by_slug: Dict[Optional[str], DesignTokens] = {}
    assets_by_slug: Dict[Optional[str], DesignAssets] = {}
    for (kind, slug), p in sub_files.items():
        s_raw, s_err = _load_yaml(p)
        if s_err:
            print(f"ERROR: {s_err}", file=sys.stderr)
            return 2
        try:
            if kind == "tokens":
                tokens_by_slug[slug] = DesignTokens.model_validate(s_raw)
            else:
                assets_by_slug[slug] = DesignAssets.model_validate(s_raw)
        except ValidationError as e:
            print(f"[FAIL] {p.name} FAILED schema validation\n")
            for line in _format_pydantic_errors(e):
                print(f"  - {line}")
            return 1

    # 3) required-field checks
    missing = check_design_required(design)
    for slug, t in tokens_by_slug.items():
        lbl = "DESIGN__tokens.yaml" if slug is None else f"DESIGN__{slug}__tokens.yaml"
        missing.extend(check_tokens_required(t, lbl))
    for slug, a in assets_by_slug.items():
        lbl = "DESIGN__assets.yaml" if slug is None else f"DESIGN__{slug}__assets.yaml"
        missing.extend(check_assets_required(a, lbl))

    # 4) ID-prefix format checks
    id_errors = check_design_id_prefixes(design)
    soft_warnings: List[str] = []
    for slug, a in assets_by_slug.items():
        lbl = "DESIGN__assets.yaml" if slug is None else f"DESIGN__{slug}__assets.yaml"
        id_errors.extend(check_assets_id_prefixes(a, lbl))
        soft_warnings.extend(check_asset_type_taxonomy(a, lbl))

    # 5) composition consistency
    comp_errors = check_composition(design, sub_files)

    # 6) asset-brief coverage
    uncovered = check_asset_brief_coverage(design, assets_by_slug)

    status = design.metadata.status
    n_tokens, n_assets = len(tokens_by_slug), len(assets_by_slug)
    blocking = bool(missing or id_errors or comp_errors or uncovered)

    def _dump(title: str, items: List[str]) -> None:
        if items:
            print(f"\n{len(items)} {title}:")
            for m in items:
                print(f"  - {m}")

    if status == "complete":
        if blocking:
            print(f"[FAIL] DESIGN.yaml claims status 'complete' but has errors ({design_path})")
            _dump("required field(s) missing", missing)
            _dump("composition error(s)", comp_errors)
            _dump("ID-prefix format violation(s)", id_errors)
            _dump("uncovered to-be-generated asset(s)", uncovered)
            _dump("advisory (asset_type not in taxonomy)", soft_warnings)
            return 1
        print(
            f"[OK] DESIGN.yaml is valid and complete ({design_path}); "
            f"{n_tokens} token file(s), {n_assets} asset file(s)."
        )
        _dump("advisory (asset_type not in taxonomy)", soft_warnings)
        return 0

    # status == "draft"
    print(
        f"[DRAFT] DESIGN.yaml is a draft ({design_path}); "
        f"{n_tokens} token file(s), {n_assets} asset file(s)."
    )
    _dump("required field(s) missing", missing)
    _dump("composition issue(s) (warnings in draft)", comp_errors)
    _dump("ID-prefix format violation(s) (warnings in draft)", id_errors)
    _dump("uncovered to-be-generated asset(s) (warnings in draft)", uncovered)
    _dump("advisory (asset_type not in taxonomy)", soft_warnings)
    if not blocking:
        print("\nAll required fields filled, composition consistent, coverage complete. "
              "Set metadata.status: complete when done.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate DESIGN.yaml + its conditional sub-files against the sdlc-design schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "DESIGN.yaml"),
        help="Path to DESIGN.yaml (default: ./docs/DESIGN.yaml). DESIGN__*.yaml "
        "siblings in the same directory are validated automatically.",
    )
    args = parser.parse_args(argv)
    return validate_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
