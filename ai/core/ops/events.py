"""Metadata-only event logs for metrics and alerts (AI-21), next to `skillforge.llm` (CallRecord)
and `skillforge.safety` (safety decisions).

Policy, as for CallRecord: never text. No request, answer, spec, page text, URL path or
exception message; `extra="forbid"` stops a content field from being added by accident.
Each event is one JSON line on its own logger:

    skillforge.pipeline   StepEvent           one per pipeline step (status, cost, latency)
    skillforge.knowledge  IngestPageEvent     one per ingested page (verdict reasons)
                          LLMScreenEvent      one per LLM injection-screen batch
    skillforge.quality    QualitySampleEvent  a published spec picked for the AI-16 judge
"""

import hashlib
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StepEvent(_Event):
    event: Literal["step"] = "step"
    step: Literal["analyze", "clarify", "design"]
    status: Literal["ok", "needs_input", "blocked", "retry_later", "failed"]
    error_code: str | None = None
    calls: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    skill_run: str | None = None
    # The skill's running total (earlier steps + this one) when the backend opened a skill_run
    # with an id: the design step's value is the cost per skill.
    skill_cost_usd: float | None = Field(default=None, ge=0)


class IngestPageEvent(_Event):
    event: Literal["ingest_page"] = "ingest_page"
    host: str  # the page's host only, never the path or the text
    reasons: list[str]  # empty when the page was indexed; "injection" when rejected for it
    chunks: int = Field(ge=0)
    quarantined: int = Field(ge=0)


class LLMScreenEvent(_Event):
    event: Literal["llm_screen"] = "llm_screen"
    screened: int = Field(ge=0)
    flagged: int = Field(ge=0)


class QualitySampleEvent(_Event):
    event: Literal["quality_sample"] = "quality_sample"
    skill_run: str
    sample_rate: float = Field(ge=0, le=1)


LOGGERS = {
    StepEvent: "skillforge.pipeline",
    IngestPageEvent: "skillforge.knowledge",
    LLMScreenEvent: "skillforge.knowledge",
    QualitySampleEvent: "skillforge.quality",
}


def log_event(event: _Event, *, warning: bool = False) -> None:
    logger = logging.getLogger(LOGGERS[type(event)])
    logger.log(
        logging.WARNING if warning else logging.INFO,
        event.model_dump_json(),
        extra={"skillforge_event": event.model_dump()},
    )


# ------------------------------------------------------------------ quality sampling

_sample_rate = 0.0


def set_sample_rate(rate: float) -> None:
    """The share of published specs sent to the AI-16 judge (from the environment profile)."""
    global _sample_rate
    if not 0 <= rate <= 1:
        raise ValueError("the sample rate must be between 0 and 1")
    _sample_rate = rate


def sample_rate() -> float:
    return _sample_rate


def should_sample(key: str, rate: float | None = None) -> bool:
    """Deterministic: the same skill is always in or out of the sample at a given rate."""
    rate = _sample_rate if rate is None else rate
    if rate <= 0:
        return False
    value = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    return value / 2**64 < rate
