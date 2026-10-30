"""schema.json is current, valid JSON Schema, and enforces the same per-field rules as Pydantic.

BE and FE build against schema.json, so for every structural mistake both must agree.
"""

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from core.spec import SCHEMA_PATH, SPEC_VERSION, render_schema, validate_spec
from core.spec.__main__ import main
from tests.spec.helpers import EXAMPLES, as_json, changed


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return data


def test_committed_schema_is_current() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render_schema(), (
        "schema.json is out of date: run `python -m core.spec export-schema`"
    )


def test_schema_is_valid_draft_2020_12(schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["x-spec-version"] == SPEC_VERSION
    assert schema["additionalProperties"] is False
    assert all(d.get("additionalProperties") is False for d in schema["$defs"].values())


STRUCTURAL_MISTAKES = {
    "unknown field": lambda d: d["skill"].update(titel="x"),
    "unknown nested field": lambda d: d["procedures"][0].update(owner="me"),
    "missing section": lambda d: d.pop("triggers"),
    "bad kind": lambda d: d["skill"].update(kind="persona"),
    "bad domain area": lambda d: d["skill"].update(domain="cooking/baking"),
    "bad name": lambda d: d["skill"].update(name="AI Engineer"),
    "vendor tool name": lambda d: d["tools"].update(optional=["Bash"]),
    "unknown target": lambda d: d.update(targets=["cursor"]),
    "duplicate target": lambda d: d.update(targets=["claude", "claude"]),
    "no procedures": lambda d: d.update(procedures=[]),
    "template outside templates/": lambda d: d["outputs"][0].update(template="x.md"),
    "number instead of text": lambda d: d["skill"].update(version=1.0),
    "wrong spec version": lambda d: d.update(spec_version="0.1"),
}


@pytest.mark.parametrize("mistake", STRUCTURAL_MISTAKES)
def test_pydantic_and_schema_json_reject_the_same_mistakes(
    schema: dict[str, Any], mistake: str
) -> None:
    data = changed(STRUCTURAL_MISTAKES[mistake])
    assert validate_spec(data).spec is None, "pydantic accepted it"
    assert list(Draft202012Validator(schema).iter_errors(as_json(data))), "schema.json accepted it"


def test_cli_export_check_and_validate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export-schema", "--check"]) == 0
    assert main(["validate", *map(str, sorted(EXAMPLES.glob("*.yaml")))]) == 0
    assert capsys.readouterr().out.count("OK  ") == len(list(EXAMPLES.glob("*.yaml")))
