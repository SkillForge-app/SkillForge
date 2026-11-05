"""The daily storage job (DE-03): expire raw pages, repair, sweep orphans. Rules: docs/object-storage.md sections 3 and 4.

Order of every delete: the database FIRST (clear the key, set the *_deleted_at time), the object AFTER the commit. So a row
never points to a missing object. If the delete of the object fails, the object is an orphan and the sweep removes it.

Raw pages are deleted 30 days after the FIRST upload (the object's last-modified time, which a skipped re-upload does not
change). A re-fetch of unchanged content therefore does not extend the time.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg

from .base import BUCKET_CLEAN, BUCKET_RAW, ObjectStorage

logger = logging.getLogger("skillforge_data.storage")

RAW_RETENTION = timedelta(days=30)
ORPHAN_AGE = timedelta(hours=24)


@dataclass
class JobReport:
    raw_expired: int = 0              # raw objects deleted because they are 30 days old
    rows_cleared: int = 0             # documents whose raw_object_key was cleared (expiry and repair)
    orphans_deleted: int = 0
    errors: list[str] = field(default_factory=list)


def expire_raw(conn: psycopg.Connection, storage: ObjectStorage, *, now: datetime,
               retention: timedelta = RAW_RETENTION) -> JobReport:
    """Delete raw objects older than `retention` (counted from the first upload)."""
    report = JobReport()
    for obj in list(storage.list(BUCKET_RAW)):
        if now - obj.last_modified < retention:
            continue
        with conn.transaction():                      # 1. the database first: every row with this key
            cleared = conn.execute(
                "UPDATE knowledge.documents SET raw_deleted_at = %s, raw_object_key = NULL WHERE raw_object_key = %s",
                (now, obj.key),
            ).rowcount
        report.rows_cleared += cleared
        try:
            storage.delete(BUCKET_RAW, obj.key)       # 2. the object after the commit
            report.raw_expired += 1
        except Exception as exc:  # noqa: BLE001 - the sweep removes the orphan later
            report.errors.append(f"could not delete raw {obj.key}: {exc}")
            logger.warning("could not delete raw %s: %s", obj.key, exc)
    return report


def reconcile_raw(conn: psycopg.Connection, storage: ObjectStorage, *, now: datetime) -> JobReport:
    """Repair rows whose raw object is gone (for example removed by the 35-day bucket rule): clear the key."""
    report = JobReport()
    keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT raw_object_key FROM knowledge.documents WHERE raw_object_key IS NOT NULL").fetchall()]
    for key in keys:
        if storage.exists(BUCKET_RAW, key):
            continue
        with conn.transaction():
            report.rows_cleared += conn.execute(
                "UPDATE knowledge.documents SET raw_deleted_at = %s, raw_object_key = NULL WHERE raw_object_key = %s",
                (now, key),
            ).rowcount
        logger.warning("raw object %s was missing; cleared the key", key)
    return report


def sweep_orphans(conn: psycopg.Connection, storage: ObjectStorage, *, now: datetime,
                  age: timedelta = ORPHAN_AGE) -> JobReport:
    """Delete objects that no row references and that are older than `age` (a crash between upload and commit).

    Clean text is also kept while its document is alive: other extraction versions of a live document stay until the
    rebuild that switches `active_config` removes them (TODO).
    """
    report = JobReport()
    raw_keys = {r[0] for r in conn.execute(
        "SELECT raw_object_key FROM knowledge.documents WHERE raw_object_key IS NOT NULL").fetchall()}
    clean_keys = {r[0] for r in conn.execute(
        "SELECT clean_object_key FROM knowledge.documents WHERE clean_object_key IS NOT NULL").fetchall()}
    live_documents = {str(r[0]) for r in conn.execute(
        "SELECT id FROM knowledge.documents WHERE clean_deleted_at IS NULL").fetchall()}
    for bucket, referenced in ((BUCKET_RAW, raw_keys), (BUCKET_CLEAN, clean_keys)):
        for obj in list(storage.list(bucket)):
            if obj.key in referenced or now - obj.last_modified < age:
                continue
            if bucket == BUCKET_CLEAN and _document_id_of(obj.key) in live_documents:
                continue
            try:
                storage.delete(bucket, obj.key)
                report.orphans_deleted += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"could not delete orphan {bucket}/{obj.key}: {exc}")
    return report


def run_daily_storage_job(conn: psycopg.Connection, storage: ObjectStorage, *, now: datetime) -> JobReport:
    """Expire, repair, then sweep. Scheduling it daily is DE-14."""
    total = JobReport()
    for step in (expire_raw, reconcile_raw, sweep_orphans):
        part = step(conn, storage, now=now)
        total.raw_expired += part.raw_expired
        total.rows_cleared += part.rows_cleared
        total.orphans_deleted += part.orphans_deleted
        total.errors += part.errors
    logger.info("storage job: %s", total)
    return total


def _document_id_of(clean_object_key: str) -> str | None:
    first = clean_object_key.split("/", 1)[0]
    try:
        return str(uuid.UUID(first))
    except ValueError:
        return None
