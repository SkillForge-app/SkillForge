
import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CLAUDE_CODE_SCHEMA
from backend.app.spec.models import AgentDefinition
from backend.app.spec.validator import validate_agent_definition


def build_permissions(
    tools: list[str],
    constraints: list[str],
) -> dict[str, list[str]]:
    """Build Claude Code permissions from tools and constraints."""

    permissions: dict[str, list[str]] = {
        "allow": [],
        "ask": [],
        "deny": [],
    }

    safe_tools = {"Read", "Glob", "Grep"}
    approval_tools = {"Write", "Edit"}
    supported_tools = safe_tools | approval_tools

    # Default permissions for validated tools
    for tool in tools:
        if tool in safe_tools:
            if tool not in permissions["allow"]:
                permissions["allow"].append(tool)

        elif tool in approval_tools:
            if tool not in permissions["ask"]:
                permissions["ask"].append(tool)

    # Apply explicit constraints
    for raw_rule in constraints:
        rule = raw_rule.strip()

        if ":" not in rule:
            continue

        action, target = rule.split(":", 1)
        action = action.strip().lower()
        target = target.strip()

        if target not in supported_tools:
            continue

        if action == "deny":
            permissions["allow"] = [
                item
                for item in permissions["allow"]
                if item != target
            ]

            permissions["ask"] = [
                item
                for item in permissions["ask"]
                if item != target
            ]

            if target not in permissions["deny"]:
                permissions["deny"].append(target)

        elif action == "allow" and target in tools:
            permissions["ask"] = [
                item
                for item in permissions["ask"]
                if item != target
            ]

            if target not in permissions["allow"]:
                permissions["allow"].append(target)

    return permissions


def build_subagents(
    config: dict[str, Any],
) -> dict[str, str]:
    """Generate Claude Code subagent Markdown files."""

    claude_config = config.get("claude_code", {})

    if not isinstance(claude_config, dict):
        raise ValueError(
            "claude_code config must be an object"
        )

    subagents = claude_config.get("subagents", [])

    if not isinstance(subagents, list):
        raise ValueError(
            "subagents must be a list"
        )

    artifacts: dict[str, str] = {}

    for subagent in subagents:
        if not isinstance(subagent, dict):
            raise ValueError(
                "Each subagent must be an object"
            )

        name = subagent.get("name")
        description = subagent.get("description")
        instructions = subagent.get("instructions")

        # Validate name to prevent unsafe file paths
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,63}",
            name,
        ):
            raise ValueError(
                "Invalid subagent name"
            )

        if (
            not isinstance(description, str)
            or not description.strip()
        ):
            raise ValueError(
                "Subagent description is required"
            )

        if (
            not isinstance(instructions, str)
            or not instructions.strip()
        ):
            raise ValueError(
                "Subagent instructions are required"
            )

        path = f".claude/agents/{name}.md"

        if path in artifacts:
            raise ValueError(
                f"Duplicate subagent: {name}"
            )

        # JSON-quoted strings are compatible with YAML
        # frontmatter for these string values.
        metadata_name = json.dumps(
            name,
            ensure_ascii=False,
        )

        metadata_description = json.dumps(
            description.strip(),
            ensure_ascii=False,
        )

        artifacts[path] = (
            "---\n"
            f"name: {metadata_name}\n"
            f"description: {metadata_description}\n"
            "---\n\n"
            f"{instructions.strip()}\n"
        )

    return artifacts


