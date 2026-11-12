import json
from collections.abc import Mapping
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CLAUDE_CODE_SCHEMA
from backend.app.compiler.spec_adapter import get_validated_spec, render_skill


CAPABILITY_TO_CLAUDE = {
    "filesystem_read": ["Read", "Glob", "Grep"],
    "filesystem_write": ["Write", "Edit"],
    "terminal": ["Bash"],
    "code_execution": ["Bash"],
    "web_search": ["WebSearch"],
    "web_fetch": ["WebFetch"],
}


class ClaudeCompiler(BaseCompiler):
    """Compile SkillSpec into Claude Code instruction and permission files."""

    def compile(self, skill_spec: Mapping[str, Any]) -> dict[str, str]:
        spec = get_validated_spec(skill_spec)

        content = render_skill(spec, "Claude Code")
        tools = spec.get("tools", {})

        allow = []
        ask = []

        for capability in tools.get("required", []):
            mapped = CAPABILITY_TO_CLAUDE.get(capability, [])
            if capability in {"filesystem_write", "terminal", "code_execution"}:
                ask.extend(mapped)
            else:
                allow.extend(mapped)

        for capability in tools.get("optional", []):
            ask.extend(CAPABILITY_TO_CLAUDE.get(capability, []))

        permissions = {
            "permissions": {
                "allow": sorted(set(allow)),
                "ask": sorted(set(ask)),
                "deny": [],
            }
        }

        return {
            CLAUDE_CODE_SCHEMA.instruction_file: content,
            CLAUDE_CODE_SCHEMA.config_file: json.dumps(
                permissions, indent=2
            ) + "\n",
        }
