# DE-02 benchmark: similarity search on pgvector (100k and 500k measured, 1M estimated)

Status: measured 4 November 2026 on a development laptop. **Read the three warnings first.**

1. **The vectors are random.** Uniform noise, normalised to length 1, with no structure. HNSW finds neighbours much
   less well in noise than in real embeddings, and every distance is almost the same, so the graph is harder to
   walk. These numbers are **harder than real data**, and the recall figures below are **not an indicator** of
   production quality (recall on real embeddings is much higher). They are only useful to compare settings with each other.
2. **The machine is small:** 7.7 GB of RAM in total, with 0.5 to 0.8 GB free most of the time, and only 3.66 GiB
   for the whole Docker/WSL virtual machine. Above about 200k vectors the data no longer fits in cache here, so the
   500k numbers are mostly **disk reads**, not the index. A real server with enough RAM for the index (about 2 GB per
   million vectors) should be clearly faster. We cannot say by how much from this machine.
3. **The 1M numbers are estimated, not measured.** The 1M data was generated, but the HNSW index could not be
   finished on this machine (section 6). Everything under "1M" is labelled *estimated*.

## 1. What was measured

AI's own search query, through the view `knowledge.knowledge_chunks` (the contract in
[knowledge_views.sql](../db/knowledge_views.sql)):

```sql
SELECT chunk_id, source_url, title, retrieved, text, section, concepts, content_hash, domains,
       1 - (embedding <=> $v) AS score
FROM knowledge.knowledge_chunks
[WHERE (domains && $domain_and_parents::text[]
        OR EXISTS (SELECT 1 FROM unnest(domains) AS d WHERE d LIKE $domain || '/%'))]
ORDER BY embedding <=> $v, chunk_id
LIMIT 10;
```

- 100 queries per case (random unit vectors, always the same 100), after an untimed warm-up pass. Time is
  wall-clock **on the client**, so it includes the round trip to the container. p50, p95 and p99 over the 100 queries.
- recall@10: the overlap of the index result with the exact top 10 (same filter, all indexes switched off), 20 queries.
- Domains in the generated data: `technology/ai` 12% of the chunks (the **broad** filter), `science/biology` 3%,
  `legal/contracts` 0.8% (the **rare** filter). Others between 4% and 23%.
- Scripts: [data/bench/](../bench/) (`create_db.sh`, `generate.sql`, `build_index.sql`, `queries.py`,
  `cache_effect.py`, `run.sh`, `drop_db.sh`). The data is generated inside Postgres with `generate_series`:
  one document per source, 10 chunks per document, about 400 characters of text per chunk.
- Both big tables (`chunks`, `embeddings`) were made `UNLOGGED` in the benchmark database: no WAL, so less disk and
  faster loading. Query speed is the same. The schema is `db/schema-draft.sql` plus `db/knowledge_views.sql`, unchanged,
  except that the HNSW index is created after loading, with the same definition (`m = 16`, `ef_construction = 64`, cosine).

## 2. Machine and settings

| | |
|---|---|
| Computer | Windows 11, **7.7 GB RAM** (0.5 to 0.8 GB free), 12 logical CPUs |
| Docker / WSL | Docker Desktop on WSL2, VM limited to **3.66 GiB** (the default, 50% of RAM). The Docker disk image was moved from `C:` to `E:` for this test (`C:` had under 3 GB free) |
| Software | PostgreSQL 18.6, pgvector 0.8.6, image `pgvector/pgvector:0.8.6-pg18` |
| Benchmark container | separate from the local stack (port 5434; `compose.yaml` and the main container were not changed). `--shm-size=1g`, `--memory=2800m` |
| Postgres settings | `shared_buffers` 512 MB, `maintenance_work_mem` 1 GB, `max_parallel_maintenance_workers` 2, `effective_cache_size` 2 GB, `max_wal_size` 2 GB |
| Not changed | `work_mem` 4 MB. `hnsw.max_scan_tuples` left at the default |

