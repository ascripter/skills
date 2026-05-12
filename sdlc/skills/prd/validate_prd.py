"""Validate PRD.yaml against the canonical sdlc-prd schema.

Run from the project root:

    python .claude/skills/sdlc-prd/validate_prd.py
    python .claude/skills/sdlc-prd/validate_prd.py --path some/other/PRD.yaml

Exit codes:
    0 — schema valid; either status='complete' with all required fields filled,
        or status='draft' (with or without missing required fields).
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing.
    2 — could not read or parse the file (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml)
"""

from __future__ import annotations

import argparse
import sys
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional

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
# Enums (kept in lockstep with PRD.schema.yaml)
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class ExpertiseLevel(str, Enum):
    novice = "novice"
    intermediate = "intermediate"
    expert = "expert"
    mixed = "mixed"


class Scalability(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"
    hyperscale = "hyperscale"


class Reliability(str, Enum):
    best_effort = "best_effort"
    high = "high"
    mission_critical = "mission_critical"


class Accessibility(str, Enum):
    none_yet = "none_yet"
    wcag_aa = "wcag_aa"
    wcag_aaa = "wcag_aaa"


class PrimaryLanguage(str, Enum):
    python = "python"
    typescript = "typescript"
    javascript = "javascript"
    go = "go"
    rust = "rust"
    java = "java"
    csharp = "csharp"
    ruby = "ruby"
    other = "other"
    undecided = "undecided"


class RuntimePlatform(str, Enum):
    web = "web"
    mobile_ios = "mobile_ios"
    mobile_android = "mobile_android"
    desktop = "desktop"
    cli = "cli"
    server = "server"
    embedded = "embedded"
    browser_extension = "browser_extension"
    other = "other"
    undecided = "undecided"


class DeploymentTarget(str, Enum):
    cloud_aws = "cloud_aws"
    cloud_gcp = "cloud_gcp"
    cloud_azure = "cloud_azure"
    self_hosted = "self_hosted"
    on_prem = "on_prem"
    edge = "edge"
    serverless = "serverless"
    hybrid = "hybrid"
    undecided = "undecided"


class DataOwnership(str, Enum):
    user_owned = "user_owned"
    org_owned = "org_owned"
    platform_owned = "platform_owned"
    third_party = "third_party"
    mixed = "mixed"


class DataVolume(str, Enum):
    kilobytes = "kilobytes"
    megabytes = "megabytes"
    gigabytes = "gigabytes"
    terabytes = "terabytes"
    petabytes = "petabytes"
    unknown = "unknown"


class AuthModel(str, Enum):
    none = "none"
    api_key = "api_key"
    oauth2 = "oauth2"
    oidc = "oidc"
    saml = "saml"
    jwt = "jwt"
    session_cookie = "session_cookie"
    passkeys = "passkeys"
    custom = "custom"


class DataSensitivity(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"
    regulated = "regulated"


class Monetization(str, Enum):
    free = "free"
    freemium = "freemium"
    paid = "paid"
    subscription = "subscription"
    usage_based = "usage_based"
    enterprise = "enterprise"
    open_source = "open_source"
    internal_tool = "internal_tool"
    undecided = "undecided"


class LicenseType(str, Enum):
    proprietary = "proprietary"
    mit = "mit"
    apache_2 = "apache_2"
    gpl_v3 = "gpl_v3"
    agpl_v3 = "agpl_v3"
    bsd_3_clause = "bsd_3_clause"
    mpl_2 = "mpl_2"
    cc_by = "cc_by"
    cc_by_sa = "cc_by_sa"
    other = "other"
    undecided = "undecided"


# =============================================================================
# Theme models — declared in the canonical interview order from
# product-questions.yaml (required themes first, product_identity last among
# required, optional themes follow).
# =============================================================================

# Allow extra keys we haven't modeled yet (forward-compat for new question
# additions); reject unknown enum values strictly.
_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _ThemeBase(BaseModel):
    model_config = _BASE_CONFIG


class ProblemOpportunity(_ThemeBase):
    problem_statement: Optional[str] = None
    problem_statement_confidence: Optional[Confidence] = None
    who_has_pain: Optional[List[str]] = None
    who_has_pain_confidence: Optional[Confidence] = None
    current_workarounds: Optional[List[str]] = None
    current_workarounds_confidence: Optional[Confidence] = None
    why_now: Optional[str] = None


class UsersPersonas(_ThemeBase):
    primary_users: Optional[List[str]] = None
    primary_users_confidence: Optional[Confidence] = None
    secondary_users: Optional[List[str]] = None
    user_goals: Optional[List[str]] = None
    user_frustrations: Optional[List[str]] = None
    expertise_level: Optional[ExpertiseLevel] = None
    expertise_level_confidence: Optional[Confidence] = None


class UseCases(_ThemeBase):
    core_workflows: Optional[List[str]] = None
    primary_jobs_to_be_done: Optional[List[str]] = None
    secondary_jobs: Optional[List[str]] = None
    edge_cases: Optional[List[str]] = None


class FunctionalRequirements(_ThemeBase):
    must_have_features: Optional[List[str]] = None
    nice_to_have_features: Optional[List[str]] = None
    out_of_scope: Optional[List[str]] = None
    integrations_required: Optional[List[str]] = None
    integrations_required_confidence: Optional[Confidence] = None
    ai_features: Optional[List[str]] = None
    ai_features_confidence: Optional[Confidence] = None


class TechnicalConstraints(_ThemeBase):
    primary_language: Optional[PrimaryLanguage] = None
    primary_language_rationale: Optional[str] = None
    primary_language_confidence: Optional[Confidence] = None
    framework: Optional[List[str]] = None
    framework_confidence: Optional[Confidence] = None
    runtime_platform: Optional[RuntimePlatform] = None
    runtime_platform_rationale: Optional[str] = None
    runtime_platform_confidence: Optional[Confidence] = None
    deployment_target: Optional[DeploymentTarget] = None
    deployment_target_rationale: Optional[str] = None
    deployment_target_confidence: Optional[Confidence] = None
    existing_systems: Optional[List[str]] = None
    existing_systems_confidence: Optional[Confidence] = None
    browser_support: Optional[List[str]] = None


class ProductIdentity(_ThemeBase):
    idea_text: Optional[str] = None
    name: Optional[str] = None
    name_confidence: Optional[Confidence] = None
    slug: Optional[str] = None
    slug_confidence: Optional[Confidence] = None
    one_liner: Optional[str] = None
    one_liner_confidence: Optional[Confidence] = None
    tagline: Optional[str] = None
    vision: Optional[str] = None
    mission: Optional[str] = None


class NonFunctionalRequirements(_ThemeBase):
    performance_targets: Optional[List[str]] = None
    scalability: Optional[Scalability] = None
    scalability_confidence: Optional[Confidence] = None
    reliability: Optional[Reliability] = None
    reliability_confidence: Optional[Confidence] = None
    availability_sla: Optional[str] = None
    accessibility: Optional[Accessibility] = None
    other: Optional[List[str]] = None  # catch-all for any NFRs not captured above


class DataModel(_ThemeBase):
    key_entities: Optional[List[str]] = None
    data_ownership: Optional[DataOwnership] = None
    data_ownership_confidence: Optional[Confidence] = None
    data_volume_estimate: Optional[DataVolume] = None
    data_volume_estimate_confidence: Optional[Confidence] = None
    storage_preferences: Optional[List[str]] = None
    storage_preferences_rationale: Optional[str] = None
    storage_preferences_confidence: Optional[Confidence] = None


class SecurityCompliance(_ThemeBase):
    auth_model: Optional[AuthModel] = None
    auth_model_rationale: Optional[str] = None
    auth_model_confidence: Optional[Confidence] = None
    data_sensitivity: Optional[DataSensitivity] = None
    data_sensitivity_confidence: Optional[Confidence] = None
    regulatory_requirements: Optional[List[str]] = None
    regulatory_requirements_confidence: Optional[Confidence] = None
    encryption_at_rest: Optional[bool] = None
    audit_logging: Optional[bool] = None


class BusinessModel(_ThemeBase):
    monetization: Optional[Monetization] = None
    monetization_rationale: Optional[str] = None
    monetization_confidence: Optional[Confidence] = None
    pricing_model: Optional[str] = None
    license_type: Optional[LicenseType] = None
    license_type_rationale: Optional[str] = None
    license_type_confidence: Optional[Confidence] = None
    target_market: Optional[str] = None


class Stakeholders(_ThemeBase):
    product_owner: Optional[str] = None
    primary_contributors: Optional[List[str]] = None
    decision_maker: Optional[str] = None
    external_dependencies: Optional[List[str]] = None


class Milestones(_ThemeBase):
    mvp_scope: Optional[str] = None
    phases: Optional[List[str]] = None


class SuccessMetrics(_ThemeBase):
    primary_kpis: Optional[List[str]] = None
    acceptance_criteria: Optional[List[str]] = None
    definition_of_done: Optional[List[str]] = None
    user_satisfaction_target: Optional[str] = None


class RisksAssumptions(_ThemeBase):
    top_risks: Optional[List[str]] = None
    key_assumptions: Optional[List[str]] = None
    blockers: Optional[List[str]] = None
    dependencies: Optional[List[str]] = None


class OpenQuestions(_ThemeBase):
    undecided_decisions: Optional[List[str]] = None
    parking_lot: Optional[List[str]] = None


# =============================================================================
# Top-level models
# =============================================================================


class Metadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    prd_version: str
    last_updated: str  # ISO-8601 string; not parsed to datetime to keep YAML simple
    generated_by: str = "sdlc-prd"
    session_id: str
    monorepo: bool = False
    status: Literal["draft", "complete"] = "draft"


class Product(_ThemeBase):
    """One product's themes in interview order, used inside `products: <slug>: ...`."""

    problem_opportunity: Optional[ProblemOpportunity] = None
    users_personas: Optional[UsersPersonas] = None
    use_cases: Optional[UseCases] = None
    functional_requirements: Optional[FunctionalRequirements] = None
    technical_constraints: Optional[TechnicalConstraints] = None
    product_identity: Optional[ProductIdentity] = None
    non_functional_requirements: Optional[NonFunctionalRequirements] = None
    data_model: Optional[DataModel] = None
    security_compliance: Optional[SecurityCompliance] = None
    business_model: Optional[BusinessModel] = None
    stakeholders: Optional[Stakeholders] = None
    milestones: Optional[Milestones] = None
    success_metrics: Optional[SuccessMetrics] = None
    risks_assumptions: Optional[RisksAssumptions] = None
    open_questions: Optional[OpenQuestions] = None


class PRD(BaseModel):
    """Top-level PRD document.

    Single-product mode: theme blocks live at the top level; `products` is None.
    Multi-product mode:  `products` is a non-empty map; theme blocks are None.
    """

    model_config = ConfigDict(extra="allow")

    metadata: Metadata
    prd_warnings: List[str] = Field(default_factory=list)

    # Single-product theme blocks in interview order (mirror Product)
    problem_opportunity: Optional[ProblemOpportunity] = None
    users_personas: Optional[UsersPersonas] = None
    use_cases: Optional[UseCases] = None
    functional_requirements: Optional[FunctionalRequirements] = None
    technical_constraints: Optional[TechnicalConstraints] = None
    product_identity: Optional[ProductIdentity] = None
    non_functional_requirements: Optional[NonFunctionalRequirements] = None
    data_model: Optional[DataModel] = None
    security_compliance: Optional[SecurityCompliance] = None
    business_model: Optional[BusinessModel] = None
    stakeholders: Optional[Stakeholders] = None
    milestones: Optional[Milestones] = None
    success_metrics: Optional[SuccessMetrics] = None
    risks_assumptions: Optional[RisksAssumptions] = None
    open_questions: Optional[OpenQuestions] = None

    # Multi-product mode
    products: Optional[Dict[str, Product]] = None

    @model_validator(mode="after")
    def _check_mode(self) -> "PRD":
        single_themes = [
            self.problem_opportunity,
            self.users_personas,
            self.use_cases,
            self.functional_requirements,
            self.technical_constraints,
            self.product_identity,
            self.non_functional_requirements,
            self.data_model,
            self.security_compliance,
            self.business_model,
            self.stakeholders,
            self.milestones,
            self.success_metrics,
            self.risks_assumptions,
            self.open_questions,
        ]
        any_single = any(t is not None for t in single_themes)

        if self.metadata.monorepo:
            if not self.products:
                raise ValueError("metadata.monorepo is true but `products` is missing or empty")
            if any_single:
                raise ValueError(
                    "monorepo mode set but top-level theme blocks are present; "
                    "in monorepo mode all themes must live under `products.<slug>`"
                )
        else:
            if self.products:
                raise ValueError(
                    "`products` is set but metadata.monorepo is false; "
                    "either set monorepo: true or move themes to top level"
                )
        return self


# =============================================================================
# Required-field check — separate from schema validation so drafts can be
# saved without failing. Validation behavior depends on metadata.status.
# =============================================================================

# Path is dotted relative to a Product (or top level in single-product mode).
REQUIRED_PATHS: List[str] = [
    "problem_opportunity.problem_statement",
    "users_personas.primary_users",
    "use_cases.core_workflows",
    "functional_requirements.must_have_features",
    "technical_constraints.primary_language",
    "technical_constraints.runtime_platform",
    "product_identity.name",
    "product_identity.one_liner",
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


def check_required(prd: PRD) -> List[str]:
    """Return list of missing required field paths.

    In monorepo mode, paths are prefixed with `products.<slug>.`.
    """
    missing: List[str] = []

    def _check(scope_label: str, root: object) -> None:
        for path in REQUIRED_PATHS:
            if _is_empty(_get_dotted(root, path)):
                missing.append(f"{scope_label}{path}")

    if prd.metadata.monorepo and prd.products:
        for slug, product in prd.products.items():
            _check(f"products.{slug}.", product)
    else:
        _check("", prd)

    return missing


# =============================================================================
# CLI
# =============================================================================


def _format_pydantic_errors(err: ValidationError) -> List[str]:
    formatted: List[str] = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()))
        msg = e.get("msg", "invalid")
        formatted.append(f"{loc}: {msg}")
    return formatted


def validate_file(path: Path) -> int:
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"ERROR: YAML parse error in {path}:\n  {e}", file=sys.stderr)
        return 2

    if raw is None:
        print(f"ERROR: {path} is empty", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print(
            f"ERROR: {path} top level must be a mapping, got {type(raw).__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        prd = PRD.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] PRD.yaml FAILED schema validation ({path})\n")
        print("Errors:")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    missing = check_required(prd)
    status = prd.metadata.status

    if status == "complete":
        if missing:
            print(
                f"[FAIL] PRD.yaml claims status 'complete' but {len(missing)} "
                f"required field(s) are missing ({path})\n"
            )
            print("Missing required fields:")
            for m in missing:
                print(f"  - {m}")
            return 1
        print(f"[OK] PRD.yaml is valid and complete ({path})")
        return 0

    # status == "draft"
    if missing:
        print(
            f"[DRAFT] PRD.yaml is a draft — {len(missing)} required field(s) " f"missing ({path})"
        )
        print("Missing required fields (fill in and set metadata.status: complete when done):")
        for m in missing:
            print(f"  - {m}")
    else:
        print(
            f"[DRAFT] PRD.yaml is a draft — all required fields filled. "
            f"Set metadata.status: complete when done ({path})"
        )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate PRD.yaml against the sdlc-prd schema.")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "PRD.yaml"),
        help="Path to PRD.yaml (default: ./docs/PRD.yaml)",
    )
    args = parser.parse_args(argv)
    return validate_file(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
