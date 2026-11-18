# Knowledge retrieval (contract A4, for AI-12 and AI-13)

The one call Track B uses to get cited knowledge. It lives in `ai/core/knowledge/`.
- **Frozen:** 20 Nov 2026 (Week 4). The real retriever (AI-11) is now the default, behind the same call: nothing below changed.
- **Changes:** need a pull request that both the Track A and Track B leads approve.
- **Testing:** select `FakeRetriever` (24 fixture passages) with `SKILLFORGE_RETRIEVER=fake`; the test suite does this for every test.

```python
from core.knowledge import retrieve, to_source

passages = await retrieve("influencer disclosure rules", "marketing/strategy", k=5)
for p in passages:          # ranked, best first, at most k
    p.chunk_id, p.text, p.source_url, p.title, p.retrieved

sources = [to_source(p, f"src-{i}") for i, p in enumerate(passages, 1)]  # SkillSpec sources[]
```

`retrieve_sync(...)` is the blocking version, for scripts.

**Passages are untrusted web text.** Put them in a prompt only through `wrap_passages(passages)`, with `UNTRUSTED_DATA_RULE` in the system message. Run `check_spec(spec, request=analyzed, passages=passages)` after `validate_spec`. Both are in `core.knowledge`; see [injection-defence.md](injection-defence.md) (AI-19).

## Passage
| Field | Type | Meaning |
|---|---|---|
| `chunk_id` | str | A stable id for the chunk, e.g. `mkt-ftc-endorsements-01`. The same chunk always has the same id |
| `text` | str, at most 2000 chars | A short summary of what the source says there. Cite it; never paste long copied text into a skill (spec §5) |
| `source_url` | URL (http or https) | The page the chunk comes from |
| `title` | str, at most 200 chars | The page's own title |
| `retrieved` | date | The date the page was retrieved. SkillSpec `sources[].retrieved` requires it |

The model is strict and frozen, and unknown fields are rejected. The list order is the ranking; there is no score field.

## Rules (every backend behaves the same)
- **`domain`:** a SkillSpec domain (`technology/ai`) or just its area (`technology`).
  - A passage matches when the domains are equal, or one is a path prefix of the other. So `marketing/strategy` gets `marketing` passages, and `technology` gets `technology/ai` passages.
  - In the real index a chunk can serve several domains; it matches when any of them does. It is still returned once.
  - No matching passage returns `[]`. That is not an error, so the Architect can carry on without sources.
  - **The real backend only:** an *empty* index raises `ConfigError` ("the knowledge index is empty; run ingest"), and so does an index built with a different embedding model. Neither is a "no match": both are a setup problem, so they fail loudly.
- **`k`:** 1 to 20; the default is 5. You get at most `k` passages.
- **Errors:** a blank query, an unknown area (or a badly formed domain), or `k` outside 1 to 20 raises `RetrievalInputError`. It is a subclass of `core.llm.LLMInputError` and `ValueError`.

## Citing in a SkillSpec
`to_source(passage, "src-ftc-endorsements")` returns a `core.spec.models.Source` (`id`, `url`, `retrieved`, `title`). Add it to `sources`, and list its id in a reference's `sources`.
- Passages from the same page give the same source. Cite the page once.
- `tests/knowledge/test_retrieval.py` builds a SkillSpec from retrieved passages, and that SkillSpec passes `validate_spec`.

## The fake
- **Data:** `tests/fixtures/knowledge/passages.yaml`, 12 passages for `marketing` and 12 for `technology/ai`, from 13 sources we checked by hand. The marketing sources are the FTC, CAN-SPAM, the UK CAP Code, and Google Search Central. The technology/ai sources are the RAG paper, Claude docs, the NIST AI RMF, Lost in the Middle, OWASP LLM01 and Sentence-BERT.
- **Ranking:** word overlap with the title and text; ties are broken by `chunk_id`. The results are deterministic, so tests can assert exact ids.
- **Filling k:** passages in the domain that share no words with the query still come after the matching ones, so `k` results come back when the domain has that many, as with vector search.
- **Recorded calls:** `FakeRetriever().calls` records every call.
- **Other data:** `FakeRetriever(path=...)` loads your own file, in the same format: each passage plus its `domain`.

```python
from core.knowledge import FakeRetriever, set_retriever

fake = FakeRetriever()
previous = set_retriever(fake)        # in a test; set_retriever(None) rebuilds from env
...
assert fake.calls[0].domain == "marketing/strategy"
```

