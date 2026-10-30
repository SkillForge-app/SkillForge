"""The AI pipeline interface: the functions the backend worker calls (contract for BE-07/BE-08).

    pipeline: AIPipeline = RealPipeline()          # or FakePipeline() in BE tests
    result = await pipeline.analyze(text, selected_targets=["claude"])
    if result.status == "needs_input": ...show result.value.questions, later call clarify()...
    result = await pipeline.design(result.value, existing_names=names, on_progress=send_event)

Every step returns a StepResult VALUE (never raises for expected outcomes), so the worker can
store it as JSON (`model_dump_json()`) and decide what to do from `status`:
- ok           continue with `value`
- needs_input  show the clarifying questions in `value.questions`, then call clarify()
- blocked      show `user_message`; start no job (BE-14)
- retry_later  a provider or the safety screen was unavailable; retry the job later
- failed       no usable result (e.g. no valid spec after 3 tries); `issues` say why
                 (error_code "budget_exceeded": the skill's model budget is used up, AI-21)
Changes to this file need a PR approved by AI and BE.

Cost budget (AI-21): wrap each step of one job in `core.llm.skill_run(skill_id,
spent_usd=<cost of earlier steps>)`; the budget then covers the whole skill. Without it, each
step gets the environment's per-step budget. Every step logs one metadata-only StepEvent.
"""

import time
from collections.abc import Awaitable, Callable, Collection, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from core.agents import (
    ArchitectRefused,
    ArchitectUnavailable,
    NotReady,
    NotScreened,
    build_spec,
)
from core.analysis import (
    AnalyzedRequest,
    Answer,
    RequestBlocked,
    SafetyUnavailable,
    answer_questions_safely,
    refusal_message,
    screen_and_analyze,
)
from core.llm import (
    BudgetExceeded,
    LLMError,
    LLMUnavailable,
    current_skill_run,
    get_limits,
    skill_run,
    track_usage,
)
from core.ops.events import QualitySampleEvent, StepEvent, log_event, sample_rate, should_sample
from core.spec import Issue, SkillSpec, Target

PIPELINE_VERSION = "0.1"

StepName = Literal["analyze", "clarify", "design"]
StepStatus = Literal["ok", "needs_input", "blocked", "retry_later", "failed"]
Stage = Literal["started", "attempt", "repairing", "done", "failed"]
V = TypeVar("V", AnalyzedRequest, SkillSpec)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IssueRecord(_Model):
    path: str
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"

    @classmethod
    def of(cls, issue: Issue) -> "IssueRecord":
        return cls(path=issue.path, code=issue.code, message=issue.message, severity=issue.severity)


class Usage(_Model):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ProgressEvent(_Model):
    """Sent while a step runs, for the browser (BE-08). In order, per step."""

    step: StepName
    stage: Stage
    attempt: int | None = None
    message: str


class StepResult(_Model, Generic[V]):
    step: StepName
    status: StepStatus
    value: V | None = None
    user_message: str | None = Field(default=None, description="Safe to show to the user.")
    error_code: str | None = None
    issues: list[IssueRecord] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    pipeline_version: str = PIPELINE_VERSION


OnProgress = Callable[[ProgressEvent], None]


class AIPipeline(Protocol):
    async def analyze(
        self, text: str, *, selected_targets: Sequence[Target] = ()
    ) -> StepResult[AnalyzedRequest]: ...

    async def clarify(
        self, analyzed: AnalyzedRequest, answers: Sequence[Answer]
    ) -> StepResult[AnalyzedRequest]: ...

    async def design(
        self,
        analyzed: AnalyzedRequest,
        *,
        existing_names: Collection[str] = (),
        on_progress: OnProgress | None = None,
    ) -> StepResult[SkillSpec]: ...


RETRY_LATER_MESSAGE = "Something went wrong on our side. Please try again in a few minutes."
FAILED_MESSAGE = "We could not design this skill. Please rephrase or add detail and try again."
BUDGET_MESSAGE = "This skill needs more work than we can do for one request. Please narrow it down."


