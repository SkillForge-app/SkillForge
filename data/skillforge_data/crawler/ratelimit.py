"""Per-host rate limit: at least `min_interval` seconds between two requests to the same host."""
from __future__ import annotations

import time
from collections.abc import Callable


class HostRateLimiter:
    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str, crawl_delay: float | None = None) -> float:
        """Block until a request to `host` is allowed. A `Crawl-delay` from robots.txt raises the interval.

        Returns how long it waited (seconds). The time of the request is recorded after the wait.
        """
        interval = max(self.min_interval, crawl_delay or 0.0)
        waited = 0.0
        last = self._last.get(host)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining
        self._last[host] = self._clock()
        return waited
