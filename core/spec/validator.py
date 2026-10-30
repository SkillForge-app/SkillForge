
from dataclasses import dataclass

from core.spec.models import AgentDefinition


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


def validate_agent_definition(
    definition: AgentDefinition,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # Check tool allowlist
    available_tools = {
        tool.name
        for tool in definition.tools
        if tool.enabled
    }

    for index, tool_name in enumerate(definition.agent.tools):
        if tool_name not in available_tools:
            issues.append(
                ValidationIssue(
                    path=f"agent.tools[{index}]",
                    message=(
                        f"Tool '{tool_name}' is not defined "
                        "or is disabled."
                    ),
                )
            )

    # Check conflicting constraints
    seen_rules: dict[str, tuple[str, int]] = {}

    for index, raw_rule in enumerate(
        definition.agent.constraints.rules
    ):
        rule = raw_rule.strip()

        if ":" not in rule:
            continue

        action, target = rule.split(":", 1)
        action = action.strip().lower()
        target = target.strip()

        if action not in {"allow", "deny"} or not target:
            continue

        previous = seen_rules.get(target)

        if previous is not None:
            previous_action, previous_index = previous

            if previous_action != action:
                issues.append(
                    ValidationIssue(
                        path=f"agent.constraints.rules[{index}]",
                        message=(
                            f"Conflicting rules for '{target}': "
                            f"'{previous_action}' at index "
                            f"{previous_index} and '{action}' "
                            f"at index {index}."
                        ),
                    )
                )
        else:
            seen_rules[target] = (action, index)

    return issues