class RealPipeline:
    """The production pipeline: safety screen + analysis, clarification, Skill Architect."""

    async def analyze(
        self, text: str, *, selected_targets: Sequence[Target] = ()
    ) -> StepResult[AnalyzedRequest]:
        start = time.perf_counter()
        with _step_budget("analyze"), track_usage() as usage:
            outcome = await _analysis_step(
                "analyze", screen_and_analyze(text, selected_targets=selected_targets)
            )
        return _finish(outcome, usage, start)

    async def clarify(
        self, analyzed: AnalyzedRequest, answers: Sequence[Answer]
    ) -> StepResult[AnalyzedRequest]:
        start = time.perf_counter()
        with _step_budget("clarify"), track_usage() as usage:
            outcome = await _analysis_step("clarify", answer_questions_safely(analyzed, answers))
        return _finish(outcome, usage, start)

    async def design(
        self,
        analyzed: AnalyzedRequest,
        *,
        existing_names: Collection[str] = (),
        on_progress: OnProgress | None = None,
    ) -> StepResult[SkillSpec]:
        def emit(stage: Stage, attempt: int | None, message: str) -> None:
            if on_progress:
                on_progress(
                    ProgressEvent(step="design", stage=stage, attempt=attempt, message=message)
                )

        def from_architect(stage: str, attempt: int) -> None:
            messages = {
                "attempt": f"Designing the skill (attempt {attempt})",
                "repairing": f"Fixing problems in the design (attempt {attempt})",
                "done": "Design ready",
                "failed": "Could not produce a valid design",
            }
            emit(stage, attempt, messages.get(stage, stage))  # type: ignore[arg-type]

        emit("started", None, "Starting the skill design")
        start = time.perf_counter()
        with _step_budget("design"), track_usage() as usage:
            try:
                result = await build_spec(
                    analyzed, existing_names=existing_names, on_progress=from_architect
                )
            except NotScreened:
                outcome = _result(
                    "design", "failed", error_code="not_screened", user_message=FAILED_MESSAGE
                )
            except NotReady:
                outcome = _result("design", "needs_input", error_code="open_questions")
            except ArchitectUnavailable:
                outcome = _result(
                    "design",
                    "retry_later",
                    error_code="provider_unavailable",
                    user_message=RETRY_LATER_MESSAGE,
                )
            except BudgetExceeded:
                outcome = _budget_result("design")
            except ArchitectRefused:
                outcome = _result(
                    "design",
                    "blocked",
                    error_code="blocked.other",
                    user_message=refusal_message("other"),
                )
            else:
                if result.ok:
                    outcome = _result(
                        "design",
                        "ok",
                        value=result.spec,
                        issues=[IssueRecord.of(i) for i in result.issues],
                    )
                else:
                    outcome = _result(
                        "design",
                        "failed",
                        error_code="invalid_spec",
                        user_message=FAILED_MESSAGE,
                        issues=[IssueRecord.of(i) for i in result.issues],
                    )
        if outcome.status == "ok" and outcome.value is not None:
            _maybe_sample(outcome.value.skill.name)
        return _finish(outcome, usage, start)


async def _analysis_step(
    step: StepName, run: Awaitable[AnalyzedRequest]
) -> StepResult[AnalyzedRequest]:
    try:
        analyzed: AnalyzedRequest = await run
    except RequestBlocked as blocked:
        return _result(
            step,
            "blocked",
            error_code=f"blocked.{blocked.category}",
            user_message=blocked.user_message,
        )
    except BudgetExceeded:
        return _budget_result(step)
    except (SafetyUnavailable, LLMUnavailable):
        return _result(
            step, "retry_later", error_code="provider_unavailable", user_message=RETRY_LATER_MESSAGE
        )
    except LLMError as exc:
        return _result(
            step,
            "failed",
            error_code=f"analysis_failed.{type(exc).__name__}",
            user_message=FAILED_MESSAGE,
        )
    status: StepStatus = "needs_input" if analyzed.needs_clarification else "ok"
    return _result(step, status, value=analyzed)


def _budget_result(step: StepName) -> StepResult[Any]:
    return _result(step, "failed", error_code="budget_exceeded", user_message=BUDGET_MESSAGE)


@contextmanager
def _step_budget(step: StepName) -> Iterator[None]:
    """The environment's per-step budget, unless the backend opened a skill_run (which then
    holds the whole skill's budget)."""
    if current_skill_run() is not None:
        context: Any = nullcontext()
    else:
        context = skill_run(None, budget_usd=get_limits().step_budget_usd.get(step))
    with context:
        yield


def _finish(outcome: StepResult[Any], usage: Any, start: float) -> StepResult[Any]:
    result = outcome.model_copy(update={"usage": _usage(usage)})
    run = current_skill_run()
    log_event(
        StepEvent(
            step=result.step,
            status=result.status,
            error_code=result.error_code,
            calls=result.usage.calls,
            cost_usd=result.usage.cost_usd,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            skill_run=run.skill_id if run else None,
            skill_cost_usd=round(run.total_usd, 6) if run and run.skill_id else None,
        ),
        warning=result.status in ("retry_later", "failed"),
    )
    return result


def _maybe_sample(skill_name: str) -> None:
    """Log a published spec for the AI-16 judge at the environment's sample rate."""
    run = current_skill_run()
    key = run.skill_id if run and run.skill_id else skill_name
    if should_sample(key):
        log_event(QualitySampleEvent(skill_run=key, sample_rate=sample_rate()))


def _result(step: StepName, status: StepStatus, **fields: Any) -> StepResult[Any]:
    return StepResult[Any](step=step, status=status, **fields)


def _usage(totals: Any) -> Usage:
    return Usage(
        calls=totals.calls,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cost_usd=round(totals.cost_usd, 6),
    )
