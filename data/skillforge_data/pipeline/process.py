"""DE-05: process one fetched page: normalise the URL, extract, chunk, embed and store, safely and idempotently.

Order of the work, and why (decision for the open point in docs/data-architecture.md, no schema change):

1. Everything that can fail is done FIRST, before the database says anything about a new version: normalise the URL,
   upload the raw bytes, extract, remove repeated chunks, embed, check the vectors.
2. Then ONE database transaction does all of this together: `record_document_version()` (which makes the new
   version current and hides the old one), the verdict of the page, the new chunks and embeddings, the removal of the
   old versions' chunks and embeddings (the cascade removes the embeddings), and `clean_deleted_at` on the old
   documents. If anything in it fails, nothing of it happens: the old version is still current, with its chunks.
   Backend's condition ("old chunks go only after the new ones are stored, in the same transaction") holds, and so
   does "the page stays visible until the new content is ready".
3. After the commit: delete the old clean-text objects (database first, then the object) and store the new clean text.
   The clean text key contains the document id, which exists only after step 2, so its upload cannot come earlier;
   the row gets `clean_object_key` only after the object exists.

A failure is logged, counted in `crawl_runs.pages_failed` (with the error text) and returned; it is never raised.
"""
from __future__ import annotations

import hashlib
import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

from ..interfaces import (
    Embed,
    ExtractedChunk,
    ExtractedPage,
    ExtractPage,
    NormaliseUrl,
    PipelineError,
)
from ..storage.base import BUCKET_CLEAN, BUCKET_RAW, ObjectStorage
from ..storage.keys import clean_key, raw_key
from ..store import bump_crawl_run, set_source_domains, upsert_source
from .config import PipelineConfig

logger = logging.getLogger("skillforge_data.pipeline")

MAX_TITLE_CHARS = 200
UNIT_NORM_TOLERANCE = 0.001      # same as the CHECK on embeddings


@dataclass(frozen=True)
class RawPage:
    """One fetched page, as the crawler (DE-04) hands it over."""

    url: str                              # the URL that was fetched (any spelling)
    content: bytes
    fetched_at: datetime                  # timezone-aware
    domains: Sequence[str]                # skill domains the source serves; copied to embeddings.domains
    http_status: int | None = 200
    content_type: str | None = None
    license: str = "unknown"
    license_source: str = "unknown"
    source_type: str = "web_page"
    crawl_run_id: uuid.UUID | None = None