**Parallel index build needs a bigger `/dev/shm`.** With Docker's default 64 MB, `CREATE INDEX` with
`maintenance_work_mem = 512MB` and parallel workers fails with `could not resize shared memory segment ... No space left on device`,
because pgvector keeps the graph in shared memory. Building without workers worked (74.5 s for 100k). With `--shm-size=1g`
the parallel build works (40.3 s for 100k). Staging and production containers need the same `shm_size`.

## 3. Sizes and build times

| | 100k | 500k | 1M |
|---|---|---|---|
| Data load (inside Postgres) | 13 s | 252 s | 275 s |
| Tables without the HNSW index | 0.33 GB | n/a | **3.3 GB** (measured: `embeddings` 2.08 GB with its other indexes, `chunks` 1.13 GB) |
| **HNSW build** (`m=16`, `ef_construction=64`, 2 workers, 1 GB) | **40 s** | **23.7 min** (psql reported 18.2 min for `CREATE INDEX`; the rest of the step was not broken down) | **not finished.** Stopped at 688k of 1M after 94 min (section 6) |
| **HNSW index size** | **195 MB** | **977 MB** | *estimated* ~1.95 GB |
| GIN index on `domains` | 3.8 MB | 5.4 MB | 6.5 MB (measured) |
| Peak container memory seen | 0.65 GiB | 2.6 GiB | 2.7 GiB (while building) |

The index costs about **1.95 KB per vector** (a 384-dimension float vector is 1.5 KB, plus the graph links), the same at
100k and 500k, so 1M is about 1.95 GB. `maintenance_work_mem = 1GB` holds the build graph for only about **482,000** vectors
(Postgres logged `hnsw graph no longer fits into maintenance_work_mem after 482163 tuples`; at 1M the same message came at
482176). After that the build writes to disk and slows down a lot (section 6). 500k just crossed that limit, which is why its
build is much slower per vector than 100k's.

## 4. Query times

Milliseconds, client side, 100 queries per row. `iter` is `hnsw.iterative_scan` (`off` or `relaxed_order`). **rows** is the
average number of rows returned (the query asks for 10).

### 4.1 100k (everything fits in cache)

| filter | ef_search | iter | p50 | p95 | p99 | rows |
|---|---|---|---|---|---|---|
| none | 40 | off | 6.8 | 9.6 | 15.6 | 10 |
| none | 100 | off | 7.7 | 14.3 | 18.2 | 10 |
| broad (12%) | 40 | off | 5.9 | 7.6 | 8.6 | **5.7** |
| broad (12%) | 40 | relaxed_order | 8.6 | 14.0 | 18.5 | 10 |
| broad (12%) | 100 | off | 8.5 | 12.8 | 16.1 | 9.9 |
| broad (12%) | 100 | relaxed_order | 7.1 | 10.6 | 12.0 | 10 |
| rare (0.8%) | 40 | off | 4.3 | 6.0 | 7.1 | **0.5** |
| rare (0.8%) | 40 | relaxed_order | 30.4 | 45.1 | 70.2 | 10 |
| rare (0.8%) | 100 | off | 7.0 | 11.2 | 13.6 | **1.1** |
| rare (0.8%) | 100 | relaxed_order | 26.8 | 32.2 | 32.7 | 10 |
| rare (0.8%) | 200 | off | 9.1 | 11.4 | 12.5 | **2.0** |
| rare (0.8%) | 200 | relaxed_order | 25.5 | 31.3 | 41.1 | 10 |
| **rare, GIN (section 5)** | | | **8.0** | **11.4** | **16.0** | 10 |
| 3% (`science/biology`), GIN | | | 15.5 | 19.4 | 23.7 | 10 |
| broad (12%), GIN | | | 34.8 | 45.0 | 49.2 | 10 |

**Everything is under 100 ms at 100k, including p99.**

### 4.2 500k (does not fit in cache here)

