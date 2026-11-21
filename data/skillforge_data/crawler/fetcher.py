"""DE-04: the polite fetcher (httpx).

Per URL: robots.txt check, per-host rate limit, an identified User-Agent, a timeout, a size limit, redirects that are
checked hop by hop, retries with backoff, and conditional GET. A URL that robots.txt forbids is never requested.
`PageFetcher` is the interface; a Playwright fetcher for pages that need JavaScript would implement it (TODO).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from ..urls import host_key
from .ratelimit import HostRateLimiter
from .robots import RobotsPolicy, RobotsResponse

logger = logging.getLogger("skillforge_data.crawler")

USER_AGENT = "SkillForgeBot/0.1 (+https://github.com/SkillForge-app/SkillForge; knowledge collection for agent skills)"
MAX_BYTES = 20 * 1024 * 1024            # 20 MB, the limit proposed in docs/object-storage.md
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
ROBOTS_MAX_REDIRECTS = 5                 # RFC 9309: follow at least five consecutive redirects

Outcome = Literal["ok", "not_modified", "blocked", "too_large", "failed"]


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str = USER_AGENT
    timeout: float = 15.0                 # seconds, for connect and for each read
    max_bytes: int = MAX_BYTES
    max_redirects: int = 5
    retries: int = 3                      # retries after the first try, for 429/5xx and network errors
    backoff_base: float = 1.0             # seconds; doubled on every retry
    max_wait: float = 60.0                # longest pause we accept; a Retry-After above it fails the page
    min_interval: float = 1.0             # seconds between two requests to one host
    denylist: frozenset[str] = frozenset()   # hosts we must not fetch (terms of service review: manual decision)

    def as_dict(self) -> dict[str, object]:
        """What goes into crawl_runs.config."""
        return {
            "user_agent": self.user_agent, "timeout": self.timeout, "max_bytes": self.max_bytes,
            "max_redirects": self.max_redirects, "retries": self.retries, "backoff_base": self.backoff_base,
            "min_interval": self.min_interval, "denylist": sorted(self.denylist),
        }


@dataclass(frozen=True)
class Validators:
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class FetchResult:
    url: str                                  # the URL that was asked for
    outcome: Outcome
    final_url: str | None = None              # after redirects
    http_status: int | None = None
    content: bytes = b""
    content_type: str | None = None
    validators: Validators = field(default_factory=Validators)
    robots_allowed: bool | None = None        # None: robots.txt was not consulted for this URL
    robots_checked_at: datetime | None = None
    error: str | None = None
    redirects: list[str] = field(default_factory=list)


class PageFetcher(Protocol):
    def fetch(self, url: str, validators: Validators | None = None) -> FetchResult: ...


class HttpFetcher:
    def __init__(
        self,
        config: FetchConfig | None = None,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        config = config or FetchConfig()
        self.config = config
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(config.timeout), follow_redirects=False,
            headers={"User-Agent": config.user_agent, "Accept": "text/html,text/markdown,text/plain;q=0.9,*/*;q=0.5"},
        )
        self._sleep = sleep
        self._limiter = HostRateLimiter(config.min_interval, clock=clock, sleep=sleep)
        self._robots = RobotsPolicy(self._fetch_robots, clock=clock)
        self._now = now or (lambda: datetime.now().astimezone())

    def close(self) -> None:
        self._client.close()

    # --- robots.txt -----------------------------------------------------------------------------------------
    def _fetch_robots(self, origin: str) -> RobotsResponse:
        """<origin>/robots.txt, rate-limited like any other request (no retries: errors mean disallow).

        Follows up to ROBOTS_MAX_REDIRECTS redirects (RFC 9309). More than that, a redirect loop, a redirect without a Location, a
        redirect to something that is not http(s) or to a deny-listed host all count as "request failed" (status None).
        A redirect to another host is followed but logged and returned in `RobotsResponse.redirects`.
        """
        current = f"{origin}/robots.txt"
        followed: list[str] = []
        seen = {current}
        while True:
            self._limiter.wait(host_key(current))
            try:
                response = self._client.get(current, headers={"Accept": "text/plain"})
            except httpx.HTTPError as exc:
                logger.warning("robots.txt of %s not reachable (%s): %s", origin, current, exc)
                return RobotsResponse(None, redirects=tuple(followed))
            if response.status_code not in REDIRECT_STATUSES:
                break
            location = response.headers.get("location")
            target = urljoin(current, location) if location else None
            parts = urlsplit(target) if target else None
            try:
                host_key(target) if target else None
            except ValueError:                           # not http(s), no host, or a bad port
                parts = None
            if not parts or parts.scheme not in ("http", "https") or not parts.hostname:
                logger.warning("robots.txt of %s: redirect without a usable Location from %s", origin, current)
                return RobotsResponse(None, redirects=tuple(followed))
            if parts.hostname.lower() in self.config.denylist:
                logger.warning("robots.txt of %s: redirect to deny-listed host %s", origin, parts.hostname)
                return RobotsResponse(None, redirects=tuple(followed))
            if len(followed) >= ROBOTS_MAX_REDIRECTS or target in seen:
                why = "a redirect loop" if target in seen else f"more than {ROBOTS_MAX_REDIRECTS} redirects"
                logger.warning("robots.txt of %s: %s, treated as unavailable", origin, why)
                return RobotsResponse(None, redirects=tuple(followed))
            if host_key(target) != host_key(current):
                logger.warning("robots.txt of %s redirects to another host: %s", origin, target)
            followed.append(target)
            seen.add(target)
            current = target
        text = response.text if response.status_code == 200 and len(response.content) <= 512 * 1024 else ""
        return RobotsResponse(response.status_code, text, tuple(followed))

    # --- one URL --------------------------------------------------------------------------------------------
    def fetch(self, url: str, validators: Validators | None = None) -> FetchResult:
        result = FetchResult(url=url, outcome="failed")
        current = url
        for hop in range(self.config.max_redirects + 1):
            parts = urlsplit(current)
            try:
                host_key(current)
            except ValueError:
                result.error = f"not an http(s) URL: {current}"
                return result
            if parts.hostname.lower() in self.config.denylist:
                result.outcome, result.error = "blocked", f"host {parts.hostname} is on the deny-list"
                result.robots_allowed = None
                return result
            allowed, reason = self._robots.allowed(current)
            if hop == 0:
                result.robots_allowed, result.robots_checked_at = allowed, self._now()
            if not allowed:
                result.outcome, result.error = "blocked", f"{reason}: {current}"
                return result      # the page itself is never requested
            response = self._get_with_retries(current, validators if hop == 0 else None, result)
            if response is None:
                return result
            result.http_status = response.status_code
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                response.close()
                if not location:
                    result.error = f"redirect without Location from {current}"
                    return result
                current = urljoin(current, location)
                result.redirects.append(current)
                continue
            return self._finish(response, current, result)
        result.error = f"more than {self.config.max_redirects} redirects from {url}"
        return result

    def _get_with_retries(self, url: str, validators: Validators | None, result: FetchResult) -> httpx.Response | None:
        headers = {}
        if validators and validators.etag:
            headers["If-None-Match"] = validators.etag
        if validators and validators.last_modified:
            headers["If-Modified-Since"] = validators.last_modified
        host = host_key(url)
        delay = self._robots.crawl_delay(url)
        for attempt in range(self.config.retries + 1):
            self._limiter.wait(host, delay)
            try:
                request = self._client.build_request("GET", url, headers=headers)
                response = self._client.send(request, stream=True)
            except httpx.HTTPError as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                if attempt == self.config.retries:
                    return None
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.config.retries:
                retry_after = _retry_after_seconds(response.headers.get("retry-after"), self._now())
                response.close()
                if retry_after is not None and retry_after > self.config.max_wait:
                    # The server wants a longer pause than we accept: do not hammer it and do not wait for minutes. The page fails in
                    # this run (counted in pages_failed with this reason); the re-crawl schedule (DE-09) picks it up again later.
                    result.http_status = response.status_code
                    result.error = (f"HTTP {response.status_code} for {url}: the server asked to wait {retry_after:.0f}s "
                                    f"(more than max_wait {self.config.max_wait:.0f}s), not retried")
                    logger.warning("%s", result.error)
                    return None
                self._sleep(self._backoff(attempt, retry_after))
                continue
            return response
        return None

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        wait = retry_after if retry_after is not None else self.config.backoff_base * (2 ** attempt)
        return min(wait, self.config.max_wait)

    def _finish(self, response: httpx.Response, url: str, result: FetchResult) -> FetchResult:
        try:
            result.final_url = url
            status = response.status_code
            result.validators = Validators(response.headers.get("etag"), response.headers.get("last-modified"))
            if status == 304:
                result.outcome = "not_modified"
                return result
            if status != 200:
                result.error = f"HTTP {status} for {url}"
                return result            # outcome stays 'failed'; 4xx are not retried
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.config.max_bytes:
                result.outcome, result.error = "too_large", f"Content-Length {declared} is over {self.config.max_bytes}"
                return result
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self.config.max_bytes:
                    result.outcome, result.error = "too_large", f"body is over {self.config.max_bytes} bytes"
                    return result
            result.outcome, result.content = "ok", bytes(body)
            result.content_type = response.headers.get("content-type")
            return result
        except httpx.HTTPError as exc:
            result.outcome, result.error = "failed", f"{type(exc).__name__}: {exc}"
            return result
        finally:
            response.close()


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    """Retry-After (RFC 9110, 10.2.3): a number of seconds or an HTTP-date. A date in the past means 0; garbage means None."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:                     # "-0000" or a date without a zone: HTTP-dates are GMT
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())
