"""Per-call usage records, cost totals and the per-skill cost budget (AI-02, AI-21).

Policy: log metadata only. A CallRecord never holds prompt text, rendered messages, inputs,
embedded texts, model output or exception messages (provider errors can echo the prompt).
`extra="forbid"` stops a content field from being added by accident.

    with skill_run(job.skill_id, spent_usd=job.cost_so_far, budget_usd=1.50) as run:
        result = await pipeline.design(analyzed)    # stops cleanly once the budget is used up
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.llm.errors import BudgetExceeded

logger = logging.getLogger("skillforge.llm")


class CallRecord(BaseModel):
    """One attempt to call a model. All attempts of one `complete`/`embed` share a call_id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    kind: Literal["complete", "embed"]
    prompt_id: str | None = None
    prompt_version: int | None = None
    model_role: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    n_texts: int | None = None
    cost_usd: float | None = None
    finish_reason: str | None = None
    latency_ms: float
    status: Literal["ok", "error"]
    error_type: str | None = None
    attempt: int = 1
    # AI-21: which link of the role's model chain this attempt used (0 = the primary model).
    fallback: int = Field(default=0, ge=0)
    # AI-21: the skill run (BE's id) this call belongs to, so cost per skill can be summed.
    skill_run: str | None = None


@dataclass
class UsageTotals:
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, record: CallRecord) -> None:
        self.calls += 1
        self.errors += record.status == "error"
        self.input_tokens += record.input_tokens or 0
        self.output_tokens += record.output_tokens or 0
        self.cost_usd += record.cost_usd or 0.0


_active: ContextVar[tuple[UsageTotals, ...]] = ContextVar("skillforge_llm_usage", default=())


@contextmanager
def track_usage() -> Iterator[UsageTotals]:
    """Add up every LLM call made inside the block, e.g. to get the cost of one skill run.

    Blocks can be nested; a call counts towards every active block.
    """
    totals = UsageTotals()
    token = _active.set((*_active.get(), totals))
    try:
        yield totals
    finally:
        _active.reset(token)


@dataclass
class SkillRun:
    """One skill's model spend: what earlier steps spent plus what this block spends."""

    skill_id: str | None
    spent_usd: float = 0.0  # before this block (earlier steps of the same skill)
    budget_usd: float | None = None  # None: no limit
    totals: UsageTotals = field(default_factory=UsageTotals)

    @property
    def total_usd(self) -> float:
        return self.spent_usd + self.totals.cost_usd

    @property
    def exhausted(self) -> bool:
        return self.budget_usd is not None and self.total_usd >= self.budget_usd


_runs: ContextVar[tuple[SkillRun, ...]] = ContextVar("skillforge_skill_runs", default=())


@contextmanager
def skill_run(
    skill_id: str | None, *, spent_usd: float = 0.0, budget_usd: float | None = None
) -> Iterator[SkillRun]:
    """Give the calls in the block a skill id and a cost budget.

    BE wraps each step of one job and passes what earlier steps spent (`StepResult.usage`), so
    the budget covers the whole skill without changing the pipeline's signatures. Once spent +
    this block's cost reaches the budget, the next model call raises BudgetExceeded instead of
    calling. A call already running finishes and is counted, so at most one call overruns.
    Runs can be nested; every active budget is checked.
    """
    if spent_usd < 0 or (budget_usd is not None and budget_usd <= 0):
        raise ValueError("spent_usd must be >= 0 and budget_usd > 0")
    with track_usage() as totals:
        run = SkillRun(skill_id, spent_usd, budget_usd, totals)
        token = _runs.set((*_runs.get(), run))
        try:
            yield run
        finally:
            _runs.reset(token)


def current_skill_run() -> SkillRun | None:
    runs = _runs.get()
    return runs[-1] if runs else None


def current_skill_id() -> str | None:
    """The innermost skill id in force (an inner run without an id keeps the outer one)."""
    return next((r.skill_id for r in reversed(_runs.get()) if r.skill_id), None)


def check_budget() -> None:
    """Raise BudgetExceeded when any active skill run has used up its budget. The gateways call
    this before every model attempt, fallbacks included."""
    for run in _runs.get():
        if run.exhausted:
            raise BudgetExceeded(
                f"the skill's model budget of ${run.budget_usd:.2f} is used up "
                f"(${run.total_usd:.4f} spent)"
            )


def new_call_id() -> str:
    return uuid.uuid4().hex


def log_call(record: CallRecord) -> None:
    """Log one JSON line on the `skillforge.llm` logger and add it to active usage totals."""
    for totals in _active.get():
        totals.add(record)
    level = logging.INFO if record.status == "ok" else logging.WARNING
    logger.log(level, record.model_dump_json(), extra={"llm_call": record.model_dump()})