def build_commands(
    config: dict[str, Any],
) -> dict[str, str]:
    """Generate Claude Code slash command files."""

    claude_config = config.get("claude_code", {})

    if not isinstance(claude_config, dict):
        raise ValueError(
            "claude_code config must be an object"
        )

    commands = claude_config.get("commands", [])

    if not isinstance(commands, list):
        raise ValueError(
            "commands must be a list"
        )

    artifacts: dict[str, str] = {}

    for command in commands:
        if not isinstance(command, dict):
            raise ValueError(
                "Each command must be an object"
            )

        name = command.get("name")
        description = command.get("description")
        prompt = command.get("prompt")

        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,63}",
            name,
        ):
            raise ValueError(
                "Invalid command name"
            )

        if (
            not isinstance(description, str)
            or not description.strip()
        ):
            raise ValueError(
                "Command description is required"
            )

        if (
            not isinstance(prompt, str)
            or not prompt.strip()
        ):
            raise ValueError(
                "Command prompt is required"
            )

        path = f".claude/commands/{name}.md"

        if path in artifacts:
            raise ValueError(
                f"Duplicate command: {name}"
            )

        metadata_description = json.dumps(
            description.strip(),
            ensure_ascii=False,
        )

        artifacts[path] = (
            "---\n"
            f"description: {metadata_description}\n"
            "---\n\n"
            f"{prompt.strip()}\n"
        )

    return artifacts


def build_workflow_commands(
    steps: list[str],
) -> dict[str, str]:
    """Generate slash commands automatically from workflow steps."""

    artifacts: dict[str, str] = {}

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, str) or not step.strip():
            raise ValueError(
                "Workflow step must be a non-empty string"
            )

        name = f"step-{index}"
        path = f".claude/commands/{name}.md"

        metadata_description = json.dumps(
            f"Workflow step {index}: {step.strip()}",
            ensure_ascii=False,
        )

        artifacts[path] = (
            "---\n"
            f"description: {metadata_description}\n"
            "---\n\n"
            f"{step.strip()}\n"
        )

    return artifacts


class ClaudeCompiler(BaseCompiler):
    """Generate Claude Code artifacts from an agent definition."""

    def compile(
        self,
        agent_spec: dict[str, Any],
    ) -> dict[str, str]:

        # Validate input structure
        definition = AgentDefinition.model_validate(
            agent_spec
        )

        # Validate business rules
        issues = validate_agent_definition(
            definition
        )

        if issues:
            messages = [
                f"{issue.path}: {issue.message}"
                for issue in issues
            ]

            raise ValueError(
                "\n".join(messages)
            )

        # Locate Claude Code templates
        template_dir = (
            Path(__file__).resolve().parent.parent
            / "templates"
            / "claude_code"
        )

        environment = Environment(
            loader=FileSystemLoader(
                str(template_dir)
            ),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )

        template = environment.get_template(
            "CLAUDE.md.j2"
        )

        agent = definition.agent

        # Generate CLAUDE.md
        content = template.render(
            name=agent.name,
            description=agent.description or "",
            runtime=agent.runtime,
            entrypoint=agent.entrypoint,
            tools=agent.tools,
            constraints=agent.constraints,
            workflow=agent.workflow,
            quality=agent.quality,
            autonomy=agent.autonomy,
        )

        # Generate permissions
        settings = {
            "permissions": build_permissions(
                agent.tools,
                agent.constraints.rules,
            )
        }

        settings_content = json.dumps(
            settings,
            indent=2,
            ensure_ascii=False,
        ) + "\n"

        # Collect generated artifacts
        artifacts: dict[str, str] = {
            CLAUDE_CODE_SCHEMA.instruction_file: content,
            CLAUDE_CODE_SCHEMA.config_file: settings_content,
        }

        # Generate Subagents
        artifacts.update(
            build_subagents(agent.config)
        )

        # Generate Commands from Workflow steps
        workflow_commands = build_workflow_commands(
            agent.workflow.steps
        )

        artifacts.update(workflow_commands)

        # Generate explicitly configured Slash Commands
        configured_commands = build_commands(
            agent.config
        )

        # Prevent duplicate command file paths
        duplicate_paths = (
            artifacts.keys() & configured_commands.keys()
        )

        if duplicate_paths:
            raise ValueError(
                f"Duplicate command path: "
                f"{sorted(duplicate_paths)[0]}"
            )

        artifacts.update(configured_commands)

        return artifacts
