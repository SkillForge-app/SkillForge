from collections.abc import Mapping
from typing import Any

from backend.app.spec.validator import validate_spec


def get_validated_spec(data: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_spec(data)

    if not result.ok:
        errors = "\n".join(
            f"{issue.path}: {issue.message}"
            for issue in result.errors
        )
        raise ValueError(f"Invalid SkillSpec:\n{errors}")

    if result.spec is None:
        raise ValueError("SkillSpec validation returned no specification.")

    return result.spec.model_dump(mode="json")


def render_skill(spec: dict[str, Any], platform: str) -> str:
    skill = spec["skill"]
    lines = [
        f"# {skill['title']}",
        "",
        f"> {skill['summary']}",
        "",
        f"**Name:** {skill['name']}",
        f"**Version:** {skill['version']}",
        f"**Kind:** {skill['kind']}",
        f"**Domain:** {skill['domain']}",
        f"**Platform:** {platform}",
        "",
        "## When to use",
    ]

    for item in spec.get("triggers", {}).get("use_when", []):
        lines.append(f"- {item}")

    lines.extend(["", "## When not to use"])

    for item in spec.get("triggers", {}).get("avoid_when", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Principles"])

    for item in spec.get("expertise", {}).get("principles", []):
        lines.append(f"- {item}")

    for procedure in spec.get("procedures", []):
        lines.extend([
            "",
            f"## Procedure: {procedure['title']}",
            "",
        ])

        for index, step in enumerate(procedure.get("steps", []), 1):
            lines.append(f"{index}. {step}")

        if procedure.get("produces"):
            lines.append(f"\n**Produces:** {', '.join(procedure['produces'])}")

    for output in spec.get("outputs", []):
        lines.extend([
            "",
            f"## Output: {output['title']}",
        ])

        if output.get("template"):
            lines.append(f"Template: `{output['template']}`")

        for section in output.get("sections", []):
            lines.append(f"- {section}")

    lines.extend(["", "## Guardrails"])

    for guardrail in spec.get("guardrails", []):
        lines.append(
            f"- **{guardrail['severity'].upper()} "
            f"({guardrail['category']}):** {guardrail['rule']}"
        )

    tools = spec.get("tools", {})
    lines.extend(["", "## Tools"])

    for tool in tools.get("required", []):
        lines.append(f"- Required: `{tool}`")

    for tool in tools.get("optional", []):
        lines.append(f"- Optional: `{tool}`")

    references = spec.get("knowledge", {}).get("references", [])
    if references:
        lines.extend(["", "## References"])
        for reference in references:
            lines.append(
                f"- **{reference['title']}** — `{reference['file']}`"
            )

    sources = spec.get("sources", [])
    if sources:
        lines.extend(["", "## Sources"])
        for source in sources:
            lines.append(f"- {source['title']}: {source['url']}")

    evaluation = spec.get("evaluation", {})
    if evaluation.get("test_prompts"):
        lines.extend(["", "## Evaluation prompts"])
        for prompt in evaluation["test_prompts"]:
            lines.append(f"- {prompt}")

    if evaluation.get("should_not_trigger"):
        lines.extend(["", "## Should not trigger"])
        for item in evaluation["should_not_trigger"]:
            lines.append(f"- {item}")

    lines.append("")
    return "\n".join(lines)
