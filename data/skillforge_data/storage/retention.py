"""DE-13: retention enforcement for the two rules of `docs/data-architecture.md` ("Retention") that no job applied yet.

| Data | Kept | Rule here |
|---|---|---|
| Superseded documents (`is_current = false`) | 90 days (agreed with AI) | delete the row; its chunks and embeddings go with it (cascade) |
| `crawl_runs` | 12 months (agreed with AI) | delete the row; `documents.crawl_run_id` becomes NULL |

Order, as in `jobs.py`: the **database first** (one small transaction per batch), the **objects after the commit**. A row never points at a
missing object; if an object cannot be deleted it is an orphan that `sweep_orphans` removes later. Idempotent: a second run finds nothing.

Approximations that are **decisions of mine**, to confirm:
- The schema has no "superseded at" column, so the age of a superseded document is counted from its `fetched_at` (the last time that content
  was fetched, which is shortly before a newer version replaced it). It can be a little early by at most one re-crawl window. A column would
  make it exact (question in `docs/p4-progress.md`).
- "12 months" is 365 days, counted from `started_at`. A run still `running` is never deleted (the monitoring check `stuck_run` reports it).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg

from .base import BUCKET_CLEAN, BUCKET_RAW, ObjectStorage

logger = logging.getLogger("skillforge_data.storage")

SUPERSEDED_RETENTION = timedelta(days=90)
CRAWL_RUN_RETENTION = timedelta(days=365)
BATCH = 500


@dataclass
class RetentionReport:
    documents_deleted: int = 0
    crawl_runs_deleted: int = 0
    objects_deleted: int = 0
    errors: list[str] = field(default_factory=list)


def delete_superseded_documents(
    conn: psycopg.Connection, storage: ObjectStorage | None, *, now: datetime,
    retention: timedelta = SUPERSEDED_RETENTION, batch: int = BATCH,
) -> RetentionReport:
    """Delete documents that are not current and were last fetched more than `retention` ago. A current document is never touched."""
    report = RetentionReport()
    cutoff = now - retention
    while True:
        with conn.transaction():                          # 1. the database first
            rows = conn.execute(
                "DELETE FROM knowledge.documents WHERE id IN ("
                "  SELECT id FROM knowledge.documents WHERE NOT is_current AND fetched_at < %s ORDER BY fetched_at LIMIT %s) "
                "RETURNING raw_object_key, clean_object_key", (cutoff, batch)).fetchall()
        if not rows:
            return report
        report.documents_deleted += len(rows)
        if storage is not None:                           # 2. the objects after the commit
            _delete_unreferenced(conn, storage, BUCKET_RAW, {r[0] for r in rows if r[0]}, report)
            _delete_unreferenced(conn, storage, BUCKET_CLEAN, {r[1] for r in rows if r[1]}, report)


def delete_old_crawl_runs(conn: psycopg.Connection, *, now: datetime, retention: timedelta = CRAWL_RUN_RETENTION) -> RetentionReport:
    """Delete finished crawl runs that started more than `retention` ago. Documents keep existing; their `crawl_run_id` becomes NULL."""
    with conn.transaction():
        deleted = conn.execute(
            "DELETE FROM knowledge.crawl_runs WHERE status <> 'running' AND started_at < %s", (now - retention,)).rowcount
    return RetentionReport(crawl_runs_deleted=deleted)


def _delete_unreferenced(conn: psycopg.Connection, storage: ObjectStorage, bucket: str, keys: set[str],
                         report: RetentionReport) -> None:
    """Delete the objects that no remaining document points to (a raw key can be shared by sources with the same bytes)."""
    column = "raw_object_key" if bucket == BUCKET_RAW else "clean_object_key"
    for key in sorted(keys):
        if conn.execute(f"SELECT 1 FROM knowledge.documents WHERE {column} = %s LIMIT 1", (key,)).fetchone():
            continue
        try:
            storage.delete(bucket, key)
            report.objects_deleted += 1
        except Exception as exc:  # noqa: BLE001 - the orphan sweep removes it later
            report.errors.append(f"could not delete {bucket}/{key}: {exc}")
            logger.warning("retention: could not delete %s/%s: %s", bucket, key, exc)


def run_daily_retention_job(conn: psycopg.Connection, storage: ObjectStorage | None, *, now: datetime) -> RetentionReport:
    """Superseded documents, then old crawl runs. Run it daily after the raw expiry (see `run_daily_jobs`)."""
    total = delete_superseded_documents(conn, storage, now=now)
    runs = delete_old_crawl_runs(conn, now=now)
    total.crawl_runs_deleted = runs.crawl_runs_deleted
    logger.info("retention job: %s", total)
    return total
