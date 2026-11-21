"""DE-11: data-quality checks on `knowledge.crawl_runs` and `knowledge.documents`.

Every check is a function of the connection, a `now` and a `MonitoringConfig`; it only reads, and returns a list of `Alert` (empty when
all is well). The numbers in `MonitoringConfig` are **assumptions** (nothing in the task plan fixes them): start with them, tune them
after the first real crawls.

The task's "Done when" is "alert on failed or empty runs": `failed_run` and `empty_run`. The others are the "volumes and freshness" of the
task text.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

from .alerts import Alert, Severity

PAGES = "pages_fetched + pages_unchanged + pages_duplicate + pages_blocked + pages_failed"


@dataclass(frozen=True)
class MonitoringConfig:
    lookback: timedelta = timedelta(hours=24)            # runs finished in this window are looked at by the run checks
    stuck_after: timedelta = timedelta(hours=6)          # a run still "running" after this is stuck
    max_days_without_success: int = 3                    # N: no successful run for this many days
    volume_drop_ratio: float = 0.5                       # alert when a run has less than this share of the usual volume
    volume_baseline_runs: int = 5                        # the usual volume = median of this many earlier finished runs
    volume_min_baseline: int = 10                        # ignore the check when the usual volume is smaller than this
    unprocessed_after: timedelta = timedelta(hours=24)   # a usable document not embedded after this is stuck in the pipeline
    unprocessed_max: int = 0                             # how many stuck documents are tolerated
    max_days_without_new_data: int = 7                   # newest document older than this: nothing new is arriving


def failed_runs(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """A run that ended with status 'failed' inside the look-back window. Critical."""
    rows = conn.execute(
        "SELECT id, finished_at, left(coalesce(error, ''), 200), pages_failed FROM knowledge.crawl_runs "
        "WHERE status = 'failed' AND finished_at >= %s ORDER BY finished_at", (now - config.lookback,)).fetchall()
    return [Alert("failed_run", Severity.CRITICAL, f"crawl run {run_id} failed", now, f"failed_run:{run_id}",
                  {"run_id": str(run_id), "finished_at": finished.isoformat(), "pages_failed": failed, "error": error})
            for run_id, finished, error, failed in rows]


def empty_runs(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """A finished run that saw zero pages (fetched, unchanged, duplicate, blocked and failed are all 0). Critical.

    A run that ended 'failed' is reported by `failed_runs`, not twice.
    """
    rows = conn.execute(
        f"SELECT id, status, finished_at FROM knowledge.crawl_runs WHERE status IN ('succeeded', 'partial') "
        f"AND finished_at >= %s AND ({PAGES}) = 0 ORDER BY finished_at", (now - config.lookback,)).fetchall()
    return [Alert("empty_run", Severity.CRITICAL, f"crawl run {run_id} finished with zero pages", now, f"empty_run:{run_id}",
                  {"run_id": str(run_id), "status": status, "finished_at": finished.isoformat()})
            for run_id, status, finished in rows]


def stuck_runs(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """A run still 'running' long after it started: the process probably died. Critical."""
    rows = conn.execute(
        "SELECT id, started_at FROM knowledge.crawl_runs WHERE status = 'running' AND started_at < %s ORDER BY started_at",
        (now - config.stuck_after,)).fetchall()
    return [Alert("stuck_run", Severity.CRITICAL, f"crawl run {run_id} has been running since {started:%Y-%m-%d %H:%M}", now,
                  f"stuck_run:{run_id}", {"run_id": str(run_id), "started_at": started.isoformat()})
            for run_id, started in rows]


def no_recent_success(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """No run with status 'succeeded' that saw at least one page finished in the last N days (also when there is no run). Critical.

    An empty run does not count as a success (it has its own alert), otherwise a crawler that finds nothing would look healthy.
    """
    last = conn.execute(
        f"SELECT max(finished_at) FROM knowledge.crawl_runs WHERE status = 'succeeded' AND ({PAGES}) > 0").fetchone()[0]
    limit = now - timedelta(days=config.max_days_without_success)
    if last is not None and last >= limit:
        return []
    when = f"the last one finished at {last:%Y-%m-%d %H:%M}" if last else "there has never been one"
    return [Alert("no_recent_success", Severity.CRITICAL,
                  f"no successful crawl run in {config.max_days_without_success} days: {when}", now, "no_recent_success",
                  {"days": config.max_days_without_success, "last_success": last.isoformat() if last else None})]


def volume_drop(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """The latest finished run saw much fewer pages than usual (the median of the runs before it). Warning.

    Skipped when there are fewer than 3 earlier runs, or the usual volume is below `volume_min_baseline` (too small to judge).
    """
    rows = conn.execute(
        f"SELECT id, ({PAGES}) AS pages, finished_at FROM knowledge.crawl_runs WHERE status IN ('succeeded', 'partial') "
        f"AND finished_at IS NOT NULL AND finished_at <= %s ORDER BY finished_at DESC LIMIT %s",
        (now, config.volume_baseline_runs + 1)).fetchall()
    if len(rows) < 4:
        return []
    (run_id, pages, finished), earlier = rows[0], [r[1] for r in rows[1:]]
    usual = statistics.median(earlier)
    if usual < config.volume_min_baseline or pages == 0 or pages >= usual * config.volume_drop_ratio:
        return []                                         # pages == 0 is the empty_run check's job
    return [Alert("volume_drop", Severity.WARNING,
                  f"crawl run {run_id} saw {pages} pages, the usual is {usual:g}", now, f"volume_drop:{run_id}",
                  {"run_id": str(run_id), "pages": pages, "usual": usual, "ratio": round(pages / usual, 3),
                   "finished_at": finished.isoformat()})]


def unprocessed_documents(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """Current, usable documents that were fetched long ago but never reached status 'embedded': stuck in the pipeline. Warning.

    Usable means: quality_ok, not a duplicate, and not a stored SKILL.md example (those are not embedded).
    """
    count = conn.execute(
        "SELECT count(*) FROM knowledge.documents d JOIN knowledge.sources s ON s.id = d.source_id "
        "WHERE d.is_current AND d.quality_ok AND d.duplicate_of IS NULL AND d.status <> 'embedded' "
        "AND s.source_type <> 'skill_md' AND d.fetched_at < %s", (now - config.unprocessed_after,)).fetchone()[0]
    if count <= config.unprocessed_max:
        return []
    return [Alert("unprocessed_documents", Severity.WARNING,
                  f"{count} usable documents were fetched more than {config.unprocessed_after} ago and are not embedded", now,
                  "unprocessed_documents", {"count": count, "older_than_hours": config.unprocessed_after.total_seconds() / 3600})]


def no_new_data(conn: psycopg.Connection, now: datetime, config: MonitoringConfig) -> list[Alert]:
    """The newest document is older than N days: nothing new is arriving (freshness). Warning. Silent on an empty database."""
    newest = conn.execute("SELECT max(fetched_at) FROM knowledge.documents").fetchone()[0]
    if newest is None or newest >= now - timedelta(days=config.max_days_without_new_data):
        return []
    return [Alert("no_new_data", Severity.WARNING,
                  f"the newest document was fetched at {newest:%Y-%m-%d %H:%M}, more than {config.max_days_without_new_data} days ago",
                  now, "no_new_data", {"newest": newest.isoformat(), "days": config.max_days_without_new_data})]


ALL_CHECKS = (failed_runs, empty_runs, stuck_runs, no_recent_success, volume_drop, unprocessed_documents, no_new_data)
