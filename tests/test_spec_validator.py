
from core.spec.models import (
    AgentDefinition,
    AgentSpec,
    ConstraintsSpec,
    ProjectSpec,
    ToolSpec,
)
from core.spec.validator import validate_agent_definition


def make_definition(
    requested_tools: list[str] | None = None,
    available_tools: list[ToolSpec] | None = None,
    rules: list[str] | None = None,
) -> AgentDefinition:
    return AgentDefinition(
        agent=AgentSpec(
            name="TestAgent",
            runtime="python",
            entrypoint="main.py",
            tools=requested_tools or [],
            constraints=ConstraintsSpec(rules=rules or []),
        ),
        project=ProjectSpec(name="TestProject"),
        tools=available_tools or [],
    )


def test_valid_tool_is_allowed():
    definition = make_definition(
        requested_tools=["browser"],
        available_tools=[ToolSpec(name="browser")],
    )
    assert validate_agent_definition(definition) == []


def test_unknown_tool_is_rejected():
    definition = make_definition(
        requested_tools=["unknown"],
        available_tools=[ToolSpec(name="browser")],
    )
    issues = validate_agent_definition(definition)

    assert len(issues) == 1
    assert issues[0].path == "agent.tools[0]"


def test_disabled_tool_is_rejected():
    definition = make_definition(
        requested_tools=["browser"],
        available_tools=[
            ToolSpec(name="browser", enabled=False)
        ],
    )
    issues = validate_agent_definition(definition)

    assert len(issues) == 1
    assert "disabled" in issues[0].message


def test_conflicting_constraints_are_rejected():
    definition = make_definition(
        rules=["allow:browser", "deny:browser"]
    )
    issues = validate_agent_definition(definition)

    assert len(issues) == 1
    assert issues[0].path == "agent.constraints.rules[1]"
    assert "Conflicting" in issues[0].message


def test_non_conflicting_constraints_are_allowed():
    definition = make_definition(
        rules=["allow:browser", "deny:terminal"]
    )
    assert validate_agent_definition(definition) == []


def test_plain_text_constraints_are_allowed():
    definition = make_definition(
        rules=["Always explain errors clearly"]
    )
    assert validate_agent_definition(definition) == []


import pytest
from pydantic import ValidationError

from core.spec.models import AutonomySpec


@pytest.mark.parametrize(
    "level",
    ["low", "medium", "high"],
)
def test_valid_autonomy_levels(level):
    autonomy = AutonomySpec(level=level)
    assert autonomy.level == level


def test_invalid_autonomy_level_is_rejected():
    with pytest.raises(ValidationError):
        AutonomySpec(level="unlimited")


def test_default_autonomy_is_medium():
    autonomy = AutonomySpec()
    assert autonomy.level == "medium"
