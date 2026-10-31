
import pytest
from pydantic import ValidationError

from core.spec.models import (
    AgentDefinition,
    AgentSpec,
    ProjectSpec,
    ToolSpec,
)


def valid_agent_data():
    return {
        "name": "research-agent",
        "description": "Research assistant",
        "runtime": "python",
        "entrypoint": "agents.research:run",
        "tools": ["web_search"],
        "environment": {},
        "config": {},
    }


def test_valid_agent_spec():
    agent = AgentSpec(**valid_agent_data())

    assert agent.name == "research-agent"
    assert agent.runtime == "python"
    assert agent.entrypoint == "agents.research:run"
    assert agent.tools == ["web_search"]


def test_all_allowed_runtimes():
    for runtime in ("python", "node", "container"):
        agent = AgentSpec(
            **{**valid_agent_data(), "runtime": runtime}
        )
        assert agent.runtime == runtime


def test_invalid_runtime_is_rejected():
    with pytest.raises(ValidationError):
        AgentSpec(
            **{**valid_agent_data(), "runtime": "unknown"}
        )


def test_empty_agent_name_is_rejected():
    with pytest.raises(ValidationError):
        AgentSpec(
            **{**valid_agent_data(), "name": ""}
        )


def test_unknown_agent_field_is_rejected():
    with pytest.raises(ValidationError):
        AgentSpec(
            **{**valid_agent_data(), "vendor_specific_field": "value"}
        )


def test_project_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        ProjectSpec(name="")


def test_tool_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        ToolSpec(name="")


def test_agent_definition_defaults():
    definition = AgentDefinition(
        agent=valid_agent_data(),
        project={"name": "AgentForge"},
    )

    assert definition.tools == []
    assert definition.project.name == "AgentForge"
    assert definition.agent.autonomy.level == "medium"
    assert definition.agent.constraints.rules == []
    assert definition.agent.workflow.steps == []
    assert definition.agent.quality.criteria == []


def test_invalid_spec_has_readable_errors():
    with pytest.raises(ValidationError) as exc_info:
        AgentSpec(
            name="",
            runtime="unknown",
            entrypoint="run",
        )

    errors = exc_info.value.errors()
    error_fields = {error["loc"][0] for error in errors}

    assert "name" in error_fields
    assert "runtime" in error_fields

    message = str(exc_info.value)
    assert "at least 1 character" in message
    assert "'python', 'node' or 'container'" in message
