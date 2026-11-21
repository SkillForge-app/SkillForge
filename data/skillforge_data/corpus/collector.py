"""DE-08: collect public SKILL.md files, under the licence policy of `skillforge_data/licensing.py` (policy (a)).

For every file found:

1. The licence of the repository is asked once per repository per run. If the policy refuses it (or it is unknown), the file is **only
   counted**: it is not downloaded, not hashed, not stored. If the file was stored earlier and the licence of its repository is refused
   now, the source is **withdrawn** (deleted with its documents) so it cannot be used as an example any more.
2. If it is allowed, the file is downloaded, hashed (sha256) and stored as a `skill_md` source (url, licence, `license_source = 'repo'`)
   with one document row (content hash, fetch date) through `knowledge.record_document_version`; the bytes go to the raw bucket when a
   storage is given. Running again with the same files changes nothing but `fetched_at` (case 1 of that function).

Every call to GitHub waits for the per-host pause of the crawler's rate limiter.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import psycopg

from ..crawler.ratelimit import HostRateLimiter
from ..licensing import check_skill_file_licence, register_skill_file
from ..storage.base import BUCKET_RAW, ObjectStorage
from ..storage.keys import raw_key
from .github import GitHubClient, SkillFileHit

logger = logging.getLogger("skillforge_data.corpus")

MAX_FILE_BYTES = 1024 * 1024         # assumption: a SKILL.md over 1 MB is not a skill; it is counted as failed
MAX_TITLE_CHARS = 200                # documents.title limit


@dataclass
class CorpusReport:
    found: int = 0                   # files returned by the search
    stored: int = 0                  # new files stored (new document)
    unchanged: int = 0               # allowed files whose content was already stored
    updated: int = 0                 # allowed files whose content changed (a new document version)
    refused: int = 0                 # refused by the policy: nothing about them was stored
    withdrawn: int = 0               # stored earlier, now refused: removed
    failed: int = 0
    refused_by_licence: Counter[str] = field(default_factory=Counter)      # "GPL-3.0-only" or "unknown": counts only
    errors: list[str] = field(default_factory=list)


class CorpusCollector:
    def __init__(
        self,
        conn: psycopg.Connection,
        client: GitHubClient,
        *,
        storage: ObjectStorage | None = None,
        limiter: HostRateLimiter | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        pipeline_version: str = "corpus-1",
    ) -> None:
        self._conn = conn
        self._client = client
        self._storage = storage
        self._limiter = limiter or HostRateLimiter(1.0)
        self._now = now
        self._pipeline_version = pipeline_version

    def run(self, *, query: str = "filename:SKILL.md", max_files: int = 1000, max_pages: int = 100) -> CorpusReport:
        report = CorpusReport()
        licences: dict[str, str | None] = {}                     # repository -> SPDX id, asked once per run
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            self._limiter.wait("github-api")
            hits = self._client.search_skill_files(query, page=page)
            if not hits:
                break
            for hit in hits:
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                if report.found >= max_files:
                    return report
                report.found += 1
                try:
                    self._handle(hit, licences, report)
                except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
                    report.failed += 1
                    report.errors.append(f"{hit.url}: {type(exc).__name__}: {exc}")
                    logger.warning("corpus: %s failed: %s", hit.url, exc)
        return report

    def _handle(self, hit: SkillFileHit, licences: dict[str, str | None], report: CorpusReport) -> None:
        if hit.repo not in licences:
            self._limiter.wait("github-api")
            licences[hit.repo] = self._client.repo_licence(hit.repo)
        decision = check_skill_file_licence(licences[hit.repo])
        if not decision.allowed:
            report.refused += 1
            report.refused_by_licence[decision.license] += 1
            if self._withdraw(hit.url):
                report.withdrawn += 1
            return                                               # the file is not even downloaded

        self._limiter.wait("github-content")
        content = self._client.fetch_file(hit)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"file is {len(content)} bytes, over the {MAX_FILE_BYTES} limit")
        content_hash = hashlib.sha256(content).hexdigest()
        host = (urlsplit(hit.url).hostname or "").lower()
        key = raw_key(host, content_hash, "text/markdown") if self._storage is not None else None
        title = f"{hit.repo}: {hit.path}"[:MAX_TITLE_CHARS]
        with self._conn.transaction():
            _, record = register_skill_file(self._conn, hit.url, licences[hit.repo])
            if record is None:                                   # cannot happen after the check above; never store on doubt
                report.refused += 1
                return
            before = self._conn.execute(
                "SELECT count(*), coalesce(bool_or(content_hash = %s AND is_current), false) "
                "FROM knowledge.documents WHERE source_id = %s", (content_hash, record.source_id)).fetchone()
            self._conn.execute(
                "SELECT knowledge.record_document_version(%s, %s, %s, %s, %s, %s, NULL, 200, %s)",
                (record.source_id, content_hash, self._now(), title, record.license, self._pipeline_version, key))
        if self._storage is not None and key is not None:
            self._storage.put(BUCKET_RAW, key, content, content_type="text/markdown")
        if before[1]:
            report.unchanged += 1
        elif before[0]:
            report.updated += 1
        else:
            report.stored += 1

    def _withdraw(self, url: str) -> bool:
        """A refused file that is already stored is removed (its documents go with it). True if something was removed."""
        with self._conn.transaction():
            row = self._conn.execute(
                "DELETE FROM knowledge.sources WHERE url = %s AND source_type = 'skill_md' RETURNING id", (url,)).fetchone()
        if row:
            logger.warning("corpus: %s withdrawn: the licence of its repository is not allowed (any more)", url)
        return row is not None
