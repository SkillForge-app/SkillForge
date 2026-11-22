"""The only file that imports the `ai/` package (`core.pipeline`).

It runs where both packages are installed (the API image once DevOps adds `ai/`, and the worker).
`core` is imported inside the functions, so the backend still starts and its tests still run
where `ai/` is not installed.

Choose the implementation with SKILLFORGE_PIPELINE:
    real  (default)  RealPipeline: needs the LLM keys from ai/.env
    fake             FakePipeline: the example data from ai/examples/, no model calls
"""

import os
from collections.abc import Sequence
from typing import Any

from backend.app.pipeline.outcome import DesignPipeline, ProgressCallback, StepOutcome


class PipelineUnavailable(RuntimeError):
    """The `ai/` package is not installed in this environment."""


def _import_core():
    try:
        from core import analysis, pipeline  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on the deployment
        raise PipelineUnavailable(
            "The AI package (ai/core) is not installed. Install it next to the backend, "
            "or set SKILLFORGE_PIPELINE=fake for local work."
        ) from exc
    return analysis, pipeline


def _outcome(result: Any) -> StepOutcome:
    return StepOutcome(
        step=result.step,
        status=result.status,
        value=result.value.model_dump(mode="json") if result.value is not None else None,
        user_message=result.user_message,
        error_code=result.error_code,
        issues=[issue.model_dump(mode="json") for issue in result.issues],
        usage=result.usage.model_dump(mode="json"),
    )


class CorePipeline:
    """Adapts an `AIPipeline` from `core.pipeline` to the backend's DesignPipeline."""

    def __init__(self, inner: Any | None = None, *, fake: bool = False):
        analysis, pipeline = _import_core()
        self._analysis = analysis
        if inner is None:
            inner = pipeline.FakePipeline() if fake else pipeline.RealPipeline()
        self._inner = inner

    async def analyze(self, text: str, targets: Sequence[str]) -> StepOutcome:
        return _outcome(await self._inner.analyze(text, selected_targets=list(targets)))

    async def clarify(
        self, analyzed: dict[str, Any], answers: Sequence[dict[str, Any]]
    ) -> StepOutcome:
        request = self._analysis.AnalyzedRequest.model_validate(analyzed)
        parsed = [self._analysis.Answer.model_validate(item) for item in answers]
        return _outcome(await self._inner.clarify(request, parsed))

    async def design(
        self,
        analyzed: dict[str, Any],
        existing_names: Sequence[str],
        on_progress: ProgressCallback | None = None,
    ) -> StepOutcome:
        request = self._analysis.AnalyzedRequest.model_validate(analyzed)

        def forward(event: Any) -> None:
            if on_progress is not None:
                on_progress(event.model_dump(mode="json"))

        result = await self._inner.design(
            request, existing_names=list(existing_names), on_progress=forward
        )
        return _outcome(result)


def get_pipeline() -> DesignPipeline:
    """FastAPI dependency. Tests replace it with a stub through `app.dependency_overrides`."""
    mode = os.getenv("SKILLFORGE_PIPELINE", "real").strip().lower()
    if mode not in {"real", "fake"}:
        raise PipelineUnavailable(f"SKILLFORGE_PIPELINE must be 'real' or 'fake', not '{mode}'")
    return CorePipeline(fake=(mode == "fake"))
