"""The design-run state machine: analyze -> (clarify) -> design -> validate.

It has no database and no web code. The caller loads a RunState, calls `start` or `answer`, and
stores the state again; `save` is called after every change, so a client polling the run sees
the progress events while the design is still running.

Statuses (what the API shows):
    queued        created, not started
    running       a step is running
    needs_input   the analyzer has 3 to 5 questions; send answers to continue
    completed     `spec` holds a SkillSpec that passed the backend validator
    blocked       the safety screen refused the request: no job, nothing stored (BE-14)
    retry_later   a provider was unavailable; start the run again later
    failed        no usable result; `user_message` and `issues` say why
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.app.pipeline.outcome import DesignPipeline, StepOutcome
from backend.app.spec.validator import validate_spec

TERMINAL_STATUSES = frozenset({"completed", "blocked", "retry_later", "failed"})
USAGE_KEYS = ("calls", "input_tokens", "output_tokens", "cost_usd")
MAX_PROGRESS_EVENTS = 200


class RunStateError(RuntimeError):
    """The run is not in a state that allows this call."""


@dataclass
class RunState:
    status: str = "queued"
    step: str | None = None
    analyzed: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None
    progress: list[dict[str, Any]] = field(default_factory=list)
    user_message: str | None = None
    error_code: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, float] = field(default_factory=lambda: {key: 0 for key in USAGE_KEYS})

    @property
    def questions(self) -> list[dict[str, Any]]:
        if self.status != "needs_input" or not self.analyzed:
            return []
        return list(self.analyzed.get("questions", []))


Save = Callable[[RunState], None]


def _noop(_: RunState) -> None:
    return None


def _add_usage(state: RunState, usage: dict[str, Any]) -> None:
    for key in USAGE_KEYS:
        state.usage[key] = state.usage.get(key, 0) + usage.get(key, 0)


def _stop(state: RunState, outcome: StepOutcome, status: str) -> None:
    state.status = status
    state.user_message = outcome.user_message
    state.error_code = outcome.error_code
    state.issues = list(outcome.issues)


def _begin(state: RunState, step: str) -> None:
    state.status = "running"
    state.step = step
    state.user_message = None
    state.error_code = None
    state.issues = []


async def start(
    pipeline: DesignPipeline,
    state: RunState,
    text: str,
    targets: Sequence[str],
    existing_names: Sequence[str] = (),
    save: Save = _noop,
) -> RunState:
    """Run analyze, then design if nothing more is needed from the user."""
    if state.status != "queued":
        raise RunStateError(f"A run can only be started from 'queued', not '{state.status}'")

    _begin(state, "analyze")
    save(state)
    outcome = await pipeline.analyze(text, list(targets))
    _add_usage(state, outcome.usage)

    if not _apply_analysis(state, outcome):
        save(state)
        return state
    return await _design(pipeline, state, existing_names, save)


async def answer(
    pipeline: DesignPipeline,
    state: RunState,
    answers: Sequence[dict[str, Any]],
    existing_names: Sequence[str] = (),
    save: Save = _noop,
) -> RunState:
    """Send the user's answers (skipping a question is allowed), then design."""
    if state.status != "needs_input" or state.analyzed is None:
        raise RunStateError("This run is not waiting for answers")

    _begin(state, "clarify")
    save(state)
    outcome = await pipeline.clarify(state.analyzed, list(answers))
    _add_usage(state, outcome.usage)

    # The AI contract asks at most one round of questions, so a second needs_input is a failure.
    if outcome.status == "needs_input":
        outcome = StepOutcome(
            step=outcome.step,
            status="failed",
            user_message=outcome.user_message,
            error_code="clarification_loop",
            issues=outcome.issues,
            usage=outcome.usage,
        )

    if not _apply_analysis(state, outcome):
        save(state)
        return state
    return await _design(pipeline, state, existing_names, save)


def _apply_analysis(state: RunState, outcome: StepOutcome) -> bool:
    """Record an analyze/clarify result. True when the run can go on to design."""
    if outcome.status == "ok" and outcome.value is not None:
        state.analyzed = outcome.value
        return True

    if outcome.status == "needs_input" and outcome.value is not None:
        state.analyzed = outcome.value
        _stop(state, outcome, "needs_input")
        return False

    if outcome.status == "blocked":
        state.analyzed = None  # a refused request is not kept
        _stop(state, outcome, "blocked")
    elif outcome.status == "retry_later":
        _stop(state, outcome, "retry_later")
    else:
        _stop(state, outcome, "failed")
        if outcome.status == "ok":  # "ok" without a value is a pipeline bug
            state.error_code = "empty_result"
    return False


async def _design(
    pipeline: DesignPipeline,
    state: RunState,
    existing_names: Sequence[str],
    save: Save,
) -> RunState:
    assert state.analyzed is not None
    _begin(state, "design")
    save(state)

    def on_progress(event: dict[str, Any]) -> None:
        if len(state.progress) < MAX_PROGRESS_EVENTS:
            state.progress.append(event)
            save(state)

    outcome = await pipeline.design(state.analyzed, list(existing_names), on_progress)
    _add_usage(state, outcome.usage)

    if outcome.status == "ok" and outcome.value is not None:
        _finish_design(state, outcome)
    elif outcome.status == "needs_input":
        _stop(state, outcome, "needs_input")  # the analysis still has open questions
    elif outcome.status == "blocked":
        state.analyzed = None
        _stop(state, outcome, "blocked")
    elif outcome.status == "retry_later":
        _stop(state, outcome, "retry_later")
    else:
        _stop(state, outcome, "failed")
        if outcome.status == "ok":
            state.error_code = "empty_result"

    save(state)
    return state


def _finish_design(state: RunState, outcome: StepOutcome) -> None:
    """The AI package validates its own spec; the backend checks it again before storing it."""
    result = validate_spec(outcome.value)

    if not result.ok or result.spec is None:
        state.status = "failed"
        state.error_code = "invalid_spec"
        state.user_message = (
            "We could not design this skill. Please rephrase or add detail and try again."
        )
        state.issues = [
            {
                "path": issue.path,
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
            }
            for issue in result.errors
        ]
        return

    state.spec = result.spec.model_dump(mode="json")
    state.status = "completed"
    state.user_message = None
    state.error_code = None
    # Warnings from the AI package's own validation are kept; they are not errors.
    state.issues = list(outcome.issues)
