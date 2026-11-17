"""The daily job of the data layer: the raw-page job of DE-03, then the retention rules of DE-13. Scheduling it is DE-14.

Order: raw expiry and repair first (they clear keys in the database), then retention (rows first, objects after), and the orphan sweep
last, so it also removes any object a failed delete left behind.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from .base import ObjectStorage
from .jobs import JobReport, expire_raw, reconcile_raw, sweep_orphans
from .retention import RetentionReport, run_daily_retention_job


@dataclass
class DailyReport:
    storage: JobReport
    retention: RetentionReport

    @property
    def errors(self) -> list[str]:
        return [*self.storage.errors, *self.retention.errors]


def run_daily_jobs(conn: psycopg.Connection, storage: ObjectStorage, *, now: datetime) -> DailyReport:
    total = JobReport()
    for step in (expire_raw, reconcile_raw):
        part = step(conn, storage, now=now)
        total.raw_expired += part.raw_expired
        total.rows_cleared += part.rows_cleared
        total.errors += part.errors
    retention = run_daily_retention_job(conn, storage, now=now)
    swept = sweep_orphans(conn, storage, now=now)
    total.orphans_deleted += swept.orphans_deleted
    total.errors += swept.errors
    return DailyReport(total, retention)