| filter | ef_search | iter | p50 | p95 | p99 | rows |
|---|---|---|---|---|---|---|
| none | 40 | off | 188.8 | 966.4 | 1974.5 | 10 |
| none | 100 | off | 502.0 | 1166.2 | 1338.3 | 10 |
| broad (12%) | 40 | off | 218.2 | 362.0 | 396.6 | **5.7** |
| broad (12%) | 40 | relaxed_order | 467.8 | 1059.8 | 1510.9 | 10 |
| broad (12%) | 100 | off | 511.5 | 1028.7 | 1221.6 | 9.8 |
| broad (12%) | 100 | relaxed_order | 521.6 | 1171.8 | 1730.6 | 10 |
| rare (0.8%) | 40 | off | 184.6 | 371.1 | 416.7 | **0.4** |
| rare (0.8%) | 40 | relaxed_order | **3242.4** | 6599.0 | **27535.7** | 10 |
| rare (0.8%) | 100 | off | 74.9 | 100.2 | 155.2 | **0.9** |
| rare (0.8%) | 100 | relaxed_order | 546.6 | 1204.1 | 1397.5 | 10 |
| rare (0.8%) | 200 | off | 136.7 | 232.1 | 243.0 | **2.0** |
| rare (0.8%) | 200 | relaxed_order | 273.9 | 496.7 | 586.6 | 10 |
| **rare, GIN (section 5)** | | | **35.3** | **72.7** | **107.6** | 10 |
| 3% (`science/biology`), GIN | | | 103.5 | 139.9 | 178.5 | 10 |
| broad (12%), GIN | | | 281.8 | 447.5 | 549.5 | 10 |

These are **not** the speed of the index. The 500k index is 977 MB and the table behind it another 977 MB, against 512 MB of
`shared_buffers` and a cache of about 2 GB, so most pages come from disk. `cache_effect.py` runs the same 100 queries twice in a row:

| case (500k) | first pass p50 / p95 | second pass (same queries, pages cached) p50 / p95 |
|---|---|---|
| HNSW, no filter, ef 40 | 415.5 / 957.7 | **29.9 / 164.2** |
| HNSW, rare, ef 100, relaxed_order | 465.6 / 1335.7 | 181.1 / 340.8 |
| GIN, rare | 41.5 / 72.2 | 24.8 / 32.7 |

The cases in the tables above ran one after the other on the same 100 queries, so the later cases partly profit from
pages cached by the earlier ones. **Do not compare two rows of one table closely** (for example, the run without the
`chunk_id` tie-break was 19.7 ms at 500k, but it ran late, on cached pages). The EXPLAIN shows the tie-break itself costs
nothing: an incremental sort of 35 kB.

### 4.3 What the settings do

- **Without `hnsw.iterative_scan`, a filtered search returns fewer than 10 rows.** HNSW returns its first `ef_search`
  candidates and the filter removes most of them: 5.7 of 10 rows for the broad filter at ef 40, 0.4 to 0.5 for the rare one; raising
  `ef_search` to 200 still gives only 2 rows. It is also fast only because it returns almost nothing.
- **`relaxed_order` gives the 10 rows** but, for a rare filter, scans a lot: 30 ms at 100k, and 3.2 s (p99 27 s) at 500k with
  `ef_search` 40. A larger `ef_search` makes each step of the iterative scan bigger and helped here: 3242 ms (ef 40), 547 ms (100),
  274 ms (200) at 500k.
- `relaxed_order` returns rows that are close to, but not strictly in, distance order. `strict_order` exists and was not measured.

## 5. Rare domains: GIN first (instead of HNSW with iterative scan)

For a rare domain, skip HNSW: read the matching rows through the GIN index on `embeddings.domains` and sort them by exact
distance. The query is AI's, with two changes, in a test form:

```sql
SELECT ... FROM knowledge.knowledge_chunks
WHERE domains && ARRAY['legal', 'legal/contracts']::text[]            -- the part GIN can serve
ORDER BY (embedding <=> $v) + 0, chunk_id                               -- "+ 0": the planner cannot use the HNSW index
LIMIT 10;
```

