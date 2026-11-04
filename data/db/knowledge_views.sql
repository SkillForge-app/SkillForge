-- knowledge_views.sql: the views DE exposes to AI and to the retrieval API.
-- THIS FILE IS THE CONTRACT BETWEEN DE AND AI. Any change (name, columns, types, filters)
-- needs AI's approval. Apply it AFTER db/schema-draft.sql (it reads those tables).

-- ---------------------------------------------------------------------------
-- Provenance (DE-06): every chunk reaches url, retrieved_at, license, content_hash.
-- Not filtered by active_config or is_current: any chunk, old or new, can be traced.
-- chunk_id is AI's id (the one citations use); chunk_uuid is our internal key.
-- ---------------------------------------------------------------------------
CREATE VIEW knowledge.chunk_provenance AS
SELECT c.chunk_id      AS chunk_id,
       c.id            AS chunk_uuid,
       c.content_hash  AS chunk_hash,
       d.id            AS document_id,
       d.content_hash  AS document_hash,
       s.id            AS source_id,
       s.url,
       s.host,
       d.fetched_at    AS retrieved_at,
       d.license                                     -- license as of the latest fetch
FROM knowledge.chunks c
JOIN knowledge.documents d ON d.id = c.document_id
JOIN knowledge.sources   s ON s.id = d.source_id;

-- ---------------------------------------------------------------------------
-- retrievable_chunks: what the retrieval API may return (contract with AI).
-- Only the current version of a document, never an exact/near duplicate, and only the
-- active chunk config. Join embeddings on chunk_uuid and filter by embedding_version.
-- ---------------------------------------------------------------------------
CREATE VIEW knowledge.retrievable_chunks AS
SELECT c.chunk_id      AS chunk_id,
       c.id            AS chunk_uuid,
       c.chunk_index,
       c.text,
       c.content_hash  AS chunk_hash,
       d.id            AS document_id,
       d.content_hash  AS document_hash,
       d.language,
       s.id            AS source_id,
       s.url,
       s.host,
       s.source_type,
       d.fetched_at    AS retrieved_at,
       d.license,
       ARRAY(SELECT sd.skill_domain
             FROM knowledge.source_domains sd
             WHERE sd.source_id = s.id
             ORDER BY sd.skill_domain) AS skill_domains
FROM knowledge.chunks c
JOIN knowledge.active_config ac ON ac.chunk_config_hash = c.chunk_config_hash
JOIN knowledge.documents d ON d.id = c.document_id
JOIN knowledge.sources   s ON s.id = d.source_id
WHERE d.is_current
  AND d.quality_ok
  AND d.duplicate_of IS NULL;

-- ---------------------------------------------------------------------------
-- knowledge_chunks: the view AI reads (agreed 26 Oct 2026). AI reads from this view only,
-- as the read-only role skillforge_ai_reader; our pipeline (DE-05) writes to our tables.
-- Columns follow AI's table; `domain text` became `domains text[]` (one row per chunk).
-- chunk_id is AI's id from extract_page(), title is the page title (never empty), and
-- domains comes from the same table as the embedding, so the view needs no subquery.
-- Only the current, non-duplicate documents, and only the active config and version.
--
-- Read-only: it is a join. AI's own bootstrap (CREATE INDEX ... ON knowledge_chunks)
-- fails on a view; their code must not run pg_schema() against this database.
-- ---------------------------------------------------------------------------
CREATE VIEW knowledge.knowledge_chunks AS
SELECT c.chunk_id                              AS chunk_id,
       s.url                                   AS source_url,
       d.title                                 AS title,
       (d.fetched_at AT TIME ZONE 'UTC')::date AS retrieved,
       c.text                                  AS text,
       c.section                               AS section,
       c.concepts                              AS concepts,
       c.content_hash::char(64)                AS content_hash,
       e.domains                               AS domains,
       e.embedding_model                       AS embedding_model,
       e.embedding                             AS embedding
FROM knowledge.embeddings e
JOIN knowledge.active_config ac ON ac.embedding_version = e.embedding_version
JOIN knowledge.chunks    c ON c.id = e.chunk_id AND c.chunk_config_hash = ac.chunk_config_hash
JOIN knowledge.documents d ON d.id = c.document_id
JOIN knowledge.sources   s ON s.id = d.source_id
WHERE d.is_current
  AND d.quality_ok
  AND d.duplicate_of IS NULL;
