"""The example specs in examples/skillspec/ are complete, valid, and accepted by schema.json."""

import json

import pytest
from jsonschema import Draft202012Validator

from core.spec import SCHEMA_PATH, load_spec, validate_spec
from tests.spec.helpers import EXAMPLE_NAMES, EXAMPLES, as_json, changed, codes, example

TECHNICAL_AREAS = {"technology", "data"}


def test_the_three_required_examples_exist() -> None:
    assert {"ai-engineer", "marketing-strategist", "review-nda"} <= set(EXAMPLE_NAMES)


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_example_has_no_errors_and_no_warnings(name: str) -> None:
    result = validate_spec(example(name))
    assert result.issues == ()
    assert result.spec is not None and result.spec.skill.name == name  # file name = skill name


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_example_is_accepted_by_schema_json(name: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(as_json(example(name))))
    assert errors == []


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_example_loads_from_file(name: str) -> None:
    assert load_spec(EXAMPLES / f"{name}.yaml").skill.name == name


def test_technical_and_non_technical_coverage() -> None:
    areas = [example(n)["skill"]["domain"].split("/")[0] for n in EXAMPLE_NAMES]
    assert sum(a in TECHNICAL_AREAS for a in areas) >= 1
    assert sum(a not in TECHNICAL_AREAS for a in areas) >= 2


def test_examples_cover_role_task_and_high_risk() -> None:
    kinds = {example(n)["skill"]["kind"] for n in EXAMPLE_NAMES}
    assert {"role", "task"} <= kinds
    assert example("review-nda")["skill"]["domain"].startswith("legal/")


def test_high_risk_example_needs_its_disclaimer() -> None:
    def drop(d: dict[str, list[dict[str, str]]]) -> None:
        d["guardrails"] = [g for g in d["guardrails"] if g["category"] != "disclaimer"]

    assert codes(changed(drop, "review-nda")) == [("/guardrails", "high_risk_needs_disclaimer")]
