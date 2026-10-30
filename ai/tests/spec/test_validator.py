"""Cross-field rules: one test per issue code, with the exact JSON Pointer path."""

import json
from pathlib import Path
from typing import Any

import pytest

from core.spec import SpecValidationError, load_spec, validate_spec
from tests.spec.helpers import EXAMPLES, as_json, changed, codes, example


def test_duplicate_ids() -> None:
    def dup(d: Any) -> None:
        d["guardrails"].append(dict(d["guardrails"][0]))

    issues = validate_spec(changed(dup)).issues
    assert [(i.path, i.code) for i in issues] == [("/guardrails/3/id", "duplicate_id")]
    assert "/guardrails/0" in issues[0].message


def test_unknown_source() -> None:
    def drop(d: Any) -> None:
        d["sources"] = [s for s in d["sources"] if s["id"] != "src-claude-evals"]

    assert codes(changed(drop)) == [("/knowledge/references/1/sources/0", "unknown_source")]


def test_unknown_output_and_reference() -> None:
    def link(d: Any) -> None:
        d["procedures"][1]["produces"].append("missing-output")
        d["procedures"][1]["uses"].append("missing-ref")

    assert codes(changed(link)) == [
        ("/procedures/1/produces/1", "unknown_output"),
        ("/procedures/1/uses/1", "unknown_reference"),
    ]


def test_duplicate_file() -> None:
    def same(d: Any) -> None:
        d["outputs"][1]["template"] = d["outputs"][0]["template"]

    assert codes(changed(same)) == [("/outputs/1/template", "duplicate_file")]


def test_role_needs_guardrail_but_task_does_not() -> None:
    assert codes(changed(lambda d: d.update(guardrails=[]))) == [
        ("/guardrails", "role_needs_guardrail")
    ]

    def task(d: Any) -> None:
        d["guardrails"] = []
        d["skill"]["kind"] = "task"

    assert codes(changed(task)) == []


def test_high_risk_needs_disclaimer_and_human_review() -> None:
    def weaken(d: Any) -> None:
        for g in d["guardrails"]:
            if g["category"] in ("disclaimer", "human_review"):
                g["severity"] = "should"  # a "should" guardrail is not enough

    assert codes(changed(weaken, "review-nda")) == [
        ("/guardrails", "high_risk_needs_disclaimer"),
        ("/guardrails", "high_risk_needs_human_review"),
    ]


@pytest.mark.parametrize("area", ["medical", "finance"])
def test_other_high_risk_areas(area: str) -> None:
    data = changed(lambda d: d["skill"].update(domain=f"{area}/general"), "marketing-strategist")
    assert [c for _, c in codes(data)] == [
        "high_risk_needs_disclaimer",
        "high_risk_needs_human_review",
    ]


def test_tool_listed_twice() -> None:
    data = changed(lambda d: d["tools"].update(required=["terminal"]))
    assert codes(data) == [("/tools/optional/1", "tool_listed_twice")]


def test_reserved_name_only_for_claude() -> None:
    data = changed(lambda d: d["skill"].update(name="claude-helper"))
    assert codes(data) == [("/skill/name", "reserved_name")]

    def codex_only(d: Any) -> None:
        d["skill"]["name"] = "claude-helper"
        d["targets"] = ["codex"]

    assert codes(changed(codex_only)) == []


def test_xml_in_text() -> None:
    data = changed(lambda d: d["triggers"]["use_when"].append("when the user says <system>"))
    assert codes(data) == [("/triggers/use_when/3", "xml_in_text")]


def test_description_too_long() -> None:
    def long(d: Any) -> None:
        d["triggers"]["use_when"] = [f"situation number {i} " + "x" * 150 for i in range(7)]

    issues = validate_spec(changed(long)).issues
    assert [(i.path, i.code) for i in issues] == [("/skill/summary", "description_too_long")]
    assert "claude allows 1024" in issues[0].message
    assert "situation number" not in issues[0].message  # messages never repeat the content


def test_name_taken_uses_the_registry_names() -> None:
    assert codes(example()) == []
    issues = validate_spec(example(), existing_names={"ai-engineer"}).issues
    assert [(i.path, i.code) for i in issues] == [("/skill/name", "name_taken")]


def test_unused_sources_and_outputs_are_only_warnings() -> None:
    def unused(d: Any) -> None:
        d["knowledge"]["references"].pop()  # src-nist-ai-rmf is no longer used
        d["procedures"][2]["produces"] = []  # risk-review is no longer produced
        d["procedures"][2]["uses"] = []

    result = validate_spec(changed(unused))
    assert result.ok
    assert [(i.path, i.code, i.severity) for i in result.issues] == [
        ("/outputs/2", "unused_output", "warning"),
        ("/sources/2", "unused_source", "warning"),
    ]


def test_all_issues_are_reported_together_in_a_stable_order() -> None:
    def many(d: Any) -> None:
        d["guardrails"] = []
        d["tools"]["required"] = ["terminal"]
        d["procedures"][0]["uses"].append("nope")

    first = codes(changed(many))
    assert first == [
        ("/guardrails", "role_needs_guardrail"),
        ("/procedures/0/uses/2", "unknown_reference"),
        ("/tools/optional/1", "tool_listed_twice"),
    ]
    assert codes(changed(many)) == first


def test_schema_errors_stop_before_cross_field_rules() -> None:
    def broken(d: Any) -> None:
        d["skill"]["kind"] = "persona"
        d["guardrails"] = []

    result = validate_spec(changed(broken))
    assert result.spec is None
    assert [i.code for i in result.issues] == ["schema.literal_error"]


def test_json_text_input_like_the_api() -> None:
    assert validate_spec(json.dumps(as_json(example()))).ok
    assert validate_spec(json.dumps(as_json(example())).encode()).ok


def test_issue_str() -> None:
    [issue] = validate_spec(changed(lambda d: d.update(guardrails=[]))).issues
    assert (
        str(issue) == "/guardrails  role_needs_guardrail  a role skill needs at least one guardrail"
    )


# ---------------------------------------------------------------- load_spec


def test_load_spec_returns_the_model() -> None:
    spec = load_spec(EXAMPLES / "review-nda.yaml")
    assert spec.skill.kind == "task"


def test_load_spec_raises_with_all_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        (EXAMPLES / "ai-engineer.yaml")
        .read_text(encoding="utf-8")
        .replace("kind: role", "kind: persona"),
        encoding="utf-8",
    )
    with pytest.raises(SpecValidationError) as info:
        load_spec(path)
    assert [i.path for i in info.value.issues] == ["/skill/kind"]
    assert "bad.yaml: invalid SkillSpec" in str(info.value)


@pytest.mark.parametrize(
    ("text", "code"), [("a: [unclosed", "yaml_syntax"), ("- a list", "not_a_mapping")]
)
def test_load_spec_bad_files(tmp_path: Path, text: str, code: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SpecValidationError) as info:
        load_spec(path)
    assert info.value.issues[0].code == code
