
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CODEX_SCHEMA


class CodexCompiler(BaseCompiler):
    """Generate Codex instruction files from an agent specification."""

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
            CODEX_SCHEMA.instruction_file: content
        }