@dataclass
class ProcessResult:
    status: Literal["processed", "unchanged", "rejected", "failed"]
    source_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    chunks_stored: int = 0
    duplicate_chunks_dropped: int = 0
    superseded_chunks_deleted: int = 0
    active: bool = False                  # True when the stored chunk set is the one in active_config
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def process_document(
    conn: psycopg.Connection,
    page: RawPage,
    *,
    config: PipelineConfig,
    extract: ExtractPage,
    embed: Embed,
    normalise_url: NormaliseUrl,
    storage: ObjectStorage | None = None,
) -> ProcessResult:
    """Process one page. Running it again on the same content changes nothing."""
    try:
        return _process(conn, page, config, extract, embed, normalise_url, storage)
    except Exception as exc:                      # a failed page must never stop a crawl; the old content stays
        logger.exception("processing failed for %s", page.url)
        _record_failure(conn, page, exc)
        return ProcessResult(status="failed", error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------------------------------------------
def _process(conn, page, config, extract, embed, normalise_url, storage) -> ProcessResult:
    canonical = _canonical_url(page.url, normalise_url)
    host = (urlsplit(canonical).hostname or "").lower()
    if not host:
        raise PipelineError(f"no host in URL: {canonical}")
    domains = _check_domains(page.domains)
    content_hash = hashlib.sha256(page.content).hexdigest()
    chunk_config_hash = config.chunk_config_hash()

    source_id = upsert_source(
        conn, url=canonical, host=host, source_type=page.source_type,
        license=page.license, license_source=page.license_source,
    )
    set_source_domains(conn, source_id, domains)

    # Same content already processed under this config: only refresh the fetch time (case 1 of the function).
    existing = _find_document(conn, source_id, content_hash, chunk_config_hash, config.pipeline_version)
    if existing is not None and existing["is_current"] and existing["processed"]:
        with conn.transaction():
            _record_version(conn, source_id, content_hash, page, existing["title"], config, None)
        return ProcessResult(status="unchanged", source_id=source_id, document_id=existing["id"],
                             active=_is_active(conn, config))

    raw_object_key = None
    if storage is not None:
        raw_object_key = raw_key(host, content_hash, page.content_type)
        storage.put(BUCKET_RAW, raw_object_key, page.content, content_type=page.content_type, metadata={
            "source-url": canonical,
            "crawl-run-id": str(page.crawl_run_id or ""),
            "fetched-at": page.fetched_at.isoformat(),
        })

    extracted = extract(page.content, url=canonical, retrieved=page.fetched_at.date())
    _check_extracted(extracted)
    chunks, dropped = _drop_repeated_chunks(extracted.chunks)
    if dropped:
        logger.warning("%s: %d repeated chunk_id dropped (kept the first of each)", canonical, dropped)

    vectors: list[list[float]] = []
    if extracted.quality_ok and chunks:
        vectors = _embed_chunks(embed, chunks, config)

    with conn.transaction():
        document_id = _record_version(conn, source_id, content_hash, page, extracted.title, config, raw_object_key)
        conn.execute(
            "UPDATE knowledge.documents SET language = %s, quality_ok = %s, quality_reasons = %s, "
            "screening = %s, status = %s WHERE id = %s",
            (extracted.language, extracted.quality_ok, list(extracted.quality_reasons),
             Jsonb(dict(extracted.screening)) if extracted.screening is not None else None,
             "embedded" if extracted.quality_ok else "cleaned", document_id),
        )
        conn.execute(
            "INSERT INTO knowledge.active_config (chunk_config_hash, embedding_version) VALUES (%s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (chunk_config_hash, config.embedding_version),
        )
        # a retry or a re-chunk of this very document starts from a clean slate for this config
        conn.execute("DELETE FROM knowledge.chunks WHERE document_id = %s AND chunk_config_hash = %s",
                     (document_id, chunk_config_hash))
        if extracted.quality_ok:
            _insert_chunks(conn, document_id, chunks, vectors, domains, config, chunk_config_hash)
        superseded_deleted, stale_clean_keys = _remove_superseded(conn, source_id, document_id)
        active = _is_active(conn, config)

    result = ProcessResult(
        status="processed" if extracted.quality_ok else "rejected",
        source_id=source_id, document_id=document_id, chunks_stored=len(chunks) if extracted.quality_ok else 0,
        duplicate_chunks_dropped=dropped, superseded_chunks_deleted=superseded_deleted, active=active,
    )
    _after_commit(conn, storage, config, extracted, result, stale_clean_keys)
    return result


def _canonical_url(url: str, normalise_url: NormaliseUrl) -> str:
    try:
        return normalise_url(url)
    except ValueError as exc:
        raise PipelineError(f"not an http(s) URL: {url!r}") from exc


def _check_domains(domains: Sequence[str]) -> list[str]:
    cleaned = [d.strip() for d in domains]
    if not cleaned or any(not d for d in cleaned):
        raise PipelineError("a page needs at least one non-blank skill domain (embeddings.domains)")
    if len(set(cleaned)) != len(cleaned):
        raise PipelineError("skill domains must not repeat")
    return cleaned


def _find_document(conn, source_id, content_hash, chunk_config_hash, pipeline_version) -> dict | None:
    row = conn.execute(
        """
        SELECT d.id, d.is_current, d.title, d.quality_ok, d.status, d.pipeline_version,
               EXISTS (SELECT 1 FROM knowledge.chunks c
                       WHERE c.document_id = d.id AND c.chunk_config_hash = %s) AS has_chunks
        FROM knowledge.documents d WHERE d.source_id = %s AND d.content_hash = %s
        """,
        (chunk_config_hash, source_id, content_hash),
    ).fetchone()
    if row is None:
        return None
    doc_id, is_current, title, quality_ok, status, doc_version, has_chunks = row
    rejected_and_done = (not quality_ok) and status == "cleaned" and doc_version == pipeline_version
    return {"id": doc_id, "is_current": is_current, "title": title,
            "processed": bool(has_chunks) or rejected_and_done}


def _record_version(conn, source_id, content_hash, page, title, config, raw_object_key) -> uuid.UUID:
    row = conn.execute(
        "SELECT knowledge.record_document_version(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (source_id, content_hash, page.fetched_at, title, page.license, config.pipeline_version,
         page.crawl_run_id, page.http_status, raw_object_key),
    ).fetchone()
    return row[0]


def _check_extracted(page: ExtractedPage) -> None:
    title = page.title.strip() if page.title else ""
    if not title or len(page.title) > MAX_TITLE_CHARS:
        raise PipelineError("the page has no usable title (empty or longer than 200 characters)")
    if not page.quality_ok and not page.quality_reasons:
        raise PipelineError("a rejected page must come with at least one reason")
    if not page.quality_ok and page.chunks:
        raise PipelineError("a rejected page must not have chunks")


def _drop_repeated_chunks(chunks: Sequence[ExtractedChunk]) -> tuple[list[ExtractedChunk], int]:
    """Keep the first chunk (lowest position) of each chunk_id; AI's own rule for repeated text on a page."""
    seen: set[str] = set()
    kept: list[ExtractedChunk] = []
    for chunk in sorted(chunks, key=lambda c: c.position):
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        kept.append(chunk)
    return kept, len(chunks) - len(kept)


