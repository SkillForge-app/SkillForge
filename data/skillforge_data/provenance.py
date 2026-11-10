"""DE-06: provenance. Every chunk can be traced to its source: URL, retrieval date, licence, content hash, crawl run.

`chunk_provenance` (db/knowledge_views.sql) gives chunk -> url, host, retrieved_at, license, the hashes, the crawl run, the page
title, the pipeline version and the chunk config hash (the last four were added once AI approved docs/proposals/de-06-provenance.md).
`check_provenance` is the "every chunk traceable" test of the task plan, as a function that can also run as a data-quality check
(DE-11).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import psycopg

from .storage.base import BUCKET_RAW, ObjectNotFound, ObjectStorage


@dataclass(frozen=True)
class Provenance:
    chunk_id: str
    chunk_uuid: uuid.UUID
    url: str
    host: str
    retrieved_at: datetime
    license: str
    chunk_hash: str
    document_hash: str
    document_id: uuid.UUID
    source_id: uuid.UUID
    crawl_run_id: uuid.UUID | None
    title: str
    pipeline_version: str
    chunk_config_hash: str


@dataclass
class ProvenanceReport:
    chunks_checked: int = 0
    problems: list[str] = field(default_factory=list)       # each one is a chunk or document that cannot be traced
    unknown_license: int = 0                                # traceable, but the licence is not known (allowed, DE-08)
    without_crawl_run: int = 0                              # traceable, but no crawl run (for example a manual import)

    @property
    def ok(self) -> bool:
        return not self.problems


def get_provenance(conn: psycopg.Connection, chunk_id: str) -> list[Provenance]:
    """Where did this chunk come from? One row per stored chunk with that id (old documents' chunks too, if any)."""
    rows = conn.execute(
        """
        SELECT p.chunk_id, p.chunk_uuid, p.url, p.host, p.retrieved_at, p.license, p.chunk_hash, p.document_hash,
               p.document_id, p.source_id, p.crawl_run_id, p.page_title, p.pipeline_version, p.chunk_config_hash
        FROM knowledge.chunk_provenance p
        WHERE p.chunk_id = %s
        ORDER BY p.retrieved_at DESC
        """,
        (chunk_id,),
    ).fetchall()
    return [Provenance(*row) for row in rows]


def check_provenance(conn: psycopg.Connection, storage: ObjectStorage | None = None) -> ProvenanceReport:
    """Check that every stored chunk is traceable and that its hashes are true.

    - the chunk appears in `chunk_provenance` with a URL, a retrieval time and a licence;
    - `chunks.content_hash` is the sha256 of `chunks.text`;
    - with `storage`: `documents.content_hash` is the sha256 of the raw object, for documents whose raw object still exists.
    """
    report = ProvenanceReport()
    report.chunks_checked = conn.execute("SELECT count(*) FROM knowledge.chunks").fetchone()[0]

    for chunk_id, doc_id in conn.execute(
        """
        SELECT c.chunk_id, c.document_id
        FROM knowledge.chunks c
        LEFT JOIN knowledge.chunk_provenance p ON p.chunk_uuid = c.id
        WHERE p.chunk_uuid IS NULL OR coalesce(p.url, '') = '' OR p.retrieved_at IS NULL
           OR coalesce(p.license, '') = '' OR coalesce(p.document_hash, '') = ''
        """
    ).fetchall():
        report.problems.append(f"chunk {chunk_id} (document {doc_id}) is missing url, retrieval time, licence or hash")

    for chunk_id, doc_id in conn.execute(
        "SELECT chunk_id, document_id FROM knowledge.chunks "
        "WHERE content_hash <> encode(sha256(convert_to(text, 'UTF8')), 'hex')"
    ).fetchall():
        report.problems.append(f"chunk {chunk_id} (document {doc_id}): content_hash is not the sha256 of its text")

    report.unknown_license = conn.execute(
        "SELECT count(*) FROM knowledge.chunks c JOIN knowledge.documents d ON d.id = c.document_id "
        "WHERE d.license = 'unknown'"
    ).fetchone()[0]
    report.without_crawl_run = conn.execute(
        "SELECT count(*) FROM knowledge.chunks c JOIN knowledge.documents d ON d.id = c.document_id "
        "WHERE d.crawl_run_id IS NULL"
    ).fetchone()[0]

    if storage is not None:
        for doc_id, key, content_hash in conn.execute(
            "SELECT id, raw_object_key, content_hash FROM knowledge.documents WHERE raw_object_key IS NOT NULL"
        ).fetchall():
            try:
                actual = hashlib.sha256(storage.get(BUCKET_RAW, key)).hexdigest()
            except ObjectNotFound:
                report.problems.append(f"document {doc_id}: raw object {key} is missing but the row points to it")
                continue
            if actual != content_hash:
                report.problems.append(f"document {doc_id}: raw object {key} does not match content_hash")
    return report
