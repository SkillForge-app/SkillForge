from collections.abc import Mapping
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler, AutonomyLevel
from backend.app.compiler.platform_schema import CODEX_SCHEMA
from backend.app.compiler.spec_adapter import get_validated_spec, render_skill


AUTONOMY_TO_APPROVAL = {
    "low": "on-request",
    "medium": "on-request",
    "high": "never",
}


def render_codex_config(
    spec: dict[str, Any],
    autonomy_level: AutonomyLevel = "medium",
) -> str:
    if autonomy_level not in AUTONOMY_TO_APPROVAL:
        raise ValueError(f"Unsupported autonomy level: {autonomy_level}")

    tools = spec.get("tools", {})
    required = set(tools.get("required", []))
    optional = set(tools.get("optional", []))

    if autonomy_level == "low":
        sandbox_mode = "read-only"
    elif "filesystem_write" in required:
        sandbox_mode = "workspace-write"
    else:
        sandbox_mode = "read-only"

    if "web_search" in required:
        web_search = "live"
    elif "web_search" in optional:
        web_search = "cached"
    else:
        web_search = "disabled"

    approval_policy = AUTONOMY_TO_APPROVAL[autonomy_level]

    return (
        f'approval_policy = "{approval_policy}"\n'
        f'sandbox_mode = "{sandbox_mode}"\n'
        f'web_search = "{web_search}"\n'
    )


class CodexCompiler(BaseCompiler):
    """Compile SkillSpec into Codex instruction and configuration files."""

    def compile(
        self,
        skill_spec: Mapping[str, Any],
        *,
        autonomy_level: AutonomyLevel = "medium",
    ) -> dict[str, str]:
        spec = get_validated_spec(skill_spec)
        content = render_skill(spec, "OpenAI Codex")
        config = render_codex_config(spec, autonomy_level)

        return {
            CODEX_SCHEMA.instruction_file: content,
            CODEX_SCHEMA.config_file: config,
        }