def _embed_chunks(embed: Embed, chunks: Sequence[ExtractedChunk], config: PipelineConfig) -> list[list[float]]:
    vectors = [list(map(float, v)) for v in embed([c.text for c in chunks])]
    if len(vectors) != len(chunks):
        raise PipelineError(f"embed() returned {len(vectors)} vectors for {len(chunks)} chunks")
    for vector in vectors:
        if len(vector) != config.embedding_dimensions:
            raise PipelineError(f"vector has {len(vector)} dimensions, expected {config.embedding_dimensions}")
        if abs(math.sqrt(sum(x * x for x in vector)) - 1.0) >= UNIT_NORM_TOLERANCE:
            raise PipelineError("vector is not unit length")
    return vectors


def _insert_chunks(conn, document_id, chunks, vectors, domains, config, chunk_config_hash) -> None:
    chunk_config = Jsonb(config.chunk_config())
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk_uuid = uuid.uuid4()
        # No ON CONFLICT: a repeated chunk_id that got through must fail loudly (docs, "chunk_id" section).
        conn.execute(
            "INSERT INTO knowledge.chunks (id, chunk_id, document_id, chunk_index, text, word_count, section, "
            "concepts, content_hash, chunk_config, chunk_config_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (chunk_uuid, chunk.chunk_id, document_id, chunk.position, chunk.text, chunk.word_count,
             list(chunk.section), list(chunk.concepts), chunk.content_hash, chunk_config, chunk_config_hash),
        )
        conn.execute(
            "INSERT INTO knowledge.embeddings (chunk_id, embedding, embedding_model, embedding_version, domains) "
            "VALUES (%s, %s::vector, %s, %s, %s)",
            (chunk_uuid, "[" + ",".join(repr(x) for x in vector) + "]", config.embedding_model,
             config.embedding_version, list(domains)),
        )


def _remove_superseded(conn, source_id, current_document_id) -> tuple[int, list[str]]:
    """Delete the chunks (and, by cascade, the embeddings) of the source's older documents.

    Part of the same transaction as the new version, so it only happens when the new version is stored.
    Also clears clean_object_key and sets clean_deleted_at; the objects themselves go after the commit.
    """
    old = conn.execute(
        "SELECT id, clean_object_key FROM knowledge.documents WHERE source_id = %s AND id <> %s",
        (source_id, current_document_id),
    ).fetchall()
    if not old:
        return 0, []
    old_ids = [row[0] for row in old]
    deleted = conn.execute("DELETE FROM knowledge.chunks WHERE document_id = ANY(%s)", (old_ids,)).rowcount
    conn.execute(
        "UPDATE knowledge.documents SET clean_object_key = NULL, clean_deleted_at = now() "
        "WHERE id = ANY(%s) AND clean_object_key IS NOT NULL AND clean_deleted_at IS NULL",
        (old_ids,),
    )
    return deleted, [row[1] for row in old if row[1]]


def _is_active(conn, config: PipelineConfig) -> bool:
    row = conn.execute(
        "SELECT chunk_config_hash = %s AND embedding_version = %s FROM knowledge.active_config",
        (config.chunk_config_hash(), config.embedding_version),
    ).fetchone()
    return bool(row and row[0])


def _after_commit(conn, storage, config, extracted: ExtractedPage, result: ProcessResult, stale_clean_keys) -> None:
    """Object storage work after the commit. Problems here are warnings: the database is already consistent."""
    if storage is None:
        return
    for key in stale_clean_keys:                      # the database no longer points to them
        try:
            storage.delete(BUCKET_CLEAN, key)
        except Exception as exc:  # noqa: BLE001 - the DB is consistent; a storage problem is a warning
            result.warnings.append(f"could not delete old clean text {key}: {exc}")
            logger.warning("could not delete old clean text %s: %s", key, exc)
    if not extracted.quality_ok:
        return
    key = clean_key(result.document_id, config.clean_key_fingerprint())
    try:
        storage.put(BUCKET_CLEAN, key, extracted.text.encode("utf-8"), content_type="text/plain",
                    metadata={"source-url": extracted.url})
        with conn.transaction():                      # the row points to the object only after it exists
            conn.execute("UPDATE knowledge.documents SET clean_object_key = %s WHERE id = %s",
                         (key, result.document_id))
    except Exception as exc:  # noqa: BLE001 - same: warning only
        result.warnings.append(f"clean text not stored: {exc}")
        logger.warning("clean text of %s not stored: %s", result.document_id, exc)


def _record_failure(conn: psycopg.Connection, page: RawPage, exc: Exception) -> None:
    if page.crawl_run_id is None:
        return
    try:
        bump_crawl_run(conn, page.crawl_run_id, "pages_failed", f"{page.url}: {type(exc).__name__}: {exc}")
    except Exception:
        logger.exception("could not record the failure of %s in crawl_runs", page.url)
