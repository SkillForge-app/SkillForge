# P1 plan: DE-04 crawler, DE-05 pipeline, DE-06 provenance

Status: plan, 5 November 2026. Written from [de-task-plan.pdf](de-task-plan.pdf), [project-spec.pdf](project-spec.pdf),
[data-architecture.md](data-architecture.md), [object-storage.md](object-storage.md) and
[de-02-benchmark.md](de-02-benchmark.md). No code is described here that is not already decided in those files; where a file
was silent, the assumption is marked **Assumption**.

Warning that applies to everything below: **chunks stored before 4 November 2026 are not final** (the `extract_fingerprint` and
`normalise_url` changes alter `chunk_id`), and they will be deleted and rebuilt.

## 1. Order and dependencies

DE-05 needs DE-04 in the task plan ("Needs: DE-04"), and DE-06 needs DE-05. They are built in the order of the work list, with the
storage code (DE-03) built as part of P1 because DE-05 needs somewhere to put raw and clean text:

1. DE-05 core (storage layer of the pipeline), against fakes of AI's functions.
2. DE-04 crawler (produces the raw page that DE-05 consumes).
3. DE-03 storage code (interface, in-memory, S3, daily job).
4. DE-06 provenance (check that DE-05 stores what the view needs).

## 2. DE-04: crawler

**Acceptance criteria** (task plan, spec section 5, architecture doc):

- "Disallowed URLs are never fetched (tested)": the page itself is never requested when `robots.txt` forbids it.
- httpx fetcher; Playwright fetcher for pages that need JavaScript.
- `robots.txt` and terms checks; per-domain (per-host) rate limits; an identified user agent; retries.
- Responsible scraping (spec): respect `robots.txt` and terms, rate-limit every domain, store only what is needed, keep the URL and
  the retrieval date of every source.
- Records (architecture doc): `sources.robots_allowed`, `robots_checked_at`; `crawl_runs.user_agent`, `config`, `pages_fetched`,
  `pages_unchanged`, `pages_blocked`, `pages_failed`, `error`.
