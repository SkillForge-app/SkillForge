from collections.abc import Mapping
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.platform_schema import CODEX_SCHEMA
from backend.app.compiler.spec_adapter import get_validated_spec, render_skill


class CodexCompiler(BaseCompiler):
    """Compile SkillSpec into Codex instruction files."""

    def compile(self, skill_spec: Mapping[str, Any]) -> dict[str, str]:
        spec = get_validated_spec(skill_spec)
        content = render_skill(spec, "OpenAI Codex")

        return {
            CODEX_SCHEMA.instruction_file: content,
        }
