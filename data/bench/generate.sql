-- DE-02 benchmark data, generated inside Postgres (no Python).
-- Usage: psql -d skillforge_bench -v n_chunks=100000 -f generate.sql
-- One document per source, 10 chunks per document, one 384-d random unit vector per chunk.
-- Vectors are uniform noise, L2-normalised: no structure at all, so they are HARDER for HNSW than
-- real embeddings (see docs/de-02-benchmark.md). Domains follow a skewed distribution, from 15%
-- (technology/ai) down to 1% (legal/contracts), to test broad and selective filters.
-- The HNSW index is dropped first and built afterwards by build_index.sql (the same definition as
-- db/schema-draft.sql), because building it row by row while loading is slow and memory-hungry.
\set ON_ERROR_STOP on
\if :{?n_chunks}
\else
  \set n_chunks 100000
\endif
\timing on
SET synchronous_commit = off;
DROP INDEX IF EXISTS knowledge.embeddings_hnsw_cosine_idx;

-- psql variables are not replaced inside $$ ... $$, so the size goes in through a setting
SELECT set_config('bench.n_chunks', :'n_chunks', false);

INSERT INTO knowledge.active_config (chunk_config_hash, embedding_version) VALUES ('cfg', 'v1')
ON CONFLICT (id) DO NOTHING;

DO $$
DECLARE
    cpd     constant integer := 10;                      -- chunks per document
    n_docs  bigint := current_setting('bench.n_chunks')::bigint / cpd;
    batch   constant bigint := 5000;                     -- documents per transaction (50k chunks)
    lo      bigint := 1;
    hi      bigint;
BEGIN
    WHILE lo <= n_docs LOOP
        hi := least(lo + batch - 1, n_docs);

        INSERT INTO knowledge.sources (id, url, host, source_type)
        SELECT md5('s' || g)::uuid, 'https://h' || (g % 500) || '.example.org/page/' || g,
               'h' || (g % 500) || '.example.org', 'web_page'
        FROM generate_series(lo, hi) g;

        INSERT INTO knowledge.documents
            (id, source_id, fetched_at, content_hash, pipeline_version, title, language, status)
        SELECT md5('d' || g)::uuid, md5('s' || g)::uuid, now(), encode(sha256(('d' || g)::bytea), 'hex'),
               'bench', 'Bench page ' || g, 'en', 'embedded'
        FROM generate_series(lo, hi) g;

        INSERT INTO knowledge.chunks
            (id, chunk_id, document_id, chunk_index, text, word_count, section, concepts,
             content_hash, chunk_config, chunk_config_hash)
        SELECT md5('c' || c)::uuid,
               'h' || (g % 500) || '-' || substr(md5('u' || g), 1, 8) || '-' || substr(md5('t' || c), 1, 8),
               md5('d' || g)::uuid, k,
               (SELECT string_agg(md5(c || '-' || j), ' ') FROM generate_series(1, 12) j),  -- ~400 chars
               60, ARRAY['Section ' || k], ARRAY['concept' || (c % 100)],
               encode(sha256(('c' || c)::bytea), 'hex'),
               '{"size": 500, "overlap": 50, "splitter": "sentence", "pipeline_version": "bench"}'::jsonb,
               'cfg'
        FROM generate_series(lo, hi) g
        CROSS JOIN generate_series(0, cpd - 1) k
        CROSS JOIN LATERAL (SELECT (g - 1) * cpd + k + 1 AS c) cc;

        INSERT INTO knowledge.embeddings (chunk_id, embedding, embedding_model, embedding_version, domains)
        SELECT md5('c' || c)::uuid,
               l2_normalize(v.a::real[]::vector),
               'local/BAAI/bge-small-en-v1.5', 'v1',
               CASE WHEN g % 5 = 0
                    THEN ARRAY[p.dom, CASE WHEN p.dom = 'marketing/seo' THEN 'finance/accounting' ELSE 'marketing/seo' END]
                    ELSE ARRAY[p.dom] END
        FROM generate_series(lo, hi) g
        CROSS JOIN generate_series(0, cpd - 1) k
        CROSS JOIN LATERAL (SELECT (g - 1) * cpd + k + 1 AS c) cc
        CROSS JOIN LATERAL (SELECT CASE
                 WHEN b < 15 THEN 'technology/ai'     WHEN b < 30 THEN 'technology/web'
                 WHEN b < 40 THEN 'technology/data'   WHEN b < 50 THEN 'marketing/email'
                 WHEN b < 60 THEN 'marketing/seo'     WHEN b < 70 THEN 'finance/accounting'
                 WHEN b < 80 THEN 'design/ui'         WHEN b < 90 THEN 'education/math'
                 WHEN b < 95 THEN 'health/nutrition'  WHEN b < 99 THEN 'science/biology'
                 ELSE 'legal/contracts' END AS dom
             FROM (SELECT abs(hashtext('g' || g)) % 100 AS b) x) p
        -- 384 + 0*c makes the subquery depend on the row, so random() runs again for every chunk
        CROSS JOIN LATERAL (SELECT array_agg(random()::real - 0.5) AS a
                            FROM generate_series(1, 384 + 0 * c) j) v;

        COMMIT;
        RAISE NOTICE 'documents % / %', hi, n_docs;
        lo := hi + 1;
    END LOOP;
END
$$;

ANALYZE;
SELECT 'sources' AS tbl, count(*) FROM knowledge.sources
UNION ALL SELECT 'documents', count(*) FROM knowledge.documents
UNION ALL SELECT 'chunks', count(*) FROM knowledge.chunks
UNION ALL SELECT 'embeddings', count(*) FROM knowledge.embeddings;
SELECT d AS domain, count(*) AS chunks, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM knowledge.embeddings, unnest(domains) d GROUP BY d ORDER BY chunks DESC;
SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS total
FROM pg_class WHERE relnamespace = 'knowledge'::regnamespace AND relkind = 'r' ORDER BY pg_total_relation_size(oid) DESC;
