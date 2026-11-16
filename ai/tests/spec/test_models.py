"""Per-field rules: strict models, unknown fields rejected, closed vocabularies, stable ids."""

from typing import Any

import pytest
from pydantic import ValidationError

from core.spec import SkillSpec, validate_spec
from tests.spec.helpers import FIXTURES, Spec, changed, codes, example, load_yaml, only_issue


def test_section_4_example_is_structurally_valid() -> None:
    """The spec's own example passes every per-field rule.

    The cross-field rules then catch the example's gap: `rag-patterns` cites src-2, which is
    never defined. Its output is also not linked to a procedure (a warning).
    """
    result = validate_spec(load_yaml(FIXTURES / "spec-section-4-example.yaml"))
    assert result.spec is not None
    assert [(i.path, i.code, i.severity) for i in result.issues] == [
        ("/knowledge/references/0/sources/1", "unknown_source", "error"),
        ("/outputs/0", "unused_output", "warning"),
    ]


# ---------------------------------------------------------------- unknown fields


def _add(location: tuple[Any, ...]) -> Spec:
    data = example()
    target: Any = data
    for part in location:
        target = target[part]
    target["bogus_field"] = 1
    return data


@pytest.mark.parametrize(
    "location",
    [
        (),
        ("skill",),
        ("triggers",),
        ("expertise",),
        ("procedures", 0),
        ("outputs", 0),
        ("guardrails", 0),
        ("tools",),
        ("knowledge",),
        ("knowledge", "references", 0),
        ("sources", 0),
        ("evaluation",),
    ],
)
def test_unknown_fields_are_rejected_at_every_level(location: tuple[Any, ...]) -> None:
    issue = only_issue(_add(location))
    expected_path = "".join(f"/{p}" for p in location) + "/bogus_field"
    assert (issue.path, issue.code) == (expected_path, "schema.unknown_field")


@pytest.mark.parametrize(
    ("change", "path", "suggestion"),
    [
        (lambda d: d["skill"].update(sumary=d["skill"].pop("summary")), "/skill/sumary", "summary"),
        (lambda d: d.update(guardrail=d.pop("guardrails")), "/guardrail", "guardrails"),
        (
            lambda d: d["procedures"][0].update(step=d["procedures"][0].pop("steps")),
            "/procedures/0/step",
            "steps",
        ),
    ],
)
def test_unknown_field_suggests_the_closest_name(change: Any, path: str, suggestion: str) -> None:
    issues = validate_spec(changed(change)).issues
    unknown = [i for i in issues if i.code == "schema.unknown_field"]
    assert unknown[0].path == path
    assert f'did you mean "{suggestion}"' in unknown[0].message


# ---------------------------------------------------------------- closed vocabularies and patterns


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda d: d["skill"].update(kind="persona"), "/skill/kind"),
        (lambda d: d["skill"].update(domain="cooking/baking"), "/skill/domain"),
        (lambda d: d["skill"].update(domain="technology"), "/skill/domain"),
        (lambda d: d.update(targets=["claude", "cursor"]), "/targets/1"),
        (lambda d: d["tools"].update(optional=["bash"]), "/tools/optional/0"),
        (lambda d: d["guardrails"][0].update(severity="high"), "/guardrails/0/severity"),
        (lambda d: d["guardrails"][0].update(category="legal"), "/guardrails/0/category"),
        (lambda d: d.update(spec_version="0.1"), "/spec_version"),
    ],
)
def test_closed_vocabularies(change: Any, path: str) -> None:
    issue = only_issue(changed(change))
    assert issue.path == path
    assert issue.code.startswith("schema.")


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda d: d["skill"].update(name="AI_Engineer"), "/skill/name"),
        (lambda d: d["skill"].update(name="ai--engineer"), "/skill/name"),
        (lambda d: d["skill"].update(name="a" * 65), "/skill/name"),
        (lambda d: d["skill"].update(version="v1"), "/skill/version"),
        (lambda d: d["procedures"][0].update(id="Design RAG"), "/procedures/0/id"),
        (lambda d: d["outputs"][0].update(template="design-doc.md"), "/outputs/0/template"),
        (
            lambda d: d["outputs"][0].update(template="templates/../secrets.md"),
            "/outputs/0/template",
        ),
        (
            lambda d: d["knowledge"]["references"][0].update(file="references/rag.txt"),
            "/knowledge/references/0/file",
        ),
        (lambda d: d["sources"][0].update(url="ftp://example.org/x"), "/sources/0/url"),
        (lambda d: d["sources"][0].update(retrieved="23/10/2026"), "/sources/0/retrieved"),
    ],
)
def test_patterns_ids_and_paths(change: Any, path: str) -> None:
    issue = only_issue(changed(change))
    assert issue.path == path


