# DE-15: capacity plan for the first 6 months

Status: draft of 17 November 2026, for review with DevOps ("Done when": reviewed with DevOps). Written for DevOps and the owner.
The numbers come from `bench/capacity_model.py` (pure arithmetic: change a constant, run it, copy the table). Every input is marked
**measured** (from `de-02-benchmark.md`, a development laptop with 7.7 GB RAM) or **assumption** (my guess; replace it when AI or DevOps answers).
Nothing here was measured above 500,000 chunks: the 1M index could not be built on that machine. The "large" scenario is therefore an
**extrapolation**, not a result.

## 1. Inputs

| Input | Value | Source |
|---|---|---|
| Tables per chunk (`chunks` + `embeddings` + their ordinary indexes) | 3.3 KB (3.3 GB per 1M) | **measured** (benchmark, 1M rows; chunk text there is about 400 characters) |
| HNSW index per vector (`m=16`, `ef_construction=64`) | 1.95 KB (195 MB per 100k, 977 MB per 500k) | **measured** at 100k and 500k; the same per-vector size at 1M is **assumption** |
| Vector | 384 floats = 1,536 bytes | contract (`vector(384)`), included in the 3.3 KB |
| Extra text of a real chunk | +0.7 KB | **assumption**: a real chunk is about 180 words (AI's default `target_words`), about 700 characters more than the benchmark's |
| Raw HTML per page | 100 KB | **assumption** (no real crawl has been measured) |
| Clean text per page | 20 KB | **assumption** |
| Chunks per page | 10 | **assumption** (the benchmark used 10; AI should give the real number) |
| Share of pages that change per month | 10% | **assumption** |
| Raw page retention | 30 days | agreed (`object-storage.md`) |
| Refresh window of a web page | 30 days (90 for SKILL.md and repo files) | `freshness.py` (**assumption** in the docs, agreed 30 days) |
| Superseded documents kept | 90 days | retention table (agreed with AI); not enforced yet |
| Per-host pause between requests | 1 second (`FetchConfig.min_interval`), more if robots.txt says | code |
| Local embedding speed | 30 chunks per second per worker | **assumption**: not measured; AI's model is `bge-small-en-v1.5` quantised ONNX on CPU |
| Dump size / table size | 0.5 | **assumption** (compressed `pg_dump`; indexes are not dumped) |
| Growth | linear over 6 months | **assumption** |

## 2. The formulas

```
chunks            = pages × chunks_per_page
tables_bytes      = chunks × (3.3 KB + 0.7 KB)
hnsw_bytes        = chunks × 1.95 KB
database_bytes    = tables_bytes + hnsw_bytes + superseded_rows          (superseded_rows = changed_pages_per_month × 3 × 2 KB, small)
ram_for_search    ≈ hnsw_bytes + 0.5 GB          (the index must be cached or queries are dominated by disk reads: benchmark section 4.2)
raw_bytes         = (new_pages_per_month + changed_pages_per_month) × raw_page_bytes      (30-day retention)
clean_bytes       = pages × clean_page_bytes     (one current clean text per page; the old one is deleted when replaced)
requests_per_day  = (pages + new_pages_per_month) / 30
download_per_month= (pages + new_pages_per_month) × raw_page_bytes          (no 304 savings counted: the upper bound)
embedding_hours   = chunks_to_embed / 30 / 3600          (first load: all chunks; later: new + changed pages × chunks_per_page)
dump_bytes        = tables_bytes × 0.5
```

## 3. Three scenarios at the end of month 6 (all sizes are GB unless said otherwise)

The page counts are **assumptions**: the project has no traffic forecast yet. "Pages" means current sources.

| | small | medium | large |
|---|---|---|---|
| pages | 5,000 | 50,000 | 500,000 |
| chunks | 50,000 | 500,000 | 5,000,000 |
| tables | 0.2 | 2.0 | 19.8 |
| HNSW index | 0.1 | 0.9 | 9.3 |
| **database total** | **0.3** | **2.9** | **29.4** |
| RAM to keep the index cached | 0.6 | 1.4 | 9.8 |
| raw pages (30 days) | 0.1 | 1.3 | 12.7 |
| clean text | 0.1 | 1.0 | 9.5 |
| **object storage total** | **0.2** | **2.2** | **22.3** |
| requests per day | 194 | 1,944 | 19,444 |
| download per month | 0.6 | 5.6 | 55.6 |
| embedding, first load (hours, one worker) | 0.5 | 4.6 | 46.3 |
| embedding, each month (hours) | 0.1 | 1.2 | 12.3 |
| compressed dump | 0.1 | 1.0 | 9.9 |

How to read it:
- **Small and medium fit on one ordinary database server.** Medium's index (about 0.9 GB) fits in 2 GB of RAM: the measured 500k case.
- **Large is beyond anything measured.** 5M chunks means about 9 GB of index that must stay in RAM, a build that takes many hours (the 1M build was estimated at **more than 5 hours** with 1 GB `maintenance_work_mem`; it needs about 2.1 GB per million vectors to build in memory), and a restore that rebuilds it. Before choosing "large", measure 1M on a machine with enough RAM (the DE-02 test was never finished) and decide on partitioning or a smaller vector type. I did not design that here.
- **Crawl load is small in every scenario.** Even large is about 19,000 requests a day (one every 4.4 seconds on average); the per-host pause only matters if many pages sit on few hosts: 1,944 pages from one host take about 32 minutes at one request per second.
- **Embedding is the slowest step at scale** (about 2 days for the first large load on one worker, at the assumed speed). Speed is an assumption; it is the number to measure first.
- **Query time:** the benchmark gave p50 about 30 ms warm at 500k and an **estimate** of 45 to 90 ms at 1M with the index fully cached (not demonstrated). The target "under 100 ms at 1M" (DE-02) is **not shown** yet.

## 4. What is sensitive (change one input, the result moves most)

1. **Chunks per page**: every table, the index, the embedding time and the RAM scale with it. Ask AI.
2. **Pages**: the product decides. Ask the owner or the product side for a first-6-months forecast.
3. **Raw page size**: only the object storage and the download change; a 300 KB average triples raw storage and download.
4. **Embedding speed**: decides how long a re-embedding takes when AI changes the model or the chunk config (every chunk of the old config is rebuilt; old rows stay 30 days).

## 5. Rebuilds cost extra space and time

A new chunk config or embedding version creates a second full set of chunks and embeddings next to the old one, which is kept 30 days after `active_config` switches
(retention table). **Plan for up to 2× the database size during a rebuild** (assumption: both sets complete at once), and the index build time of section 3.

## 6. Needed from AI

1. How many pages and how many chunks per skill (and per domain), on average and at most. This turns the page count into a forecast.
2. The real number of chunks per page and the real chunk size (measured on real pages with `extract_page`), not 10 and 180 words.
3. The speed of `embed_sync` on the target machine (chunks per second, one worker, CPU), and whether a GPU or a hosted embedding is planned.
4. How often they expect to change the embedding model or the chunk config (each change is a full rebuild).
5. How many skills are generated per day (retrieval query load); the benchmark ran single queries, not concurrent ones.

## 7. Needed from DevOps

1. **Budget and limits:** database server size (RAM and disk), object storage quota and cost, backup storage, and who pays for a rebuild.
2. Which server will hold the vectors, and whether the benchmark of 1M can be run on it (the DE-02 target was never measured at 1M).
3. Object storage in production (MinIO or S3), its lifecycle rules (the 35-day safety rule for `raw/`), and its request limits.
4. Backup and restore constraints (OPS-12): window, retention, target. A restore rebuilds the HNSW index (see `backup-restore.md`).
5. Egress: whether crawl traffic goes through the scraping network (OPS-09), and any bandwidth limit.
6. Redis: not used in these numbers.

## 8. Needed from Backend / the owner

A forecast of crawled domains and pages for the first 6 months, and the agreed retention numbers marked PROPOSED in `data-architecture.md` (they change the object storage and superseded-document numbers).

## 9. What is not in the numbers

WAL and replication overhead, table bloat, `pg_dump` of object storage, logs (90 days), Redis, the packages bucket (Backend's), the analytics tables (DE-12), the evaluation datasets (DE-10), and MLflow (DE-16).