- Fetch the original URL, store `normalise_url(original)` in `sources.url` (AI's extraction doc).
- Size limit per object 20 MB (object-storage doc, proposed).
- Licence of each source stored in `sources.license` / `license_source` (needed by DE-08).

**Files** (`data/skillforge_data/crawler/`): `robots.py` (fetch, parse, cache, crawl-delay), `ratelimit.py` (per-host minimum
interval, injectable clock), `fetcher.py` (httpx fetch with redirects, timeout, size cap, retries, conditional GET),
`license.py` (licence detection), `run.py` (a crawl run: `crawl_runs` row, per-URL loop, counters, errors).
Tests: `tests/test_crawler.py` with a local HTTP server.

**Built now:** everything above except Playwright and persistent conditional-GET validators.

**TODO / not now:**

- Playwright fetcher (`PlaywrightFetcher`): needs a browser download, heavy for this machine. The `PageFetcher` interface is defined so it
  can be added without touching the rest.
- Persisting `ETag` / `Last-Modified`: there are no columns for them. Proposal: `docs/proposals/de-04-conditional-get.md`. Until then
  an in-memory store is used.
- "Terms checks": terms of service cannot be parsed by machine. **Assumption:** `robots.txt` is the automatic check, plus a host
  deny-list in the run config; reading the terms of a new source is a manual review recorded as a decision, not code.
- Source discovery (finding URLs) is AI's (`crawl_list()`); the crawler is given URLs.

**Dependencies on AI:** `normalise_url()` (interface `NormaliseUrl`). Nothing else.

## 3. DE-05: processing pipeline

**Acceptance criteria:**

- Raw -> clean -> chunk -> embed; **idempotent, versioned**; "Re-running a job gives the same output".
- Chunking and embedding settings are configurable so AI can tune them (AI-10, AI-11).
- `chunk_id` is AI's id; a repeated `chunk_id` on one page keeps the first one (architecture doc).
- A page without a usable title is a pipeline failure, not an empty string.
- A rejected page (`quality_ok = false`, for example `injection`) keeps its verdict and `screening`, has no chunks, and is not shown.
- A, B, A: the returning version is processed again (its chunks were deleted when B replaced it).
- Retention: old chunks and embeddings are deleted when the new version replaces them, **but only after the new version is
  processed and stored successfully, in the same transaction**, together with `clean_deleted_at` (agreed with AI and Backend).
- If processing fails, the old content stays as it was, and the failure is recorded.
- Embeddings: `local/BAAI/bge-small-en-v1.5`, 384 dimensions, unit length; `embedding_version` is the pinned revision; `domains`
  copied from the source's domains.

**Files** (`data/skillforge_data/`): `interfaces.py` (`ExtractPage`, `Embed`, `NormaliseUrl` and the data shapes they return),
`pipeline/config.py` (`PipelineConfig`, `chunk_config_hash`), `pipeline/process.py` (`process_document`),
`store.py` (sources, source_domains, crawl_runs helpers). Tests: `tests/test_pipeline.py` on a real Postgres with fakes of AI's functions.

**Built now:** `process_document` for one page, end to end, with fakes; the safe-order decision for the open point; failure recording.

**TODO / not now:**

- Real adapters from AI's `extract_page`, `embed`, `normalise_url` to the interfaces (AI's code is not copied or imported; the
  adapter is a thin wrapper added when AI's package is installable).
- `extract_fingerprint` stays optional until AI finishes it, then becomes required in the CHECK (schema change, DE-05 TODO).
- Per-host `site_boilerplate` (`find_site_boilerplate`) and the `ExtractConfig` per host: belongs in the adapter.
- The rebuild job that switches `active_config` when a new chunk set is ready; the 30-day cleanup of inactive configs.
- Dedup and language detection (DE-07), the near-duplicate marking.
- Scheduling and batching of many pages (DE-14); this task is one document.
- Optional schema improvement (a `p_document_id` parameter for `record_document_version`): `docs/proposals/de-05-record-version.md`.

**Dependencies on AI:** `extract_page()` (clean text, `title`, `quality`, `screening`, `chunks` with `chunk_id`), `embed()` (batch,
384-d unit vectors), `normalise_url()`, `ExtractConfig.fingerprint()`. **Dependency on DevOps:** none for now.

## 4. DE-03 storage code (needed by DE-05)

**Acceptance criteria** (object-storage.md): keys for raw and clean; write order = upload first, then the database; delete order =
database first, then the object; "a row never points to a missing object"; raw deleted by a daily job 30 days after the **first**
upload (a re-fetch does not extend it), with a 35-day bucket rule only as a safety net; orphan sweep (24 h).

**Files** (`data/skillforge_data/storage/`): `base.py` (interface), `memory.py` (tests), `s3.py` (boto3, no network tests),
`keys.py`, `jobs.py` (daily raw expiry, reconcile, orphan sweep). Tests: `tests/test_storage.py`.

**TODO / not now:** MinIO in `compose.yaml` (DevOps); credentials and buckets (OPS); the `packages` bucket is DevOps and Backend's;
a real S3 test belongs in staging.

## 5. DE-06: provenance

**Acceptance criteria:** "Every chunk traceable to its source": URL, retrieval date, licence and content hash stored with every
chunk (task plan); `chunk_provenance` gives chunk -> `url`, `host`, `retrieved_at`, `license`, chunk and document hashes
(architecture doc).

**Files:** `data/skillforge_data/provenance.py` (a check that lists chunks that cannot be traced), `tests/test_provenance.py`.
Comparing the view with what is asked for may need a change to the view, which is **not** made here: a proposal goes to
`docs/proposals/de-06-provenance.md`.

## 6. What is built now and what is not

| Task | Built now | Not now |
|---|---|---|
| DE-05 | `process_document`, config, fakes, tests | real AI adapters, rebuild job, DE-07 |
| DE-04 | robots, rate limit, fetch, retries, conditional GET (memory), licence, crawl runs, tests | Playwright, persistent validators |
| DE-03 | interface, memory + S3 implementations, key layout, daily jobs, tests | MinIO, real buckets |
| DE-06 | traceability check, tests, view gap proposal | changing the view |

Rules for all of it: only files under `data/`; no schema or view change (proposals instead); no copies of AI's code; no network in
tests (a local HTTP server where needed); a new library only if it is in `pyproject.toml` and named in the progress file.