| share of the chunks | 100k (930 to 14,800 matching chunks) | 500k (about 4,700 to 74,000 matching chunks) |
|---|---|---|
| rare, 0.8% | **8.0 ms** p50, 16.0 p99 | **35.3 ms** p50, 107.6 p99 (24.8 / 32.7 warm) |
| 3% | 15.5 ms | 103.5 ms |
| 12% | 34.8 ms | 281.8 ms |

- The result is **exact**: recall@10 = 1.000 in all three cases, and it always returns 10 rows.
- EXPLAIN confirms it: `Bitmap Index Scan on embeddings_domains_gin_idx`, no HNSW. The cost grows with the **number of
  matching chunks**, about 2 ms per 1,000 matches at 100k and about 4 ms per 1,000 at 500k (cold cache here).
- For the rare filter it beats HNSW with iterative scan at both sizes: 8 vs 25 to 30 ms at 100k, 35 vs 274 to 3242 ms at 500k.
- At 100k, HNSW with `relaxed_order` is faster for the broad filter (7 to 9 ms against 35 ms). The cost lines of the two methods
  cross at about **3% of the chunks** at 100k (estimate, interpolated between the cases we measured). At 500k on this
  machine GIN was ahead even for 12%, but only because HNSW was reading from disk; on a server with the index in RAM
  the crossing point will be higher. It has to be measured again there.
- **Limit:** only the `domains && parents` half of AI's filter can use a GIN index. The other half, `LIKE 'x/%'` (the children of
  the domain), cannot. See the recommendation.

## 6. 1M: what was done, and what is estimated

**Measured at 1M:** the load (275 s), the table sizes (3.3 GB without the HNSW index), the GIN size (6.5 MB), and the start of the build.

**The HNSW build did not finish.** It ran 94 minutes (14:34 to 16:08) and stopped at 688,000 of 1,000,000 vectors, by
agreement: the plan was to stop below 900,000. The graph left `maintenance_work_mem` at 482,176 vectors, and from there the
speed fell from about 130 vectors per second to about 23 per second (635,000 to 688,000 took 39 minutes). The partial index was cancelled and removed.
So there are **no query timings at 1M**, and no recall.

**Estimated, not measured.** Method:

| Estimate for 1M | Value | How it was estimated |
|---|---|---|
| HNSW index size | ~**1.95 GB** | 1.95 KB per vector, equal at 100k (195 MB) and 500k (977 MB), times 1M |
| Total database | ~**5.3 GB** | 3.3 GB measured + the index |
| RAM to keep the index cached | ~2 GB for the index, plus `shared_buffers` and the OS | the index must be cached or latency is dominated by disk reads (section 4.2) |
| Build time with `maintenance_work_mem` 1 GB | **more than 5 hours** on this machine | 688k reached after 94 min, then about 23 vectors per second for the remaining 312k, about 3.8 more hours |
| `maintenance_work_mem` to build in memory | ~**2.1 GB** | 482k vectors fit in 1 GB. With 2.1 GB the parallel build also needs a `shm_size` of at least that size. We did not try it, because this machine cannot give it |
| Query p50, HNSW, no filter, index fully cached | **roughly 45 to 90 ms** | the warm pass at 500k was 29.9 ms (p95 164); the 100k run (7 ms) to 500k (30 ms) grew about 4x for 5x the data; taking 1.5x to 3x more for 2x the data |
| Query p50, rare domain, GIN, cached | **roughly 50 to 80 ms** | warm 500k was 24.8 ms for 4,600 matches; matches double at 1M, and the cost grows with the number of matches |
| Query p50, rare domain, HNSW with `relaxed_order` | **unknown, probably over 100 ms** | 500k warm was 181 ms (p95 341) and cold 466 ms; it gets worse as the filter gets rarer, so we do not estimate it |
| Under 100 ms at 1M | **possible only with the index in RAM, and not demonstrated** | at 500k on this machine, with a cold cache, it was not met (p50 190 to 520 ms for unfiltered and broad queries) |

