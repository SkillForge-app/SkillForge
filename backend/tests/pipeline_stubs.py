"""A scripted stand-in for the AI pipeline, shared by the runner and the API tests."""

import json
from collections.abc import Sequence
from typing import Any

from backend.app.pipeline.outcome import StepOutcome
from backend.tests.skillspec_fixtures import load_valid_spec


def valid_spec() -> dict[str, Any]:
    # The AI package hands over JSON-mode dicts, so dates are strings.
    return json.loads(json.dumps(load_valid_spec(), default=str))


def analyzed(*, questions: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {"request": "I need an AI engineer skill", "needs_clarification": questions}
    data["questions"] = (
        [
            {"id": "q1", "text": "Which stack?", "about": "scope"},
            {"id": "q2", "text": "Which users?", "about": "audience"},
            {"id": "q3", "text": "Which output?", "about": "outputs"},
        ]
        if questions
        else []
    )
    return data


class ScriptedPipeline:
    """Returns the outcomes it was given and records every call."""

    def __init__(self, **outcomes: StepOutcome):
        self.outcomes = outcomes
        self.calls: list[tuple[str, Any]] = []
        self.progress_events: list[dict[str, Any]] = [
            {"step": "design", "stage": "started", "attempt": None, "message": "Starting"},
            {"step": "design", "stage": "done", "attempt": 1, "message": "Design ready"},
        ]

    async def analyze(self, text: str, targets: Sequence[str]) -> StepOutcome:
        self.calls.append(("analyze", (text, list(targets))))
        return self.outcomes["analyze"]

    async def clarify(self, analyzed_request, answers) -> StepOutcome:
        self.calls.append(("clarify", (analyzed_request, list(answers))))
        return self.outcomes["clarify"]

    async def design(self, analyzed_request, existing_names, on_progress=None) -> StepOutcome:
        self.calls.append(("design", (analyzed_request, list(existing_names))))
        for event in self.progress_events:
            if on_progress:
                on_progress(event)
        return self.outcomes["design"]

    @property
    def steps(self) -> list[str]:
        return [name for name, _ in self.calls]


def ok(step, value, **extra) -> StepOutcome:
    return StepOutcome(step=step, status="ok", value=value, **extra)
