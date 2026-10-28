
import pytest
from pydantic import ValidationError

from core.spec.models import AgentDefinition


def test_valid_agent_definition():
    agent = AgentDefinition(
        agent={"name": "Test Agent"},
        project={"name": "AgentForge"},
        tools=[{"name": "search"}],
    )

    assert agent.agent.name == "Test Agent"
    assert agent.project.name == "AgentForge"
    assert agent.tools[0].name == "search"
    assert agent.autonomy.level == "medium"


def test_agent_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        AgentDefinition(
            agent={"name": ""},
            project={"name": "AgentForge"},
        )


def test_invalid_autonomy_level():
    with pytest.raises(ValidationError):
        AgentDefinition(
            agent={"name": "Test Agent"},
            project={"name": "AgentForge"},
            autonomy={"level": "extreme"},
        )


def test_tools_default_to_empty_list():
    agent = AgentDefinition(
        agent={"name": "Test Agent"},
        project={"name": "AgentForge"},
    )

    assert agent.tools == []


def test_project_name_cannot_be_empty():
    from core.spec.models import ProjectSpec

    with pytest.raises(ValidationError):
        ProjectSpec(name="")


def test_tool_name_cannot_be_empty():
    from core.spec.models import ToolSpec

    with pytest.raises(ValidationError):
        ToolSpec(name="")
