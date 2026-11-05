-- DE-02 benchmark: build the HNSW index after loading. Same definition as db/schema-draft.sql
-- (m = 16, ef_construction = 64, cosine). Usage:
--   psql -d skillforge_bench -v mwm=512MB -v workers=2 -f build_index.sql
\set ON_ERROR_STOP on
\timing on
SET maintenance_work_mem = :'mwm';
SET max_parallel_maintenance_workers = :workers;
CREATE INDEX embeddings_hnsw_cosine_idx
    ON knowledge.embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
ANALYZE knowledge.embeddings;
SELECT pg_size_pretty(pg_relation_size('knowledge.embeddings_hnsw_cosine_idx')) AS hnsw_index_size,
       pg_size_pretty(pg_relation_size('knowledge.embeddings')) AS embeddings_heap;