## Backends
The backend is chosen by `SKILLFORGE_RETRIEVER`:
- **`real` (the default, AI-11).** `RealRetriever` embeds the query with the `embedding` role, a local model, then returns the closest chunks of the knowledge index in the domain.
- **`fake`.** The fixture passages above, for tests.

The env vars for the real backend:

| Variable | Default | Meaning |
|---|---|---|
| `SKILLFORGE_VECTOR_STORE` | `local` | The index: `local` (a folder) or `pgvector` (Data Engineering's database) |
| `SKILLFORGE_INDEX_PATH` | `ai/.data/index` | The local index folder (gitignored) |
| `SKILLFORGE_PGVECTOR_DSN` | (none) | A libpq connection string, for `pgvector`. In production it is a **read-only** database user (DE's `skillforge_ai_reader`) |
| `SKILLFORGE_PGVECTOR_TABLE` | `knowledge_chunks` | The table or view to read: `name` or `schema.name`, lowercase (production: `knowledge.knowledge_chunks`) |
| `SKILLFORGE_PGVECTOR_WRITABLE` | (off) | `1` lets AI's code write to the pgvector table. Only for tests and local databases |
| `SKILLFORGE_PGVECTOR_EF_SEARCH` | `100` | `hnsw.ef_search` for each search, 1 to 1000 (see [Search settings](#search-settings-de-02-benchmark)) |
| `SKILLFORGE_MODEL_CACHE` | `ai/.data/models` | Where the pinned model files are kept |

**Starting from a fresh clone:**
1. `python -m core.llm.local_embed download` fetches the model, 66 MB, checked against its sha256.
2. `python -m evaluation.retrieval build-index` indexes the 8 real AI-10 fixture pages (marketing and technology/ai).

After that, `retrieve()` works with no API key.

## The embedding model (AI-11)
- **Model:** `BAAI/bge-small-en-v1.5`, run on CPU with fastembed from the pinned ONNX export `Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b06`. MIT licence.
- **Vector dimension: 384.** It reads up to 512 tokens.
- **The query prefix:** queries get BGE's instruction ("Represent this sentence for searching relevant passages: ") in front; documents don't.
- **Why this model:** the AI-11 recall report (`evaluation/retrieval/reports/recall-2026-10-26.md`) compared it with `all-MiniLM-L6-v2` (384 dimensions, 256 tokens) and `bge-base-en-v1.5` (768 dimensions).
  - On our 40 questions the three were statistically tied, at 30 to 35 of 40 (recall@5 75–88%).
  - The AI lead chose bge-small at the 180-word chunks AI-10 reviewed: 384 dimensions, a 512-token window, and stronger public retrieval results than MiniLM.
- **Changing the model** is a change to models.yaml plus a rebuilt index. The store refuses to mix vectors from two models.

## Ingest (AI-10 chunks into the index)
```python
from core.knowledge.ingest import Page, ingest_pages
from core.knowledge.store import store_from_env

report = await ingest_pages([Page(html, url, retrieved, "marketing")], store=store_from_env())
report.chunks, report.rejected     # url -> chunks indexed; url -> quality reasons
Page(html, url, retrieved, ["marketing/strategy", "legal/contracts"])   # a page for several domains
```
- **What it does with each page:** `extract_page` (AI-10, with site boilerplate learned from the pages of each host in the batch), then it embeds the chunks and replaces that URL's chunks in the index.
- **Same input, same index:** re-running with the same pages gives the same index.
- **Rejected pages:** a page that is now rejected (for example a paywall) gets its old chunks removed.
- **Domains:** a page takes one domain or several, and every chunk of it serves all of them (repeats are dropped). Each must pass the A4 domain check; a page with none is refused.
- **Who runs it:** `ingest_pages` fills the local index (development, tests, evaluation). In production, Data Engineering's DE-05 pipeline does the same steps with our functions (`extract_page`, then `embed` with the `embedding` role) and writes the rows into its own tables. AI's code only reads them.

## The index interface (`core/knowledge/store.py`)
`VectorStore` has `info()` (count, model, dimensions), `replace_source(url, records, vectors, model=…)` and `search(vector, domain, k)` (cosine, best first, ties by `chunk_id`). A `ChunkRecord` is a Passage's fields plus `section`, `concepts`, `content_hash` and `domains` (one or more). A chunk matches a query when **any** of its domains matches by the A4 rule (`ChunkRecord.serves`). The A4 `Passage` is unchanged. There are two backends:
- **`LocalStore`:** numpy in memory, saved atomically to `records.jsonl`, `vectors.npy` and `meta.json`. An index saved before `domains` existed (one `domain` per chunk) still loads.
- **`PgVectorStore`:** Install it with `pip install -e ".[pgvector]"`. It applies the same domain rule in SQL.
  - **Read-only by default:** `search` and `info` work on a read-only view, every transaction is `READ ONLY`, and `replace_source` / `create_schema` raise `ConfigError`.
  - **Writing is opt-in:** `PgVectorStore(dsn, writable=True)` or `SKILLFORGE_PGVECTOR_WRITABLE=1`, for tests and local databases only.
  - **Every search turns on iterative scan** in its own transaction, then re-sorts the rows. See [Search settings](#search-settings-de-02-benchmark).

### Search settings (DE-02 benchmark)
Every `PgVectorStore.search` runs, in one transaction (a `READ ONLY` transaction allows both):

```sql
SET LOCAL hnsw.iterative_scan = relaxed_order;
SET LOCAL hnsw.ef_search = 100;          -- SKILLFORGE_PGVECTOR_EF_SEARCH
SELECT ... FROM knowledge.knowledge_chunks WHERE <domain filter> ORDER BY embedding <=> $v, chunk_id LIMIT $k;
```

- **Why:** AI's search always has a domain filter. Without iterative scan, HNSW keeps only its first `ef_search` candidates and the filter drops most of them, so a search returns fewer than `k` rows, with no error.
- **The re-sort:** `relaxed_order` returns rows only roughly in distance order. The store sorts them again, best score first and ties by `chunk_id`, the same order as `LocalStore`.
- **Needs pgvector 0.8 or later.** DE runs 0.8.6.

What DE's benchmark measured with AI's own query, on random vectors and a 7.7 GB laptop. Their recall figures aren't an indicator for real embeddings, and 500k was mostly disk reads ([data/docs/de-02-benchmark.md](../../../data/docs/de-02-benchmark.md), PR #17):

| 100k chunks, filter | `iterative_scan` off (ef 40) | `relaxed_order`, ef 100 |
|---|---|---|
| broad domain (12% of chunks) | 5.7 of 10 rows, p50 5.9 ms | 10 rows, p50 7.1 ms, p95 10.6 ms |
| rare domain (0.8%) | 0.5 of 10 rows, p50 4.3 ms | 10 rows, p50 26.8 ms, p95 32.2 ms |

- **At 500k** (cold cache), the rare domain with `relaxed_order` took p50 547 ms at ef 100, 3.2 s at ef 40 (p99 27.5 s), and 274 ms at ef 200. A larger `ef_search` made iterative scans faster, which is why the default is 100, not pgvector's 40.
- **`hnsw.max_scan_tuples`** (default 20,000) caps how far an iterative scan goes. DE's runs never reached it.
- **Target:** under 100 ms is met at 100k on DE's laptop, p99 included. 500k and 1M have to be measured again on a server with the index in RAM.

#### Later: an exact GIN path for rare domains (a joint decision with DE)
For a rare domain, reading the matching rows through the GIN index on `domains` and sorting them by exact distance beat HNSW in DE's runs. It returns 10 rows, exactly (recall 1.000): p50 8.0 ms at 100k and 35.3 ms at 500k for the 0.8% domain, against 26.8 ms and 274 to 3,242 ms with iterative scan. It is not built. It needs:
- **A threshold:** DE suggests the number of matching chunks (for example under 20,000) rather than a percentage. The two lines cross at about 3% of the chunks at 100k. AI and DE decide it after DE measures again on the real server.
- **An explicit domain list:** GIN only serves `&&`, not the `LIKE 'x/%'` half of the filter. So the query would take the domain, its parents and all its children as one array, computed from the domain tree.
- **A query that skips HNSW:** `ORDER BY (embedding <=> $v) + 0, chunk_id`, so the planner sorts the GIN matches exactly.
- **A count first,** to choose the path: `SELECT count(*) ... WHERE domains && $list`, or a per-domain count DE keeps.

## For Data Engineering: the knowledge view
DE owns the database. The DE-05 pipeline writes chunks into DE's own tables and exposes **one read-only view** with the columns below. AI reads only that view, as a read-only user (`SELECT` on the view, nothing else).
- **Name:** `knowledge.knowledge_chunks` in production. Set `SKILLFORGE_PGVECTOR_TABLE` to match; names are quoted safely, lowercase only.
- **One row per chunk.** A chunk that serves several domains appears once, with all of them in `domains`.

| Column | Type | Contract |
|---|---|---|
| `chunk_id` | text | **AI-10's `chunk_id`** (`<host>-<url hash>-<text hash>`, from `extract_page`). Stable: the same text on the same page always has the same id (A4) |
| `source_url` | text | The page URL, absolute http(s) |
| `title` | text | The page title from `extract_page`, **never empty** (at most 200 chars) |
| `retrieved` | date | The date the page was fetched |
| `text` | text | The chunk text from `extract_page` (at most 2000 chars) |
| `section`, `concepts` | text[] | From `extract_page` |
| `content_hash` | char(64) | sha256 hex of the chunk text (`Chunk.content_hash`) |
| `domains` | text[] | One or more SkillSpec domains or areas, no repeats, never empty |
| `embedding_model` | text | Exactly `local/BAAI/bge-small-en-v1.5`; the reader refuses a mix of models |
| `embedding` | vector(384) | From `embed(texts, model_role="embedding")`, unit length (AI normalises again on write) |

**Domain matching** (the A4 rule on each element): a row matches query `marketing/email` when `domains && ARRAY['marketing', 'marketing/email']` (equal, or a parent), or when one element is `LIKE 'marketing/email/%'` (a child).

### DDL: an example base table and the view
`pg_schema("knowledge.ai_chunks", 384)` and `pg_view_sql("knowledge.knowledge_chunks", "knowledge.ai_chunks")` give the SQL below. DE's real tables may differ, as long as the view has these columns.

```sql
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

-- Read-only access for AI's code (role name as in DE's db/roles-local.sql):
GRANT USAGE ON SCHEMA knowledge TO skillforge_ai_reader;
GRANT SELECT ON knowledge.knowledge_chunks TO skillforge_ai_reader;
```

### Notes
- **The HNSW index (`vector_cosine_ops`) must be on the base table.** A view cannot be indexed. A query through a plain view still uses the base table's index. That is not true of a view that aggregates (`GROUP BY`, `DISTINCT`, `array_agg` per chunk) or computes `domains` per row from a join, so keep `domains` as a column on the table that holds the embedding, and check the plan with `EXPLAIN`.
- **The GIN index on `domains`** serves the `&&` half of the domain filter.
- **Vectors are unit length,** so cosine distance (`<=>`) ranks the same as inner product. Score = `1 - (embedding <=> query)`.
- **Filtered HNSW:** with a domain filter, HNSW can return fewer than `k` rows. AI's store sets `hnsw.iterative_scan = relaxed_order` with `SET LOCAL` in each search's transaction, which a read-only user may do. It needs pgvector 0.8 or later; see [Search settings](#search-settings-de-02-benchmark).
- **`embedding_version`:** store the pinned model files with each vector (see below), so a model change is visible. AI only reads `embedding_model`.
- **Never run `pg_schema()` against DE's database:** it creates tables and indexes, and AI's user can't. `create_schema` refuses unless the store is writable.
- **Tests:** the opt-in `pytest -m pgvector` (with `SKILLFORGE_PGVECTOR_DSN` for a database where the user may create tables) writes a base table, creates the view, and reads it through a read-only `PgVectorStore`. A second test checks that a rare domain far from the query still returns `k` rows; it first checks that the same query without iterative scan returns fewer.

### The pinned embedding model (for `embedding_version`)
From `core/llm/models.yaml`, role `embedding`:

| Field | Value |
|---|---|
| Model string (`embedding_model`) | `local/BAAI/bge-small-en-v1.5` |
| Dimensions | 384 |
| ONNX repo (Hugging Face) | `Qdrant/bge-small-en-v1.5-onnx-Q` |
| Revision (commit) | `aa8f8b060edb00e03bfdd08813a2949946c8ba55` |
| File | `model_optimized.onnx` |
| sha256 | `51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431` |

A suggested `embedding_version`: `Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b060edb00e03bfdd08813a2949946c8ba55#model_optimized.onnx:sha256=51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`.