The honest conclusion for DE-02: the target (under 100 ms) is met at 100k on this machine, p99 included, in every case
that returns 10 rows. At 500k it is not met on this machine with a cold cache; with a warm cache the unfiltered p50 is 30 ms
but p95 is still 164 ms. At 1M nothing was measured: it has to be **re-measured on a server with at least 4 GB of free RAM
for the database** before anyone relies on it.

## 7. Recall (random vectors: not an indicator)

recall@10 against the exact search, 20 queries. Low numbers are expected on random data and say nothing about real data.

| filter | ef_search | iter | 100k | 500k |
|---|---|---|---|---|
| none | 40 | off | 0.050 | 0.005 |
| none | 100 | off | 0.105 | 0.030 |
| broad (12%) | 40 | off | 0.020 | 0.010 |
| broad (12%) | 40 | relaxed_order | 0.065 | 0.020 |
| broad (12%) | 100 | off / relaxed_order | 0.075 / 0.075 | 0.025 / 0.025 |
| rare (0.8%) | 40 | off / relaxed_order | 0.040 / 0.375 | 0.010 / 0.095 |
| rare (0.8%) | 100 | off / relaxed_order | 0.080 / 0.400 | 0.015 / 0.095 |
| rare (0.8%) | 200 | off / relaxed_order | 0.135 / 0.400 | 0.025 / 0.125 |
| GIN (rare, 3%, 12%) | | | **1.000** | **1.000** |

What it does show: more `ef_search` and `relaxed_order` help, and the exact GIN path is exact. The size of the numbers
does not transfer to real embeddings.

## 8. EXPLAIN (ANALYZE, BUFFERS)

The view is a join of five tables; the HNSW index is used through the view and the other tables are read by primary key for the
10 rows. Plans shortened to the important nodes. The 384 floats of the query vector are not shown.

**100k, fastest (no filter, ef 40): 2.3 ms**
```
Limit  (actual time=2.225..2.229 rows=10)   Buffers: shared hit=1781
  -> Incremental Sort  (Sort Key: embedding <=> v, chunk_id; Presorted Key: embedding <=> v; Peak Memory: 35kB)
     -> Nested Loop ...
        -> Index Scan using embeddings_hnsw_cosine_idx on embeddings e   (actual time=1.908..1.926 rows=11)
             Order By: (embedding <=> v)                                  Buffers: shared hit=1670
        -> Index Scan using chunks_pkey, documents_pkey, sources_pkey   (11 loops each)
Execution Time: 2.285 ms
```

**100k, slowest (rare filter, ef 40, relaxed_order): 33.6 ms**
```
  -> Index Scan using embeddings_hnsw_cosine_idx on embeddings e   (actual time=1.859..32.789 rows=11)
       Order By: (embedding <=> v)
       Filter: ((domains && '{legal,legal/contracts}') OR EXISTS(SubPlan 1))
       Rows Removed by Filter: 1300                                  Buffers: shared hit=22491
Execution Time: 33.555 ms
```
The filter is applied to the rows coming out of the index (1,300 rows read and thrown away to find 11). The GIN index is not used.

**100k, rare filter through GIN: 7.0 ms**
```
  -> Gather Merge  (Workers Launched: 1)
     -> Sort (Sort Key: (embedding <=> v) + 0)
        -> Parallel Bitmap Heap Scan on embeddings e   (rows=465 per worker)   Heap Blocks: exact=910
           -> Bitmap Index Scan on embeddings_domains_gin_idx   (rows=930)
Execution Time: 6.977 ms
```

**500k, no filter, ef 40, cold: 697.8 ms**
```
  -> Index Scan using embeddings_hnsw_cosine_idx on embeddings e   (actual time=656.162..658.060 rows=11)
       Buffers: shared hit=89 read=1625          <- almost every index page is read from disk
Buffers (whole query): shared hit=147 read=1678
Execution Time: 697.768 ms
```

