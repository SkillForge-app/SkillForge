from collections.abc import Mapping
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CODEX_SCHEMA
from backend.app.compiler.spec_adapter import get_validated_spec, render_skill


def render_codex_config(spec: dict[str, Any]) -> str:
    tools = spec.get("tools", {})
    required = set(tools.get("required", []))
    optional = set(tools.get("optional", []))

    sandbox_mode = (
        "workspace-write"
        if "filesystem_write" in required
        else "read-only"
    )

    if "web_search" in required:
        web_search = "live"
    elif "web_search" in optional:
        web_search = "cached"
    else:
        web_search = "disabled"

    return (
        'approval_policy = "on-request"\n'
        f'sandbox_mode = "{sandbox_mode}"\n'
        f'web_search = "{web_search}"\n'
    )


class CodexCompiler(BaseCompiler):
    """Compile SkillSpec into Codex instruction and configuration files."""

    def compile(self, skill_spec: Mapping[str, Any]) -> dict[str, str]:
        spec = get_validated_spec(skill_spec)
        content = render_skill(spec, "OpenAI Codex")
        config = render_codex_config(spec)

        return {
            CODEX_SCHEMA.instruction_file: content,
            CODEX_SCHEMA.config_file: config,
        }
