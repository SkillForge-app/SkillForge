"""The backend's own view of the AI pipeline: plain dicts, no import of the `ai/` package.

The AI contract (ai/core/pipeline, docs/ai/pipeline-interface.md) uses its own Pydantic types.
Only core_adapter.py touches them; everything else in the backend, including the tests, works
with StepOutcome and these Protocols.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

StepStatus = str  # ok | needs_input | blocked | retry_later | failed (the AI contract's statuses)
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class StepOutcome:
    step: str
    status: StepStatus
    value: dict[str, Any] | None = None
    user_message: str | None = None
    error_code: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


class DesignPipeline(Protocol):
    async def analyze(self, text: str, targets: Sequence[str]) -> StepOutcome: ...

    async def clarify(
        self, analyzed: dict[str, Any], answers: Sequence[dict[str, Any]]
    ) -> StepOutcome: ...

    async def design(
        self,
        analyzed: dict[str, Any],
        existing_names: Sequence[str],
        on_progress: ProgressCallback | None = None,
    ) -> StepOutcome: ...
