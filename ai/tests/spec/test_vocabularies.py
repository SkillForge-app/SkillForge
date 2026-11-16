"""The public closed vocabularies match the published schema and work as shared field types."""

import json
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from core.spec import (
    CAPABILITIES,
    DOMAIN_AREAS,
    GUARDRAIL_CATEGORIES,
    HIGH_RISK_AREAS,
    KINDS,
    RISK_LEVELS,
    SCHEMA_PATH,
    SEVERITIES,
    TARGETS,
    Capability,
    DomainArea,
    Kind,
    RiskLevel,
    Target,
)


@pytest.fixture(scope="module")
def defs() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return {**schema["$defs"], "SkillSpec": schema}


def test_constants_match_schema_json(defs: dict[str, Any]) -> None:
    def enum(model: str, field: str) -> list[str]:
        prop = defs[model]["properties"][field]
        values: list[str] = prop.get("items", prop)["enum"]
        return values

    assert list(KINDS) == enum("SkillMeta", "kind")
    assert list(CAPABILITIES) == enum("Tools", "optional")
    assert list(TARGETS) == enum("SkillSpec", "targets")
    assert list(SEVERITIES) == enum("Guardrail", "severity")
    assert list(GUARDRAIL_CATEGORIES) == enum("Guardrail", "category")
    domain_pattern = defs["SkillMeta"]["properties"]["domain"]["pattern"]
    assert f"(?:{'|'.join(DOMAIN_AREAS)})" in domain_pattern


def test_vocabularies_are_immutable_and_distinct() -> None:
    for values in (
        KINDS,
        DOMAIN_AREAS,
        RISK_LEVELS,
        CAPABILITIES,
        TARGETS,
        SEVERITIES,
        GUARDRAIL_CATEGORIES,
    ):
        assert isinstance(values, tuple)
        assert len(set(values)) == len(values)
    assert isinstance(HIGH_RISK_AREAS, frozenset)


def test_high_risk_areas_are_domain_areas() -> None:
    assert {"legal", "medical", "finance"} == HIGH_RISK_AREAS
    assert set(DOMAIN_AREAS) >= HIGH_RISK_AREAS


class _AnalyzedRequestLike(BaseModel):
    """How Track A's AnalyzedRequest (AI-05) is expected to reuse the types."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind
    domain_area: DomainArea
    risk: RiskLevel
    tools: list[Capability] = []
    targets: list[Target] = []


def test_literal_types_work_as_field_types_in_other_models() -> None:
    ok = _AnalyzedRequestLike(kind="task", domain_area="legal", risk="high", targets=["claude"])
    assert ok.domain_area in HIGH_RISK_AREAS
    with pytest.raises(ValidationError):
        _AnalyzedRequestLike(kind="persona", domain_area="legal", risk="high")
    with pytest.raises(ValidationError):
        _AnalyzedRequestLike(kind="task", domain_area="cooking", risk="low")
    with pytest.raises(ValidationError):
        _AnalyzedRequestLike(kind="task", domain_area="legal", risk="critical")


def test_risk_levels() -> None:
    assert RISK_LEVELS == ("low", "medium", "high")


def test_benchmark_uses_the_shared_risk_level() -> None:
    """The seed benchmark labels (AI-04) and AnalyzedRequest (A3) must use one vocabulary."""
    from evaluation.benchmarks.dataset import RequestLabels, SeedSkill

    for model in (SeedSkill, RequestLabels):
        annotation: object = model.model_fields["risk"].annotation
        assert annotation is RiskLevel, model.__name__  # the same object, not a copy
