"""Small database helpers shared by the crawler and the pipeline: sources, their domains and crawl runs.

All functions take an open psycopg connection and run their own `conn.transaction()` block, so they work with an
autocommit connection (a real transaction) and inside a transaction that is already open (a savepoint, as in tests).
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

CRAWL_COUNTERS = ("pages_fetched", "pages_unchanged", "pages_duplicate", "pages_blocked", "pages_failed")


def upsert_source(
    conn: psycopg.Connection,
    *,
    url: str,
    host: str,
    source_type: str = "web_page",
    license: str = "unknown",
    license_source: str = "unknown",
    robots_allowed: bool | None = None,
    robots_checked_at: datetime | None = None,
) -> uuid.UUID:
    """Insert the source, or update what may change between fetches.

    A known licence is never replaced by 'unknown', and an unchecked robots flag never erases a checked one.
    """
    with conn.transaction():
        row = conn.execute(
            """
            INSERT INTO knowledge.sources
                (url, host, source_type, license, license_source, robots_allowed, robots_checked_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                license = CASE WHEN EXCLUDED.license <> 'unknown' THEN EXCLUDED.license
                               ELSE knowledge.sources.license END,
                license_source = CASE WHEN EXCLUDED.license <> 'unknown' THEN EXCLUDED.license_source
                                      ELSE knowledge.sources.license_source END,
                robots_allowed = COALESCE(EXCLUDED.robots_allowed, knowledge.sources.robots_allowed),
                robots_checked_at = COALESCE(EXCLUDED.robots_checked_at, knowledge.sources.robots_checked_at)
            RETURNING id
            """,
            (url, host, source_type, license, license_source, robots_allowed, robots_checked_at),
        ).fetchone()
    return row[0]


def set_source_domains(conn: psycopg.Connection, source_id: uuid.UUID, domains: Sequence[str]) -> None:
    """Record which skill domains the source serves (idempotent)."""
    with conn.transaction():
        for domain in domains:
            conn.execute(
                "INSERT INTO knowledge.source_domains (source_id, skill_domain) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (source_id, domain),
            )


def start_crawl_run(
    conn: psycopg.Connection,
    *,
    user_agent: str,
    pipeline_version: str,
    config: dict[str, Any],
    skill_domain: str | None = None,
) -> uuid.UUID:
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO knowledge.crawl_runs (user_agent, pipeline_version, config, skill_domain) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user_agent, pipeline_version, Jsonb(config), skill_domain),
        ).fetchone()
    return row[0]


def bump_crawl_run(conn: psycopg.Connection, run_id: uuid.UUID, counter: str, error: str | None = None) -> None:
    """Add one to a counter of the run (and keep the latest error text, if given)."""
    if counter not in CRAWL_COUNTERS:
        raise ValueError(f"unknown crawl_runs counter: {counter}")
    with conn.transaction():
        conn.execute(
            f"UPDATE knowledge.crawl_runs SET {counter} = {counter} + 1, "
            "error = COALESCE(left(%s, 2000), error) WHERE id = %s",
            (error, run_id),
        )


def finish_crawl_run(conn: psycopg.Connection, run_id: uuid.UUID, status: str, error: str | None = None) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE knowledge.crawl_runs SET status = %s, finished_at = now(), "
            "error = COALESCE(left(%s, 2000), error) WHERE id = %s",
            (status, error, run_id),
        )
