
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CLAUDE_CODE_SCHEMA


class ClaudeCompiler(BaseCompiler):
    """Generate Claude Code files from an agent specification."""

    def compile(self, agent_spec: dict[str, Any]) -> dict[str, str]:

        name = agent_spec.get("name", "Unnamed Agent")
        description = agent_spec.get("description", "")
        instructions = agent_spec.get("instructions", "")

        content = f"""# {name}

## Description
{description}

## Instructions
{instructions}
"""

        return {
            CLAUDE_CODE_SCHEMA.instruction_file: content
        }
