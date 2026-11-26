"""Per-call usage records, cost totals and the per-skill cost budget (AI-02, AI-21).

Policy: log metadata only. A CallRecord never holds prompt text, rendered messages, inputs,
embedded texts, model output or free-text exception messages (provider errors can echo the
prompt). `extra="forbid"` stops a content field from being added by accident.

The one exception is `error_detail` (2026-11-25): a few allowlisted fields read from the
provider's *structured* error JSON (code, provider, upstream type and message), with any text
from the call's own inputs and anything key-like removed, capped in length. When the error has
no structured JSON, nothing but the HTTP status is kept. See `provider_error_fields`.

    with skill_run(job.skill_id, spent_usd=job.cost_so_far) as run:   # the environment's budget
        result = await pipeline.design(analyzed)    # stops cleanly once the budget is used up
"""

import json
import logging
import re
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.llm.errors import BudgetExceeded
from core.llm.limits import get_limits

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
    # 2026-11-25: why a provider call failed, without content (see provider_error_fields).
    error_status: int | None = None
    error_detail: str | None = Field(default=None, max_length=300)
    # An output that failed validation: "<field path>:<error type>" per error (e.g.
    # "summary:string_too_long"), never the value. None for every other attempt.
    invalid_fields: list[str] | None = None


DETAIL_MAX = 300
_PART_MAX = 200
_KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|[A-Za-z0-9_-]{32,})")


def provider_error_fields(exc: BaseException, private: Iterable[str] = ()) -> dict[str, Any]:
    """`error_status` and `error_detail` for a failed provider call, safe to log.

    The detail is built only from the provider's structured error JSON inside the exception
    message (OpenRouter's `{"error": {"message", "code", "metadata": {"provider_name", "raw"}}}`,
    with `raw` holding the upstream `{"error": {"type", "message"}}`). Free text is never kept.
    In the two free-text fields (`message`, `upstream_message`) every word of 4+ characters that
    also occurs in `private` (the call's messages or texts) becomes "[input]": this may hide a
    harmless word, but never lets input text through. Key-like strings become "[key]", and the
    result is capped at 300 characters.
    """
    status = getattr(exc, "status_code", None)
    fields: dict[str, Any] = {"error_status": status if isinstance(status, int) else None}
    body = _json_in(str(exc))
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return fields
    found = error.get("metadata")
    meta: dict[str, Any] = found if isinstance(found, dict) else {}
    raw = _json_in(str(meta.get("raw", ""))) if meta.get("raw") else None
    found = raw.get("error") if isinstance(raw, dict) else None
    upstream: dict[str, Any] = found if isinstance(found, dict) else {}
    seen = _words(" ".join(private))
    parts = {
        "provider": meta.get("provider_name"),
        "code": error.get("code"),
        "message": _scrub(error.get("message"), seen),
        "upstream_type": upstream.get("type"),
        "upstream_message": _scrub(upstream.get("message"), seen),
    }
    text = "; ".join(f"{k}={str(v)[:_PART_MAX]}" for k, v in parts.items() if v not in (None, ""))
    fields["error_detail"] = _KEYLIKE.sub("[key]", text)[:DETAIL_MAX] or None
    return fields


def _json_in(text: str) -> Any:
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return value


_WORD = re.compile(r"[^\W_][\w-]*")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) >= 4}


def _scrub(value: Any, seen: set[str]) -> str | None:
    if value in (None, ""):
        return None
    return _WORD.sub(
        lambda m: "[input]" if len(m.group()) >= 4 and m.group().lower() in seen else m.group(),
        str(value),
    )


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

    Without `budget_usd` the environment's budget per skill applies (`skill_budget_usd` of the
    profile set by core.ops; $1.50 in production). With no profile installed there is none.
    """
    if budget_usd is None:
        budget_usd = get_limits().skill_budget_usd
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
