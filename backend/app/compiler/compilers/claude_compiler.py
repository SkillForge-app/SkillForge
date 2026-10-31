
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CLAUDE_CODE_SCHEMA
from core.spec.models import AgentDefinition
from core.spec.validator import validate_agent_definition


class ClaudeCompiler(BaseCompiler):
    """Generate CLAUDE.md from a validated agent definition."""

    def compile(self, agent_spec: dict[str, Any]) -> dict[str, str]:
        # Validate the input structure using Pydantic
        definition = AgentDefinition.model_validate(agent_spec)

        # Validate business rules
        issues = validate_agent_definition(definition)

        if issues:
            messages = [
                f"{issue.path}: {issue.message}"
                for issue in issues
            ]
            raise ValueError("\n".join(messages))

        # Load the CLAUDE.md template
        template_dir = (
            Path(__file__).resolve().parent.parent
            / "templates"
            / "claude_code"
        )

        environment = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )

        template = environment.get_template("CLAUDE.md.j2")

        # Render validated data
        agent = definition.agent

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

        return {
            CLAUDE_CODE_SCHEMA.instruction_file: content
        }
