"""Claude Code subagent and slash-command files, built from a validated SkillSpec.

Mapping (documented in backend/docs/compiler/field-mapping.md):

    skill (title, summary, triggers, principles, guardrails)  ->  .claude/agents/<skill-name>.md
    each procedure                                            ->  .claude/commands/<procedure-id>.md

Permissions stay in .claude/settings.json (see ClaudeCompiler). The command files deliberately
carry no `allowed-tools`: that setting would grant tools without a prompt and could override the
`ask` rules written to settings.json.
"""

import json
from typing import Any

AGENTS_DIR = ".claude/agents"
COMMANDS_DIR = ".claude/commands"

CAPABILITY_TO_CLAUDE: dict[str, list[str]] = {
    "filesystem_read": ["Read", "Glob", "Grep"],
    "filesystem_write": ["Write", "Edit"],
    "terminal": ["Bash"],
    "code_execution": ["Bash"],
    "web_search": ["WebSearch"],
    "web_fetch": ["WebFetch"],
}

# A subagent must always be able to read the project and its own reference files.
BASELINE_SUBAGENT_TOOLS = ("Read", "Glob", "Grep")

# Claude Code reads the description to decide when to hand work to a subagent; keep it bounded.
MAX_DESCRIPTION_LENGTH = 1024


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _frontmatter(fields: list[tuple[str, str, bool]]) -> list[str]:
    """YAML front matter. Each field is (key, value, quote); quoted values are JSON strings."""
    lines = ["---"]
    for key, value, quote in fields:
        rendered = json.dumps(value, ensure_ascii=False) if quote else value
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return lines


def subagent_tools(spec: dict[str, Any]) -> list[str]:
    """Tool names for the subagent: the baseline plus every required and optional capability."""
    tools = spec.get("tools", {})
    names = set(BASELINE_SUBAGENT_TOOLS)
    for capability in [*tools.get("required", []), *tools.get("optional", [])]:
        names.update(CAPABILITY_TO_CLAUDE.get(capability, []))
    return sorted(names)


def subagent_description(spec: dict[str, Any]) -> str:
    skill = spec["skill"]
    use_when = spec.get("triggers", {}).get("use_when", [])
    text = _one_line(skill["summary"])
    if use_when:
        text += " Use when: " + "; ".join(_one_line(item) for item in use_when) + "."
    return _truncate(text, MAX_DESCRIPTION_LENGTH)


def render_subagent(spec: dict[str, Any]) -> str:
    skill = spec["skill"]
    lines = _frontmatter(
        [
            ("name", skill["name"], False),
            ("description", subagent_description(spec), True),
            ("tools", ", ".join(subagent_tools(spec)), False),
        ]
    )

    lines.extend(["", f"You are {skill['title']}. {_one_line(skill['summary'])}"])

    principles = spec.get("expertise", {}).get("principles", [])
    if principles:
        lines.extend(["", "## Principles"])
        lines.extend(f"- {item}" for item in principles)

    guardrails = spec.get("guardrails", [])
    if guardrails:
        lines.extend(["", "## Guardrails"])
        for guardrail in guardrails:
            lines.append(
                f"- **{guardrail['severity'].upper()} ({guardrail['category']}):** "
                f"{guardrail['rule']}"
            )

    avoid_when = spec.get("triggers", {}).get("avoid_when", [])
    if avoid_when:
        lines.extend(["", "## Do not take this work"])
        lines.extend(f"- {item}" for item in avoid_when)

    procedures = spec.get("procedures", [])
    if procedures:
        lines.extend(["", "## Procedures"])
        lines.append("Each procedure is also a slash command in `.claude/commands/`.")
        for procedure in procedures:
            lines.append(f"- `/{procedure['id']}`: {procedure['title']}")

    lines.append("")
    return "\n".join(lines)


def _reference_labels(spec: dict[str, Any], ids: list[str]) -> list[str]:
    files = {
        reference["id"]: reference["file"]
        for reference in spec.get("knowledge", {}).get("references", [])
    }
    return [files.get(item, item) for item in ids]


def render_command(spec: dict[str, Any], procedure: dict[str, Any]) -> str:
    skill = spec["skill"]
    first_step = _one_line(procedure["steps"][0])
    description = _truncate(f"{procedure['title']} ({skill['title']}): {first_step}", 200)

    lines = _frontmatter([("description", description, True)])
    lines.extend(
        [
            "",
            f"# {procedure['title']}",
            "",
            "Work on the request below. Follow these steps in order and do not skip any.",
            "",
            "Request: $ARGUMENTS",
            "",
            "## Steps",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(procedure["steps"], 1))

    produces = procedure.get("produces", [])
    if produces:
        lines.extend(["", "## Produces", ", ".join(produces)])

    uses = procedure.get("uses", [])
    if uses:
        lines.extend(["", "## Consult"])
        lines.extend(f"- `{label}`" for label in _reference_labels(spec, uses))

    lines.append("")
    return "\n".join(lines)


def render_claude_artifacts(spec: dict[str, Any]) -> dict[str, str]:
    """All subagent and command files for a validated spec, keyed by file path."""
    files = {f"{AGENTS_DIR}/{spec['skill']['name']}.md": render_subagent(spec)}
    for procedure in spec.get("procedures", []):
        files[f"{COMMANDS_DIR}/{procedure['id']}.md"] = render_command(spec, procedure)
    return files
