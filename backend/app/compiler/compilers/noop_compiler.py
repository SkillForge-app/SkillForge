
from typing import Any

from backend.app.compiler.base_compiler import BaseCompiler


class NoOpCompiler(BaseCompiler):
    """A compiler that generates no files."""

    def compile(self, agent_spec: dict[str, Any]) -> dict[str, str]:
        return {}

