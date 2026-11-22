from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Literal


AutonomyLevel = Literal["low", "medium", "high"]


class BaseCompiler(ABC):
    """Base interface for SkillSpec platform compilers."""

    @abstractmethod
    def compile(
        self,
        skill_spec: Mapping[str, Any],
        *,
        autonomy_level: AutonomyLevel = "medium",
    ) -> dict[str, str]:
        """Compile a SkillSpec into platform-specific files."""
        raise NotImplementedError
