-- SkillForge knowledge store: the contract between Data Engineering and AI (AI-11).
-- Generated from ai/core/knowledge/store.py: pg_schema("knowledge.ai_chunks", 384) and
-- pg_view_sql("knowledge.knowledge_chunks", "knowledge.ai_chunks").
--
-- DE owns the tables. The base table below is an EXAMPLE: DE's real tables may differ, as long
-- as the view knowledge.knowledge_chunks has exactly these columns and types. AI only reads
-- the view, as a read-only user. See retrieval.md ("For Data Engineering: the knowledge view").
--
-- Contract points:
--   chunk_id         AI-10's chunk_id from extract_page (stable across re-crawls), not a uuid
--   title            never empty (AI-10's page title, at most 200 characters)
--   domains          text[], one or more SkillSpec domains, no repeats, one row per chunk
--   embedding_model  exactly 'local/BAAI/bge-small-en-v1.5'
--   embedding        vector(384), unit length, from embed(..., model_role="embedding")
-- Keep domains and the HNSW index on the table that holds the embedding, and keep the view a
-- plain projection (no GROUP BY / DISTINCT / per-row array_agg), so searches use the index.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS "knowledge";
CREATE TABLE IF NOT EXISTS "knowledge"."ai_chunks" (
    chunk_id        text PRIMARY KEY,
    source_url      text NOT NULL,
    title           text NOT NULL,
    retrieved       date NOT NULL,
    text            text NOT NULL,
    section         text[] NOT NULL DEFAULT '{}',
    concepts        text[] NOT NULL DEFAULT '{}',
    content_hash    char(64) NOT NULL,
    domains         text[] NOT NULL CHECK (cardinality(domains) > 0),
    embedding_model text NOT NULL,
    embedding       vector(384) NOT NULL
);
-- HNSW (cosine) on the base table: a view cannot be indexed, but a query through a plain
-- view (no GROUP BY or DISTINCT) still uses this index.
CREATE INDEX IF NOT EXISTS "ai_chunks_embedding_idx"
    ON "knowledge"."ai_chunks" USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS "ai_chunks_source_idx" ON "knowledge"."ai_chunks" (source_url);
-- GIN on domains: serves `domains && ARRAY[domain and its parents]`.
CREATE INDEX IF NOT EXISTS "ai_chunks_domains_idx" ON "knowledge"."ai_chunks" USING gin (domains);

CREATE OR REPLACE VIEW "knowledge"."knowledge_chunks" AS
SELECT
    chunk_id,
    source_url,
    title,
    retrieved,
    text,
    section,
    concepts,
    content_hash,
    domains,
    embedding_model,
    embedding
FROM "knowledge"."ai_chunks";

-- Read-only access for AI's code (role name as in DE's db/roles-local.sql).
GRANT USAGE ON SCHEMA knowledge TO skillforge_ai_reader;
GRANT SELECT ON knowledge.knowledge_chunks TO skillforge_ai_reader;

-- AI's search, for reference (score = 1 - cosine distance; a row matches the query domain
-- when one of its domains equals it, is a parent of it, or lies under it):
--   SELECT chunk_id, source_url, title, retrieved, text, section, concepts, content_hash,
--          domains, 1 - (embedding <=> $vector) AS score
--   FROM "knowledge"."knowledge_chunks"
--   WHERE (domains && $domain_and_parents::text[]
--          OR EXISTS (SELECT 1 FROM unnest(domains) AS d WHERE d LIKE $domain || '/%'))
--   ORDER BY embedding <=> $vector, chunk_id LIMIT $k;
-- With a filter, set hnsw.iterative_scan = relaxed_order (pgvector 0.8+) for the session.
