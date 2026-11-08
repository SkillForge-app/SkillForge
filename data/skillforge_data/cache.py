"""DE-09: the domain knowledge cache. "A second request in the same domain reuses the cache."

A skill domain is covered when it has enough fresh, current, readable documents (docs/data-architecture.md, "DE-09 cache
lookup"). Pages are shared between skills: a source can serve several domains, and a domain also counts the sources of its parents
and children, the same rule AI's retrieval filter uses (`domains && [domain and parents]` or a child `LIKE 'domain/%'`).

What counts as a usable document: current, not a duplicate (DE-07), passed the quality check, processed (`status = 'embedded'`),
and fetched within the freshness window of its source type. Everything is a function of the database and of `now`, so it can be
tested with any clock and called by any scheduler (DE-14).

Not here (TODO): the per-host site-boilerplate record, which needs a small table (docs/proposals/de-09-host-boilerplate.md).
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import psycopg

from .freshness import FreshnessRules

logger = logging.getLogger("skillforge_data.cache")


def domain_and_parents(domain: str) -> list[str]:
    """'marketing/email/newsletters' -> ['marketing', 'marketing/email', 'marketing/email/newsletters']."""
    parts = [p for p in domain.strip("/").split("/") if p]
    if not parts:
        raise ValueError("a skill domain must not be empty")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


@dataclass(frozen=True)
class DueSource:
    source_id: uuid.UUID
    url: str
    host: str
    source_type: str
    last_fetched_at: datetime | None       # None: never fetched (no current document)


@dataclass
class CachePlan:
    domain: str
    action: Literal["reuse", "refresh", "crawl"]
    fresh: int                              # usable, fresh documents
    stale: int                              # usable documents that are older than the window
    needed: int                             # min_documents
    stale_sources: list[DueSource] = field(default_factory=list)   # to re-crawl (robots allows)
    missing: int = 0                        # how many more sources are needed (action 'crawl')

    @property
    def covered(self) -> bool:
        return self.fresh >= self.needed


_DOMAIN_FILTER = """
    EXISTS (SELECT 1 FROM knowledge.source_domains sd
            WHERE sd.source_id = s.id
              AND (sd.skill_domain = ANY(%(parents)s) OR sd.skill_domain LIKE %(domain)s || '/%%'))
"""


def plan_domain(conn: psycopg.Connection, domain: str, *, rules: FreshnessRules, now: datetime) -> CachePlan:
    """Decide what a request for `domain` needs: reuse the cache, refresh stale pages, or crawl new sources."""
    rows = conn.execute(
        f"""
        SELECT s.id, s.url, s.host, s.source_type, s.robots_allowed, d.fetched_at
        FROM knowledge.sources s
        JOIN knowledge.documents d ON d.source_id = s.id
        WHERE d.is_current AND d.duplicate_of IS NULL AND d.quality_ok AND d.status = 'embedded'
          AND {_DOMAIN_FILTER}
        """,
        {"parents": domain_and_parents(domain), "domain": domain.strip("/")},
    ).fetchall()
    fresh = 0
    stale_sources: list[DueSource] = []
    for source_id, url, host, source_type, robots_allowed, fetched_at in rows:
        if now - fetched_at <= rules.max_age_for(source_type):
            fresh += 1
        elif robots_allowed is not False:
            stale_sources.append(DueSource(source_id, url, host, source_type, fetched_at))
    stale_sources.sort(key=lambda s: s.last_fetched_at)           # oldest first
    stale = len(rows) - fresh
    needed = rules.min_documents
    if fresh >= needed:
        return CachePlan(domain, "reuse", fresh, stale, needed)
    if fresh + len(stale_sources) >= needed:
        return CachePlan(domain, "refresh", fresh, stale, needed, stale_sources)
    return CachePlan(domain, "crawl", fresh, stale, needed, stale_sources,
                     missing=needed - fresh - len(stale_sources))


def ensure_domain(
    conn: psycopg.Connection,
    domain: str,
    *,
    rules: FreshnessRules,
    now: datetime,
    crawl: Callable[[CachePlan], None],
) -> CachePlan:
    """The request path: plan, and call `crawl(plan)` only if the cache cannot serve the domain.

    A second request in the same domain finds the documents the first one stored and does not call `crawl` ("reuses the cache").
    Returns the plan that was acted on; look at its `action`.
    """
    plan = plan_domain(conn, domain, rules=rules, now=now)
    if plan.action == "reuse":
        logger.info("domain %s: cache hit (%d fresh documents)", domain, plan.fresh)
        return plan
    logger.info("domain %s: %s (fresh %d of %d, stale sources %d)", domain, plan.action, plan.fresh, plan.needed,
                len(plan.stale_sources))
    crawl(plan)
    return plan


def due_for_recrawl(
    conn: psycopg.Connection,
    *,
    rules: FreshnessRules,
    now: datetime,
    domain: str | None = None,
    limit: int | None = None,
) -> list[DueSource]:
    """The re-crawl schedule: sources whose current page is older than its window, or that were never fetched.

    Oldest first (never fetched before all), at most `limit`. Sources that robots.txt forbids (`robots_allowed = false`) are
    never listed. Optionally only the sources of one domain (with its parents and children).
    """
    where = "s.robots_allowed IS DISTINCT FROM false"
    params: dict[str, object] = {}
    if domain is not None:
        where += f" AND {_DOMAIN_FILTER}"
        params = {"parents": domain_and_parents(domain), "domain": domain.strip("/")}
    rows = conn.execute(
        f"""
        SELECT s.id, s.url, s.host, s.source_type, d.fetched_at
        FROM knowledge.sources s
        LEFT JOIN knowledge.documents d ON d.source_id = s.id AND d.is_current
        WHERE {where}
        """,
        params,
    ).fetchall()
    due = [DueSource(*row) for row in rows
           if row[4] is None or now - row[4] > rules.max_age_for(row[3])]
    due.sort(key=lambda s: (s.last_fetched_at is not None, s.last_fetched_at or now, s.url))
    return due[:limit] if limit is not None else due
