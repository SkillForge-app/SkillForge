
import json
from pathlib import Path

from core.spec.models import AgentDefinition


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "spec"
    / "schema.json"
)


def test_exported_schema_matches_models():
    assert SCHEMA_PATH.exists(), "schema.json is missing"

    exported_schema = json.loads(
        SCHEMA_PATH.read_text(encoding="utf-8")
    )

    expected_schema = AgentDefinition.model_json_schema()

    assert exported_schema == expected_schema, (
        "schema.json is outdated. Regenerate it from AgentDefinition."
    )