**500k, slowest (rare filter, ef 40, relaxed_order): 6368.7 ms**
```
  -> Index Scan using embeddings_hnsw_cosine_idx on embeddings e   (actual time=1386.240..6355.400 rows=11)
       Filter: ((domains && '{legal,legal/contracts}') OR EXISTS(SubPlan 1))
       Rows Removed by Filter: 1580              Buffers: shared hit=4150 read=18970
Execution Time: 6368.683 ms
```
19,000 pages read from disk to find 11 matching rows.

**500k, rare filter through GIN, cold: 537.2 ms** (the measured p50 over 100 queries was 35 ms; this is the first query of the run)
```
  -> Gather Merge  (Workers Planned: 2, Launched: 2)
     -> Parallel Bitmap Heap Scan on embeddings e
        -> Bitmap Index Scan on embeddings_domains_gin_idx        Buffers: shared hit=809 read=4007
Execution Time: 537.230 ms
```

## 9. Recommendation for the AI team

1. **Broad domains (large share of the chunks): HNSW with `hnsw.iterative_scan = relaxed_order`.** Set it for the
   session (a read-only user may). On the 12% filter at 100k it is the fastest way (7 to 9 ms) and returns the full 10 rows.
   Use `hnsw.ef_search` 100 or more (iterative scans got faster with a larger value, section 4.3).
2. **Rare domains (about under 5% of the chunks): GIN on `embeddings.domains`, with an exact sort.** Same result as the search
   in section 5: exact (recall 1.0), 10 rows, 8 ms at 100k and 35 ms at 500k for 0.8%, against 30 ms and 3.2 s (p99 27 s) for
   HNSW with iterative scan.
3. **Never use a filter without `hnsw.iterative_scan`.** Without it the filtered search returns **fewer than 10 rows** (5.7 for
   the broad filter at ef 40, 0.4 for the rare one at 500k). The caller gets a short answer and no error.
4. **The threshold has to be decided by AI and DE.** The measurements put the crossing at about 3% at 100k (section 5);
   5% is a starting value, not a measurement. Because the GIN cost follows the number of matching chunks (about 2 to 4
   ms per 1,000), a rule on a **count** is better than one on a percentage: use GIN when the filter matches fewer than a
   fixed number of chunks (for example 20,000), HNSW otherwise. The count is cheap to get with the same GIN index
   (`SELECT count(*) FROM knowledge.embeddings WHERE domains && $parents`), or DE can keep a small table of chunks per domain.
   **Re-measure the threshold on the real server.**
5. **Children (`LIKE 'x/%'`) need a list.** A GIN index only serves `&&`. AI's filter also matches children of the
   domain with `LIKE`, which GIN cannot use, and which also makes the planner scan the whole table for the filter. For the GIN
   path the caller has to turn the domain into an explicit list *before* the query: the domain, its parents and all its children
   (`ARRAY['marketing', 'marketing/email', 'marketing/email/newsletters', ...]`). The domain tree is known (SkillSpec), so the list
   can be computed once and cached. Our measurements used a rare domain with no children, so they do not include this.
6. **Remember what these numbers are:** random vectors, harder than real; a 7.7 GB machine, so 500k and 1M are limited by disk reads;
   recall is no indicator. Re-run `bench/run.sh` with real embeddings (or at least clustered ones) on a server with enough RAM.

## 10. To do for DE

- Decide the `shm_size` and `maintenance_work_mem` for staging and production (OPS): the parallel HNSW build needs
  `shm_size` at least as big as `maintenance_work_mem`; to build 1M in memory, about 2.1 GB of each.
- Measure 1M on a server with enough RAM, with the same scripts.
- Provide the matching-chunk count per domain (query or table) for the threshold in recommendation 4.
- The `hnsw.max_scan_tuples` limit (pgvector default 20,000) caps an iterative scan; it was not reached in our runs and was not tested.
