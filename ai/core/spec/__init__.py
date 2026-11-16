"""SkillSpec v0.2 (AI-01, contract B1): models, validator and the published schema.json.

    from core.spec import load_spec, validate_spec
    from core.spec import DomainArea, Kind, RiskLevel, HIGH_RISK_AREAS   # shared vocabularies

See docs/ai/skillspec.md.
"""

from core.spec.models import (
    CAPABILITIES,
    DOMAIN_AREAS,
    GUARDRAIL_CATEGORIES,
    HIGH_RISK_AREAS,
    KINDS,
    RISK_LEVELS,
    SCHEMA_PATH,
    SEVERITIES,
    SPEC_VERSION,
    TARGETS,
    Capability,
    DomainArea,
    GuardrailCategory,
    Kind,
    RiskLevel,
    Severity,
    SkillSpec,
    Target,
    json_schema,
    render_schema,
)
from core.spec.validator import (
    PLATFORM_LIMITS,
    Issue,
    SpecValidationError,
    ValidationResult,
    draft_description,
    load_spec,
    schema_issues,
    validate_spec,
)

__all__ = [
    "CAPABILITIES",
    "DOMAIN_AREAS",
    "GUARDRAIL_CATEGORIES",
    "HIGH_RISK_AREAS",
    "KINDS",
    "RISK_LEVELS",
    "PLATFORM_LIMITS",
    "SCHEMA_PATH",
    "SEVERITIES",
    "SPEC_VERSION",
    "TARGETS",
    "Capability",
    "DomainArea",
    "GuardrailCategory",
    "Issue",
    "Kind",
    "RiskLevel",
    "Severity",
    "SkillSpec",
    "SpecValidationError",
    "Target",
    "ValidationResult",
    "draft_description",
    "json_schema",
    "load_spec",
    "render_schema",
    "schema_issues",
    "validate_spec",
]
