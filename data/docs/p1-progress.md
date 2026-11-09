# P1 progress: DE-05, DE-04, DE-03 (code), DE-06

Status: 5 November 2026. Everything is in the working tree under `data/`. **Nothing was committed, staged or pushed.** Nothing outside
`data/` was touched. `db/schema-draft.sql`, `db/knowledge_views.sql`, `compose.yaml`, `.github/` and `devops/` are unchanged
(`git diff` on them is empty). The plan is [p1-plan.md](p1-plan.md).

## Result

| Check | Result |
|---|---|
| `ruff check .` (from `data/`) | **All checks passed** |
| `pytest -q -rs` | **97 passed, 0 skipped** (12 before; ran in ~30 s on the local Postgres) |
| Run after each task | after the pipeline 31 passed, after the crawler 73, after storage 90, after provenance 97 |

Mutation check on the most important rule: deleting the old chunks *before* the new version is stored makes 3 pipeline tests fail
(`replaces the old chunks`, `database error after the flip rolls everything back`, `new fingerprint beside the old one`); the code was
restored and the suite is green again.

## Task 1: the plan: done

[p1-plan.md](p1-plan.md): acceptance criteria for DE-04, DE-05, DE-06 (and the DE-03 code they need), files, dependencies on AI, what is built
now and what is TODO. Read: the task plan, the spec, `data-architecture.md`, `de-02-benchmark.md`, `object-storage.md`.

## Task 2: DE-05 pipeline core: done

Files: `skillforge_data/interfaces.py` (the AI interfaces `ExtractPage`, `Embed`, `NormaliseUrl` and the data shapes),
`skillforge_data/pipeline/config.py` (`PipelineConfig`, `chunk_config_hash`), `skillforge_data/pipeline/process.py` (`process_document`),
`skillforge_data/store.py` (sources, domains, crawl runs), `skillforge_data/storage/{base,keys,memory}.py` (interface used by the pipeline),
`tests/conftest.py`, `tests/fakes.py`, `tests/test_pipeline.py` (19 tests), `docs/proposals/de-05-record-version.md`.
Changed: `tests/test_document_versions.py` (fixtures moved to `conftest.py`, no test changed), `pyproject.toml`, `docs/data-architecture.md`
(one sentence: the open point is decided).

