"""FakePipeline: the AI pipeline contract without any model calls, for backend tests (BE-07).

    fake = FakePipeline()                                  # every step returns "ok"
    fake.set("design", "failed", error_code="invalid_spec")
    fake.set("analyze", "blocked", user_message="We can't create this skill. ...")

By default it returns the example AnalyzedRequests and SkillSpecs from ai/examples/, and emits
the same progress events as the real pipeline. Every call is recorded in `fake.calls`.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.analysis import AnalyzedRequest, Answer
from core.pipeline.interface import (
    OnProgress,
    ProgressEvent,
    StepName,
    StepResult,
    StepStatus,
    Usage,
)
from core.spec import SkillSpec, Target, load_spec

AI_ROOT = Path(__file__).resolve().parents[2]


def example_request(name: str = "ai-engineer") -> AnalyzedRequest:
    path = AI_ROOT / "examples" / "analyzed-request" / f"{name}.json"
    return AnalyzedRequest.model_validate_json(path.read_text(encoding="utf-8"))


def example_spec(name: str = "ai-engineer") -> SkillSpec:
    return load_spec(AI_ROOT / "examples" / "skillspec" / f"{name}.yaml")


@dataclass
class _Script:
    status: StepStatus
    value: Any = None
    user_message: str | None = None
    error_code: str | None = None


@dataclass
class FakePipeline:
    calls: list[tuple[StepName, dict[str, Any]]] = field(default_factory=list)
    _scripts: dict[str, _Script] = field(default_factory=dict, repr=False)

    def set(
        self,
        step: StepName,
        status: StepStatus,
        *,
        value: Any = None,
        user_message: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Make `step` return this status from now on (value defaults to the examples)."""
        self._scripts[step] = _Script(status, value, user_message, error_code)

    def _answer(self, step: StepName, default: Any) -> StepResult[Any]:
        script = self._scripts.get(step, _Script("ok"))
        value = script.value
        if value is None and script.status in ("ok", "needs_input"):
            value = default
        return StepResult[Any](
            step=step,
            status=script.status,
            value=value,
            user_message=script.user_message,
            error_code=script.error_code,
            usage=Usage(),
        )

    async def analyze(
        self, text: str, *, selected_targets: Sequence[Target] = ()
    ) -> StepResult[AnalyzedRequest]:
        self.calls.append(("analyze", {"text": text, "selected_targets": list(selected_targets)}))
        script = self._scripts.get("analyze")
        default = example_request(
            "marketing-strategist" if script and script.status == "needs_input" else "ai-engineer"
        )
        if script and script.status == "needs_input" and script.value is None:
            default = _unanswered(default)
        return self._answer("analyze", default)

    async def clarify(
        self, analyzed: AnalyzedRequest, answers: Sequence[Answer]
    ) -> StepResult[AnalyzedRequest]:
        self.calls.append(("clarify", {"analyzed": analyzed, "answers": list(answers)}))
        return self._answer("clarify", example_request("marketing-strategist"))

    async def design(
        self,
        analyzed: AnalyzedRequest,
        *,
        existing_names: Collection[str] = (),
        on_progress: OnProgress | None = None,
    ) -> StepResult[SkillSpec]:
        self.calls.append(
            ("design", {"analyzed": analyzed, "existing_names": list(existing_names)})
        )
        result = self._answer("design", example_spec("ai-engineer"))
        if on_progress:
            on_progress(
                ProgressEvent(step="design", stage="started", message="Starting the skill design")
            )
            on_progress(
                ProgressEvent(
                    step="design",
                    stage="attempt",
                    attempt=1,
                    message="Designing the skill (attempt 1)",
                )
            )
            final = "done" if result.status == "ok" else "failed"
            on_progress(
                ProgressEvent(step="design", stage=final, attempt=1, message=f"Design {final}")
            )
        return result


def _unanswered(analyzed: AnalyzedRequest) -> AnalyzedRequest:
    """The clarified example, turned back into its first-pass form (questions, no answers)."""
    data = analyzed.model_dump(mode="json")
    data.update(needs_clarification=True, answers=[])
    return AnalyzedRequest.model_validate(data)