# ---------------------------------------------------------------- strictness


@pytest.mark.parametrize(("field", "path"), [("version", "/skill/version")])
def test_unquoted_yaml_numbers_are_rejected_with_a_hint(field: str, path: str) -> None:
    issue = only_issue(changed(lambda d: d["skill"].update({field: 1.0})))
    assert (issue.path, issue.code) == (path, "schema.string_type")
    assert "quote" in issue.message


def test_unquoted_spec_version_is_rejected() -> None:
    issue = only_issue(changed(lambda d: d.update(spec_version=0.2)))
    assert issue.path == "/spec_version"


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda d: d.update(targets=["claude", "claude"]), "/targets"),
        (lambda d: d["tools"].update(optional=["terminal", "terminal"]), "/tools/optional"),
        (
            lambda d: d["knowledge"]["references"][0].update(sources=["src-rag-paper"] * 2),
            "/knowledge/references/0/sources",
        ),
        (
            lambda d: d["procedures"][0].update(produces=["design-doc"] * 2),
            "/procedures/0/produces",
        ),
    ],
)
def test_duplicate_list_items(change: Any, path: str) -> None:
    issue = only_issue(changed(change))
    assert (issue.path, issue.code) == (path, "schema.duplicate_item")


@pytest.mark.parametrize(
    ("change", "path", "code"),
    [
        (lambda d: d.pop("evaluation"), "/evaluation", "schema.missing"),
        (lambda d: d.update(procedures=[]), "/procedures", "schema.too_short"),
        (lambda d: d["triggers"].update(use_when=[]), "/triggers/use_when", "schema.too_short"),
        (lambda d: d.update(targets=[]), "/targets", "schema.too_short"),
        (lambda d: d["skill"].update(summary="   "), "/skill/summary", "schema.string_too_short"),
    ],
)
def test_required_content(change: Any, path: str, code: str) -> None:
    assert codes(changed(change)) == [(path, code)]


def test_text_is_trimmed() -> None:
    spec = validate_spec(changed(lambda d: d["skill"].update(title="  AI Engineer  "))).spec
    assert spec is not None and spec.skill.title == "AI Engineer"


def test_optional_sections_have_defaults() -> None:
    def strip(d: Spec) -> None:
        for key in ("outputs", "guardrails", "tools", "knowledge", "sources"):
            d.pop(key)
        d["skill"]["kind"] = "task"
        for procedure in d["procedures"]:
            procedure.pop("produces")
            procedure.pop("uses")

    result = validate_spec(changed(strip))
    assert result.ok and result.spec is not None
    assert result.spec.tools.optional == [] and result.spec.knowledge.references == []


def test_models_are_frozen() -> None:
    spec = validate_spec(example()).spec
    assert spec is not None
    with pytest.raises(ValidationError):
        spec.skill.name = "other"  # type: ignore[misc]


def test_model_validate_json_is_the_strict_entry_point() -> None:
    spec = validate_spec(example()).spec
    assert spec is not None
    again = SkillSpec.model_validate_json(spec.model_dump_json())
    assert again == spec
