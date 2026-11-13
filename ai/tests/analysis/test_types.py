"""Contract A3: AnalyzedRequest rules, the exported schema, the examples and the fake fixture."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from core.analysis import SCHEMA_PATH, AnalyzedRequest, RequestAnalysis, render_schema
from core.analysis.__main__ import main
from core.spec import RiskLevel

AI_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((AI_ROOT / "examples" / "analyzed-request").glob("*.json"))
FIXTURE = AI_ROOT / "tests" / "fixtures" / "llm" / "analysis" / "request.json"
QUESTIONS = [
    {"id": "q1", "text": "Who is it for?", "about": "audience"},
    {"id": "q2", "text": "What should it produce?", "about": "outputs"},
    {"id": "q3", "text": "Which platforms?", "about": "platforms"},
]


def base(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "request": "help me hire people",
        "kind": "role",
        "domain": "hr/recruiting",
        "risk": "medium",
        "summary": "A recruiting skill.",
        "needs_clarification": True,
        "questions": QUESTIONS,
        "analyzer": {"prompt_id": "analysis/request", "prompt_version": 1},
    }
    data.update(changes)
    return data


def make(**changes: Any) -> AnalyzedRequest:
    return AnalyzedRequest.model_validate_json(json.dumps(base(**changes)))


def test_valid_first_and_second_pass() -> None:
    first = make()
    assert first.needs_clarification and first.domain_area == "hr"
    answers = [{"question_id": "q1", "text": "Warehouse staff"}, {"question_id": "q2"}]
    second = make(needs_clarification=False, answers=answers)
    assert second.answers[1].text is None  # a skipped question


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"questions": QUESTIONS[:2]}, "3 to 5 questions"),
        ({"questions": []}, "open questions"),
        ({"needs_clarification": False}, "must be true"),
        ({"answers": [{"question_id": "q1", "text": "x"}]}, "no answers yet"),
        (
            {"needs_clarification": False, "answers": [{"question_id": "q5", "text": "x"}]},
            "not asked",
        ),
        (
            {
                "needs_clarification": False,
                "answers": [{"question_id": "q1", "text": "a"}, {"question_id": "q1", "text": "b"}],
            },
            "one answer per question",
        ),
        ({"questions": [QUESTIONS[0]] * 3}, "unique"),
    ],
)
def test_question_and_answer_rules(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "persona"},
        {"domain": "cooking/baking"},
        {"risk": "critical"},
        {"targets": ["cursor"]},
        {"targets": ["claude", "claude"]},
        {"colour": "blue"},
        {"skill_name": "Not Kebab"},
    ],
)
def test_strict_fields_and_shared_vocabularies(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make(**changes)


def test_risk_uses_the_shared_vocabulary() -> None:
    annotation: object = AnalyzedRequest.model_fields["risk"].annotation
    assert annotation is RiskLevel


def test_schema_is_current_and_agrees_with_pydantic() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render_schema()
    assert main(["export-schema", "--check"]) == 0
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(base())) == []
    for bad in ({"kind": "persona"}, {"colour": "blue"}, {"targets": ["claude", "claude"]}):
        assert list(validator.iter_errors(base(**bad))), bad


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_are_valid(path: Path) -> None:
    analyzed = AnalyzedRequest.model_validate_json(path.read_text(encoding="utf-8"))
    assert analyzed.skill_name == path.stem


def test_three_examples_including_a_clarified_one() -> None:
    examples = [AnalyzedRequest.model_validate_json(p.read_text("utf-8")) for p in EXAMPLES]
    assert len(examples) == 3
    assert any(e.answers for e in examples)


def test_fake_fixture_is_a_valid_llm_answer() -> None:
    RequestAnalysis.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def test_examples_carry_a_safety_clearance() -> None:
    for path in EXAMPLES:
        analyzed = AnalyzedRequest.model_validate_json(path.read_text(encoding="utf-8"))
        assert analyzed.safety is not None, path.stem
        if analyzed.domain_area in ("legal", "medical", "finance"):
            assert "professional_disclaimer" in analyzed.safety.conditions
