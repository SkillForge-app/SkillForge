from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class BaseCompiler(ABC):
    """Base interface for SkillSpec platform compilers."""

    @abstractmethod
    def compile(self, skill_spec: Mapping[str, Any]) -> dict[str, str]:
        """Compile a validated SkillSpec into platform-specific files."""
        raise NotImplementedError
