
from abc import ABC, abstractmethod
from typing import Any


class BaseCompiler(ABC):
    """Base interface for all platform compilers."""

    @abstractmethod
    def compile(self, agent_spec: dict[str, Any]) -> dict[str, str]:
        """Convert an AgentSpec into platform-specific files."""
        pass
