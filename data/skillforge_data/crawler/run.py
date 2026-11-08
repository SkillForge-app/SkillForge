"""A crawl run: fetch a list of URLs politely, record the run in crawl_runs, hand the pages to the pipeline.

Counters in crawl_runs (assumption, the schema only names them):
- pages_fetched   a page body was downloaded (HTTP 200)
- pages_unchanged HTTP 304, or the pipeline found the same content it already processed
- pages_blocked   robots.txt (or the deny-list) forbids the URL; it was not requested
- pages_failed    network error, HTTP error, too large, a URL that cannot be normalised, or a handler error
Status: 'succeeded' when nothing failed; 'partial' when something failed and something else worked; 'failed' when
only failures happened. A run given no URLs ends 'succeeded' with all counters 0; DE-11 raises the alert for empty runs.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import psycopg

from ..interfaces import NormaliseUrl
from ..pipeline.process import RawPage
from ..store import bump_crawl_run, finish_crawl_run, start_crawl_run, upsert_source
from .fetcher import FetchConfig, PageFetcher, Validators
from .license import detect_license

logger = logging.getLogger("skillforge_data.crawler")


class ValidatorStore:
    """ETag and Last-Modified of the last fetch of a URL. In memory until the proposed columns exist
    (docs/proposals/de-04-conditional-get.md)."""

    def __init__(self) -> None:
        self._items: dict[str, Validators] = {}

    def get(self, url: str) -> Validators | None:
        return self._items.get(url)

    def set(self, url: str, validators: Validators) -> None:
        if validators.etag or validators.last_modified:
            self._items[url] = validators


@dataclass
class CrawlSummary:
    run_id: uuid.UUID
    status: str = "running"
    fetched: int = 0
    unchanged: int = 0
    blocked: int = 0
    failed: int = 0
    duplicates: int = 0          # DE-07: pages the pipeline marked as copies of another source's document
    errors: list[str] = field(default_factory=list)


# A handler gets each fetched page and may return a status string; "unchanged" is counted in pages_unchanged.
PageHandler = Callable[[RawPage], object]


class Crawler:
    def __init__(
        self,
        conn: psycopg.Connection,
        fetcher: PageFetcher,
        normalise_url: NormaliseUrl,
        *,
        config: FetchConfig,
        pipeline_version: str,
        validators: ValidatorStore | None = None,
    ) -> None:
        self._conn = conn
        self._fetcher = fetcher
        self._normalise = normalise_url
        self._config = config
        self._pipeline_version = pipeline_version
        self._validators = validators or ValidatorStore()

    def run(
        self,
        urls: Sequence[str],
        *,
        domains: Sequence[str],
        on_page: PageHandler | None = None,
        skill_domain: str | None = None,
    ) -> CrawlSummary:
        conn = self._conn
        run_id = start_crawl_run(
            conn, user_agent=self._config.user_agent, pipeline_version=self._pipeline_version,
            config=self._config.as_dict(), skill_domain=skill_domain,
        )
        summary = CrawlSummary(run_id=run_id)
        for url in urls:
            try:
                self._crawl_one(url, domains, on_page, summary)
            except Exception as exc:
                logger.exception("crawl of %s failed", url)
                self._failed(summary, url, f"{type(exc).__name__}: {exc}")
        summary.status = _status(summary)
        finish_crawl_run(conn, run_id, summary.status, "; ".join(summary.errors[-3:]) or None)
        return summary

    # ------------------------------------------------------------------------------------------------------
    def _crawl_one(self, url: str, domains: Sequence[str], on_page: PageHandler | None, summary: CrawlSummary) -> None:
        try:
            canonical = self._normalise(url)
        except ValueError as exc:
            self._failed(summary, url, f"not an http(s) URL: {exc}")
            return
        host = (urlsplit(canonical).hostname or "").lower()
        known = self._validators.get(canonical)
        result = self._fetcher.fetch(url, known)          # fetch the ORIGINAL URL, store the canonical one

        source_fields: dict[str, object] = {}
        if result.robots_allowed is not None:
            source_fields = {"robots_allowed": result.robots_allowed, "robots_checked_at": result.robots_checked_at}
        if result.outcome == "ok":
            info = detect_license(result.content) if _is_html(result.content_type) else None
            if info is not None and info.spdx != "unknown":
                source_fields.update(license=info.spdx, license_source=info.source)
        upsert_source(self._conn, url=canonical, host=host, **source_fields)

        if result.outcome == "blocked":
            summary.blocked += 1
            bump_crawl_run(self._conn, summary.run_id, "pages_blocked")
            logger.info("blocked: %s", result.error)
        elif result.outcome == "not_modified":
            summary.unchanged += 1
            bump_crawl_run(self._conn, summary.run_id, "pages_unchanged")
        elif result.outcome == "ok":
            summary.fetched += 1
            bump_crawl_run(self._conn, summary.run_id, "pages_fetched")
            self._validators.set(canonical, result.validators)
            page = RawPage(
                url=url, content=result.content, fetched_at=datetime.now(UTC), domains=domains,
                http_status=result.http_status, content_type=result.content_type,
                license=source_fields.get("license", "unknown"),            # type: ignore[arg-type]
                license_source=source_fields.get("license_source", "unknown"),   # type: ignore[arg-type]
                crawl_run_id=summary.run_id,
            )
            if on_page is not None:
                handled = on_page(page)
                status = getattr(handled, "status", handled)       # a ProcessResult, or a plain status string
                if status == "unchanged":
                    summary.unchanged += 1
                    bump_crawl_run(self._conn, summary.run_id, "pages_unchanged")
                elif status == "failed":
                    # process_document already counted it in crawl_runs (it has the run id); count it here only
                    summary.failed += 1
                    summary.errors.append(f"{url}: {getattr(handled, 'error', 'processing failed')}")
                if getattr(handled, "duplicate_of", None) is not None:      # DE-07: a copy of another source's page
                    summary.duplicates += 1
                    bump_crawl_run(self._conn, summary.run_id, "pages_duplicate")
        else:
            self._failed(summary, url, result.error or f"outcome {result.outcome}")

    def _failed(self, summary: CrawlSummary, url: str, error: str) -> None:
        summary.failed += 1
        summary.errors.append(f"{url}: {error}")
        bump_crawl_run(self._conn, summary.run_id, "pages_failed", f"{url}: {error}")


def _is_html(content_type: str | None) -> bool:
    return bool(content_type) and content_type.split(";")[0].strip().lower() in ("text/html", "application/xhtml+xml")


def _status(summary: CrawlSummary) -> str:
    if summary.failed == 0:
        return "succeeded"
    return "partial" if (summary.fetched + summary.unchanged + summary.blocked) > 0 else "failed"
