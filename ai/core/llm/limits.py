"""Per-call caps and per-role rate limits for the model gateways (AI-21).

The environment profile (core/ops) sets them once at startup with `set_limits(...)`; without
it nothing is limited, which keeps tests and scripts unchanged.

- max_output_tokens: a cap on every role's max_tokens (the smaller one wins).
- max_input_chars: a rendered prompt longer than this is refused before any call.
- per role: at most `max_concurrency` calls at once and `requests_per_minute` calls per rolling
  minute, in this process. A call waits for a slot up to `max_wait_s`, then fails with
  LLMUnavailable, which the pipeline turns into `retry_later`. The limits are per process: a
  backend with N workers allows N times as much.
"""

import asyncio
import time
import weakref
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from core.llm.errors import LLMInputError, LLMUnavailable


@dataclass(frozen=True)
class RoleLimit:
    max_concurrency: int | None = None
    requests_per_minute: int | None = None


@dataclass(frozen=True)
class Limits:
    max_output_tokens: int | None = None
    max_input_chars: int | None = None
    max_wait_s: float = 30.0
    roles: Mapping[str, RoleLimit] = field(default_factory=dict)
    default_role: RoleLimit = RoleLimit()
    # Budgets the pipeline uses when the backend gives none (see core.llm.usage.skill_run).
    skill_budget_usd: float | None = None
    step_budget_usd: Mapping[str, float] = field(default_factory=dict)

    def for_role(self, role: str) -> RoleLimit:
        return self.roles.get(role, self.default_role)


_limits = Limits()


def set_limits(limits: Limits) -> Limits:
    """Install limits for this process and return the previous ones."""
    global _limits
    previous, _limits = _limits, limits
    _limiters.clear()
    return previous


def get_limits() -> Limits:
    return _limits


def capped_max_tokens(role_max_tokens: int | None) -> int | None:
    cap = _limits.max_output_tokens
    if cap is None:
        return role_max_tokens
    return cap if role_max_tokens is None else min(role_max_tokens, cap)


def check_input_size(prompt_id: str, chars: int) -> None:
    cap = _limits.max_input_chars
    if cap is not None and chars > cap:
        raise LLMInputError(f"{prompt_id}: the prompt is {chars} characters; the limit is {cap}")


class RoleLimiter:
    """Concurrency and requests-per-minute for one role, in one event loop."""

    def __init__(
        self,
        limit: RoleLimit,
        max_wait_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self.limit = limit
        self.max_wait_s = max_wait_s
        self.clock = clock
        self.sleep = sleep
        self.running = 0
        self.peak = 0
        self._slots = asyncio.Semaphore(limit.max_concurrency) if limit.max_concurrency else None
        self._starts: deque[float] = deque()

    @asynccontextmanager
    async def slot(self, role: str) -> AsyncIterator[None]:
        deadline = self.clock() + self.max_wait_s
        if self._slots is not None:
            try:
                await asyncio.wait_for(self._slots.acquire(), timeout=self.max_wait_s)
            except TimeoutError:
                raise LLMUnavailable(f"role {role}: rate limited locally (concurrency)") from None
        try:
            await self._wait_for_rate(role, deadline)
            self.running += 1
            self.peak = max(self.peak, self.running)
            try:
                yield
            finally:
                self.running -= 1
        finally:
            if self._slots is not None:
                self._slots.release()

    async def _wait_for_rate(self, role: str, deadline: float) -> None:
        rpm = self.limit.requests_per_minute
        if not rpm:
            return
        while True:
            now = self.clock()
            while self._starts and now - self._starts[0] >= 60.0:
                self._starts.popleft()
            if len(self._starts) < rpm:
                self._starts.append(now)
                return
            wait = 60.0 - (now - self._starts[0])
            if now + wait > deadline:
                raise LLMUnavailable(f"role {role}: rate limited locally (requests per minute)")
            await self.sleep(wait)  # type: ignore[misc]


# One limiter per role per event loop: asyncio primitives belong to the loop that made them.
_limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, RoleLimiter]]" = (
    weakref.WeakKeyDictionary()
)


def limiter(role: str) -> RoleLimiter:
    per_loop = _limiters.setdefault(asyncio.get_running_loop(), {})
    if role not in per_loop:
        per_loop[role] = RoleLimiter(_limits.for_role(role), _limits.max_wait_s)
    return per_loop[role]
