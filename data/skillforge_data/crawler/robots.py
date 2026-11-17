"""robots.txt: fetch once per origin, cache, and answer "may we fetch this URL?" (RFC 9309 behaviour, conservative).

How the answer to the request for /robots.txt is read:
- 200: parse it. The rules for our product token (`SkillForgeBot`) apply, else the rules for `*`.
- 404 or 410: there are no rules, everything is allowed.
- 401 or 403: access to the rules is refused, so we treat the whole origin as disallowed (the careful choice;
  RFC 9309 allows crawling here, but we prefer not to crawl a site that blocks us).
- any other status, or the request fails: the origin is treated as disallowed for a short time, then asked again.
- redirects (RFC 9309, 2.3.1.2): the fetcher follows up to 5 (http -> https, -> www); the answer is the last response. A sixth
  redirect, or a loop, counts as "request failed" (status None), the same rule as any other error. A redirect to another host
  is followed but recorded: `RobotsResponse.redirects` and the policy reason say so.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

from ..urls import host_key, origin_key

PRODUCT_TOKEN = "SkillForgeBot"
TTL_OK_SECONDS = 24 * 3600
TTL_ERROR_SECONDS = 10 * 60


@dataclass(frozen=True)
class RobotsResponse:
    status: int | None        # None: the request failed (network error, timeout, too many redirects)
    text: str = ""
    redirects: tuple[str, ...] = ()   # the URLs followed, in order (empty: none)


@dataclass
class _Entry:
    expires_at: float
    parser: RobotFileParser | None      # None = disallow everything
    reason: str


def origin_of(url: str) -> str:
    return origin_key(url)                      # one rule for the host everywhere: skillforge_data/urls.py


class RobotsPolicy:
    """`fetch_robots(origin)` returns the RobotsResponse for `<origin>/robots.txt` (the fetcher supplies it)."""

    def __init__(
        self,
        fetch_robots: Callable[[str], RobotsResponse],
        *,
        product_token: str = PRODUCT_TOKEN,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch_robots = fetch_robots
        self._token = product_token
        self._clock = clock
        self._cache: dict[str, _Entry] = {}

    def _entry(self, origin: str) -> _Entry:
        now = self._clock()
        entry = self._cache.get(origin)
        if entry is not None and entry.expires_at > now:
            return entry
        response = self._fetch_robots(origin)
        via = _other_host_note(origin, response.redirects)
        if response.status == 200:
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            entry = _Entry(now + TTL_OK_SECONDS, parser, "robots.txt" + via)
        elif response.status in (404, 410):
            entry = _Entry(now + TTL_OK_SECONDS, _allow_all(), "no robots.txt" + via)
        elif response.status in (401, 403):
            entry = _Entry(now + TTL_OK_SECONDS, None, f"robots.txt refused ({response.status}){via}")
        else:
            entry = _Entry(now + TTL_ERROR_SECONDS, None, f"robots.txt unavailable ({response.status}){via}")
        self._cache[origin] = entry
        return entry

    def allowed(self, url: str) -> tuple[bool, str]:
        """(allowed, reason). The reason is for logs and for the crawl run's error text."""
        entry = self._entry(origin_of(url))
        if entry.parser is None:
            return False, entry.reason
        if entry.parser.can_fetch(self._token, url):
            return True, entry.reason
        return False, "disallowed by robots.txt"

    def crawl_delay(self, url: str) -> float | None:
        entry = self._entry(origin_of(url))
        if entry.parser is None:
            return None
        delay = entry.parser.crawl_delay(self._token)
        return float(delay) if delay is not None else None


def _other_host_note(origin: str, redirects: tuple[str, ...]) -> str:
    """' (redirected to host X)' when robots.txt was served by another host than the origin; else ''."""
    hosts = [host_key(r) for r in redirects]
    other = [h for h in hosts if h != host_key(origin)]
    return f" (redirected to host {other[-1]})" if other else ""


def _allow_all() -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse([])
    return parser