What it does: normalise URL -> source -> (unchanged? stop) -> upload raw -> extract -> drop repeated `chunk_id` -> embed and check the vectors ->
**one transaction** (`record_document_version`, verdict, chunks and embeddings, delete the older versions' chunks, `clean_deleted_at`) ->
after the commit: delete old clean objects, store the new clean text. Tested on a real Postgres with fakes: idempotency (second run
changes nothing, no second extraction, embedding or upload), deletion only after success and in the same transaction, a failure inside the
transaction rolls the new version back (old one still current and visible), a failure before it leaves the old one untouched and counts in
`crawl_runs.pages_failed`, A -> B -> A, a page rejected for `injection` (verdict and `screening` stored, no chunks, old chunks removed, the
same page again is "unchanged"), bad title, repeated `chunk_id`, wrong or non-unit vectors, no domain, a new fingerprint = a new chunk set
beside the old one, licence rule, raw key and metadata, a storage problem after the commit = warning.

Decisions I took:
- **The open point (`record_document_version` flips before processing):** do all work that can fail first, then flip inside the same transaction as the
  chunks. No schema change; reasoning and an optional schema improvement are in `docs/proposals/de-05-record-version.md`.
- **A failed page never raises:** `process_document` returns `status="failed"`, logs the traceback and counts it in `crawl_runs` (when it has a run id).
- **A page without a usable title is a failure** (as `data-architecture.md` says), not a fallback title.
- **Rejected pages get `status = 'cleaned'`** (processed, no chunks, no clean text); accepted pages `'embedded'`.
- **Already processed = the document exists for this content, has chunks for this chunk config (or is a rejected page of the same pipeline
  version).** Then only `fetched_at` and `license` are refreshed. A different chunk config processes it again, beside the old set.
- **`active_config` is created by the first run if missing and never switched** by the pipeline (the rebuild job is TODO). `ProcessResult.active` says
  whether the stored set is the visible one.
- **The clean text is uploaded after the commit** (its key has the document id); the row gets `clean_object_key` only after the object exists.
  The clean key follows the **latest** processed extraction, even when that set is not active yet.
- `chunk_index` = AI's `position` (gaps are possible after repeated chunks are dropped). `chunk_config` carries `extract_fingerprint` only when set.
- The caller should pass an **autocommit** connection (each step is its own transaction block); a connection already inside a transaction works too
  (the blocks become savepoints), which is how the tests run.

## Task 3: DE-04 crawler: done, except Playwright and persistent validators

Files: `skillforge_data/crawler/{robots,ratelimit,fetcher,license,run,__init__}.py`, `tests/test_crawler.py` (42 tests, local HTTP server on 127.0.0.1),
`docs/proposals/de-04-conditional-get.md`.

Covered by tests: a URL forbidden by `robots.txt` is **never requested** (also after a redirect to it), robots cached once per origin, how 200/404/410/401/403/5xx/network
errors are read, our token wins over `*`, `Crawl-delay`, deny-list, per-host spacing, redirects (followed, loop, limit), 20 MB limit by `Content-Length` and while
streaming, retries with backoff for 429/5xx/timeouts, `Retry-After` honoured and capped, 404 not retried, ETag/Last-Modified -> 304, identified User-Agent,
licence detection and SPDX mapping, `crawl_runs` (counters, status, `config`, error text), `sources.robots_allowed`/`robots_checked_at`/`license`, original URL fetched and
canonical URL stored, a full crawl feeding the pipeline and a second crawl changing nothing.

Decisions I took (the documents were silent or unclear):
- **robots.txt:** 404/410 = allowed; 401/403 and 5xx/network error = disallowed (conservative; RFC 9309 would allow on 401/403). The error case is asked again after 10 minutes, otherwise cached 24 h.
- **"Terms" checks** cannot be automatic: a host deny-list in the run config, and a manual review recorded as a decision.
- **Licence rule:** only what the page declares about itself (`rel="license"`, `<meta name="license">`, JSON-LD `license`) mapped to SPDX (Creative Commons, MIT, Apache-2.0, BSD, ISC,
  MPL, GPL...); anything else is `unknown`; nothing is guessed from a footer. Stored with `license_source = 'page'`. Whether it is *permissive* is DE-08's call.
- **Counters:** `pages_fetched` = a 200 body was downloaded; `pages_unchanged` = 304 or the pipeline said "unchanged"; `pages_blocked` = robots/deny-list; `pages_failed` = anything else.
  Status `succeeded` / `partial` / `failed`; an empty run ends `succeeded` with zeros (DE-11 alerts on that).
- **Redirects are checked hop by hop** against robots.txt, and only `http`/`https` are followed. The `Retry-After` pause is capped at 60 s.
- **User-Agent:** `SkillForgeBot/0.1 (+https://github.com/SkillForge-app/SkillForge; knowledge collection for agent skills)`; the robots token is `SkillForgeBot`.
- Default 1 request per second per host, 15 s timeout, 3 retries.

## Task 4: DE-03 storage code: done (no MinIO)

Files: `skillforge_data/storage/{base,keys,memory,s3,jobs}.py`, `tests/test_storage.py` (17 tests).
Interface (`put` never overwrites and reports whether it wrote; `get`, `exists`, `head`, `delete`, `list`), an in-memory implementation with a controllable clock,
the S3 adapter on a **passed-in boto3 client** (tests use a fake client; `S3Storage.from_env()` reads `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, optional `S3_REGION`; nothing touches the network),
raw and clean keys as in `object-storage.md`, write order (upload, then database) in the pipeline, delete order (database, then object) in the daily job.
`run_daily_storage_job` = `expire_raw` (30 days from the **first** upload, two documents sharing one raw key are both cleared) + `reconcile_raw` (clears keys whose object vanished, for
the 35-day bucket rule) + `sweep_orphans` (unreferenced objects older than 24 h; clean text of a live document is kept).
Tested: the 30-day boundary, a re-fetch does not extend it, A -> B -> A does not restart the clock while the raw object exists, a returning page gets a new object and its own 30 days, the database is cleared
before the object is deleted, a failed delete leaves a clean row and an orphan that the sweep removes, orphan age rule.

Decisions: S3 `put` is a `head` then a `put` (portable; one key = one content). Sweeps load key lists in memory (fine at today's size; revisit with the capacity plan, DE-15).

## Task 5: DE-06 provenance: done; view change only proposed

Files: `skillforge_data/provenance.py` (`get_provenance`, `check_provenance`), `tests/test_provenance.py` (7 tests), `docs/proposals/de-06-provenance.md`.
Finding: `chunk_provenance` covers URL, host, retrieval date, licence and both hashes (the task plan's four items). It does **not** carry the crawl run, the page title, the
pipeline version or the chunk config. The pipeline stores all of them; `get_provenance` joins `documents` for the run and the title. The view change (four appended columns) is a
proposal only, because the view is the DE-AI contract. `check_provenance` also verifies `chunks.content_hash` = sha256 of the text, and raw objects against `documents.content_hash`.

## New library and configuration

- **`boto3>=1.34`** added to `pyproject.toml` dependencies (used only by `S3Storage.from_env()`, imported lazily). **It is not installed in my local `.venv`** (no network use was needed
  for the tests); CI installs it with `pip install -e ".[dev]"`.
- `pyproject.toml`: packages are now found (`skillforge_data*`) and pytest gets `pythonpath = ["."]`.
- `tests/conftest.py`: the throwaway database is now created once per session with the schema loaded, and each test runs in a rolled-back transaction. The default test URL uses `127.0.0.1` instead
  of `localhost`: with `localhost` every connection waited 3 s on IPv6 first, which made the old suite take ~40 s and the new one several minutes. `DATABASE_URL` still overrides it (CI).

## TODOs and dependencies (also in the plan and proposals)

AI: adapters from AI's `extract_page`, `embed`, `normalise_url` to our interfaces (needs AI's package to be installable); `ExtractConfig.fingerprint()` final, then `extract_fingerprint`
becomes required in the CHECK; per-host `site_boilerplate`; confirmation of the licence rule and of `license_source`.
DevOps: MinIO and the buckets in `compose.yaml`; `shm_size` and `maintenance_work_mem` for the HNSW build (benchmark doc); credentials for S3.
Backend/DevOps: `packages` bucket (DevOps) and "currently in use" for its retention.
DE: Playwright fetcher; DB-backed validators (needs `docs/proposals/de-04-conditional-get.md`); rebuild job that switches `active_config` and deletes other extraction versions;
`p_document_id` in `record_document_version` (optional proposal); concurrent workers on one source are not tested; metrics beyond logs and `crawl_runs` (DE-11);
scheduling and batching (DE-14); dedup and language detection (DE-07); the licence for repo files (DE-08). Chunks stored before 4 November 2026 are not final and will be deleted.

## Things worth a look when you review

1. `process_document` catches every exception on purpose (a bad page must not stop a crawl). The failure is logged with its traceback and counted; check you are happy with that.
2. The crawler stamps `fetched_at` with the time of processing, not a server date.
3. A raw upload happens before extraction, so a page that fails to extract leaves an orphan raw object (the sweep removes it after 24 h).
4. `data/docs/data-architecture.md` has one changed sentence (the open point is decided); everything else you will see in it is from earlier commits.

## Suggested commits (one per task; the order keeps every step green)

1. `DE-05: processing pipeline core (process_document), AI interfaces, tests`
   `data/skillforge_data/{__init__,interfaces,store}.py`, `data/skillforge_data/pipeline/`, `data/skillforge_data/storage/{__init__,base,keys,memory}.py`,
   `data/tests/{conftest,fakes,test_pipeline,test_document_versions}.py`, `data/pyproject.toml`, `data/docs/proposals/de-05-record-version.md`, `data/docs/data-architecture.md`,
   `data/docs/p1-plan.md`, `data/docs/p1-progress.md`.
2. `DE-04: crawler (robots.txt, rate limits, retries, conditional GET, licence, crawl runs)`
   `data/skillforge_data/crawler/`, `data/tests/test_crawler.py`, `data/docs/proposals/de-04-conditional-get.md`.
3. `DE-03: storage code (S3 adapter, in-memory storage, daily raw expiry and orphan sweep)`
   `data/skillforge_data/storage/{s3,jobs}.py`, `data/tests/test_storage.py`.
4. `DE-06: provenance check and traceability tests; proposal for the view`
   `data/skillforge_data/provenance.py`, `data/tests/test_provenance.py`, `data/docs/proposals/de-06-provenance.md`.

(`pyproject.toml` holds both the packaging change and the `boto3` line; it goes in commit 1.)
