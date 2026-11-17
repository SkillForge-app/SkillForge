# P4 progress: sync with main, the real AI adapter

## من فين يبدأ المراجع (where a reviewer starts)

The PR is big: about 40 files, 3,000 added lines, 24 commits (2 of 3 are tests and docs). Do not read it in commit order. This order
goes from the contracts to the code that uses them. Estimated time for a careful read: 2 to 3 hours.

### 1. Read these first (the contracts: they are the reason for a review by AI and Backend)

1. `db/schema-draft.sql`: `is_valid_chunk_config()` now needs **exactly five keys** (`extract_fingerprint` is required, 64 hex).
2. `db/knowledge_views.sql`: **four columns added at the end of `chunk_provenance`** (`crawl_run_id`, `page_title`, `pipeline_version`,
   `chunk_config_hash`). Existing columns keep name and order. The other views are unchanged.
3. `docs/data-architecture.md`, sections "`active_config`" and the migration note for old chunks.
4. `docs/proposals/` (de-04, de-05, de-09): **proposals only, nothing is applied**. They need Backend's answer; no code depends on them.

### 2. Then the code, in this order

5. `skillforge_data/interfaces.py` (the small types between us and AI) and `pipeline/config.py` (`chunk_config` from `ExtractConfig`).
6. `skillforge_data/adapters/ai.py`: the only place that imports AI's code, lazily. `pyproject.toml`: extra `ai`, marker `ai_real`, no `uv.lock`.
7. `skillforge_data/pipeline/process.py` (small diff), `provenance.py` (reads the 4 new columns).
8. `skillforge_data/crawler/fetcher.py`, `robots.py`, `run.py`: robots redirects, Retry-After, the licence, validators.
9. `skillforge_data/licensing.py` (DE-08), `dedup.py` (DE-07), `cache.py` and `freshness.py` (DE-09). New files, no old behaviour.
10. Tests last: read the test **names**, they are written as sentences.

### 3. What changed in old behaviour (the part that can surprise a consumer)

| What | Before | Now | Who can notice |
|---|---|---|---|
| `Retry-After` | seconds only; waited `min(value, max_wait)` and retried | seconds or HTTP-date; waits and retries if the value is within `max_wait`; a longer wait **fails the page** with a clear error (no retry) | crawl counters: more `pages_failed` on rate-limited sites |
| `robots.txt` redirects | a 3xx answer was not followed | followed up to 5 hops (RFC 9309), also to another host (logged and recorded); a 6th hop, a loop or a bad target means "robots unavailable" (origin disallowed for 10 minutes) | which URLs are crawlable |
| `chunk_config` | 4 keys, `extract_fingerprint` optional | **5 keys, all required** | Backend (shared schema) |
| The CHECK on `chunks.chunk_config` | `is_valid_chunk_config` with 4 keys | 5 keys; an old chunk cannot be updated under the new check | **anyone with an existing database**: reset the volume or run the migration note |
| `PipelineConfig(...)` | `chunk_size`, `chunk_overlap`, `extract_fingerprint` arguments | takes `extract_config` (AI's `ExtractConfig`); the three arguments are gone | callers of the pipeline |
| `chunk_provenance` view | 10 columns | 14 (4 appended) | AI (the contract) |
| `ValidatorStore` | `set()` ignored a 200 without validators | `replace()` (and `set` as an alias): drops the old pair then; a 304 never changes it | crawler only (in memory) |
| `Crawler.run` | plain URLs | also `(url, label)` pairs and `CrawlTarget`; licence from the page wins over the list | crawler callers |
| `datasketch` dependency | declared | removed (our own MinHash) | install size |
| `bench/generate.sql` | 4-key chunk_config (would now fail the CHECK) | 5 keys with a placeholder fingerprint | whoever reruns the benchmark |

### 4. What can be skipped

- `docs/p2-plan.md`, `p2-progress.md`, `p3-progress.md` and the rest of this file: history and decisions; read them only for the "why".
- `tests/test_ai_adapter_real.py`: 7 tests marked `ai_real`, **deselected by default and never run against the real AI code**. Skim only.
- `docs/object-storage.md`, `storage/keys.py` (one line), `proposals/de-06-provenance.md` (status changed to "applied").
- Test files that only follow a code change (`test_storage.py`, `test_pipeline.py`, `test_provenance.py`, `test_document_versions.py`).

### 5. Checks to run

`ruff check .` and `pytest -q -rs` in `data/` (needs the local Postgres on port 5433): 0 skipped is the rule. After a pull, reset the
local volume (`docker compose down -v`, then `up -d`) to get the five-key CHECK.

Status: 16 November 2026. Branch `Data-Engineering`. **Nothing was pushed in this round** (see Task 2). Nothing outside `data/` was touched;
`.github/`, `devops/`, `compose.yaml`, `db/knowledge_views.sql` and `ai/` are unchanged by me (the merge brought `ai/` from main).

## Result per task

| # | Task | Done | Commit | ruff | pytest |
|---|---|---|---|---|---|
| 1 | State and merge of main | yes | merge of `origin/main` (163af0a) | pass | 212 passed, 0 skipped |
| 2 | Push + PR | **not done, by the rule** | none | - | - |
| 3 | Read `ai/` on main, compare with the P3 plan | yes (read only) | none | - | - |
| 4 | The real adapter | yes | `2f393da` | pass | **228 passed, 0 skipped, 7 deselected** |
| 5 | This file | yes | (this commit) | pass | 228 passed, 0 skipped, 7 deselected |

## Task 1

- `skillforge-postgres` was stopped (Docker was down); I started Docker and the same container. No new container.
- `git status`: clean except the untracked `docs/p3-progress.md`. Seven local commits ahead of `origin/Data-Engineering` (Tasks 4-9 of the last round, up to `cf4b843`).
- **There is no PR titled "DE-07/09: duplicate detection, domain cache, provenance columns" on GitHub.** The public API lists PRs #1-#26: our branch only has #17 and #18 (both merged earlier). So that PR
  was **never opened**, which means it is neither merged nor open, and there are no replies to read. (The last check, on 10 November, also found no PR.)
- Main moved: AI's PR #4 (`ai/` package) and the AI follow-up PRs #20-#23 were merged on 13 November; open now: #24 (`AI` branch to main), #25 (seed benchmark), #14 (Backend), #26 (Dependabot).
  `git pull --no-rebase origin main` merged with **no conflict**; `data/` itself did not change from main. 212 passed afterwards.

## Task 2: why no push

The condition was "if the DE-07/09 PR was merged and I have unpushed commits: push". The PR does not exist, so it was not merged; I did not push. **Nothing was pushed at all.**
What exists on `origin/Data-Engineering`: up to `e25d9f9` (pushed 10 November). The 8 local commits after it (Tasks 4-9, this round's adapter) plus the merge are not on GitHub.
You still need to open the PR (compare link: `https://github.com/SkillForge-app/SkillForge/compare/main...Data-Engineering?expand=1`). If you want one PR with everything, push first; I did not, so the
titles you gave ("DE-07/09 ..." and "DE-04/08 ...") can be decided by you. When you do, the **Contract change** section must say: yes, `knowledge_views.sql` (4 columns at the end of
`chunk_provenance`, approved by Zeyad) and `extract_fingerprint` is now **required** in the `chunk_config` CHECK (a schema change: Backend must know), and the proposals de-04, de-05 and de-09 are still not applied.

## Task 3: `ai/` on main, compared with the plan of P3 task 9

What `ai/` on main is: the version of AI's PR #4. Open PR #24 (branch `AI`) adds the security/deps update, the pgvector search fix, live results and licence docs; those are **not** on main yet.

| Item | P3 plan said | main says now |
|---|---|---|
| `extract_page` | `(html, *, url, retrieved, config=None) -> ExtractedPage` | **same** (`core/knowledge/extract.py:225`) |
| `embed_sync` | `(texts, *, model_role="embedding") -> list[list[float]]`, `asyncio.run` | **same** (`core/llm/gateway.py:117`) |
| `normalise_url` | `(url) -> str`, `ValueError` | **same** (`core/knowledge/urls.py:26`); docstring has a worked example |
| `ExtractConfig` / `ChunkSettings` | no `size`/`overlap`/`splitter`; `target_words=180`, `overlap_words=40` | **same**; `EXTRACTION_VERSION = 1`, `FINGERPRINT_VERSION = 1` |
| `find_site_boilerplate` | signature unknown | **now read:** `(pages: Iterable[(html, url)], *, min_pages=2, config=None) -> dict[host, tuple[str, ...]]` |
| `embedding_version` | long form | **same string** in `retrieval.md` ("The pinned embedding model") and `models.yaml`; `LocalModel` has `repo`, `revision`, `file`, `sha256` |
| Install | project `skillforge`, hatchling, `packages = ["core", "evaluation"]`, `uv.lock` | **same**: Python >= 3.11; `en-core-web-sm` is a direct-URL dependency (downloaded from GitHub, hash in `uv.lock`); `allow-direct-references = true`; main pins `fastembed==0.9.0` (PR #24 moves it to 0.9.1) |
| Model cache | "check later whether the model is reloaded per call" | **answered:** `_load` in `local_embed.py` has `@lru_cache(maxsize=4)`, so the model is loaded once per process |

**What changed from my plan:** nothing in the signatures. Two things became certain: `find_site_boilerplate`'s shape, and that the model is cached between `embed_sync` calls (so one call per page is fine).

**Will importing it make CI heavier?** Yes if it were a normal dependency (spaCy + its model wheel, fastembed/ONNX, trafilatura, lxml, litellm and langgraph are in the project's list). I did **not** install it, so this is from reading, not measured.
`import core.knowledge` pulls spaCy and langid through `extract`/`nlp`; `litellm` is imported lazily by `core/llm/gateway.py` only when the real LLM backend is built (`litellm_gateway.py` imports it at the top, but that module is loaded only then).
That is why the adapter is an **optional extra** and imports lazily (Task 4). Current `data.yml` runs `uv pip install -e ".[dev]"` (there is no `data/uv.lock`), so the extra is not installed in CI.
**Watch out:** `devops/ci/run-project.sh` runs `uv sync --locked --all-extras` if a `uv.lock` exists; if one is ever added to `data/`, the `ai` extra would be installed in CI and make it slow. Ask DevOps before adding a lock file.
I could not run the real package here (no `yaml`, no spaCy in the data environment), so `PYTHONPATH=../ai` import fails at the first missing module; I stopped there on purpose (no heavy installs).

**Were my open questions answered by the code and docs?**

1. *`size`/`overlap` mapping:* **partly.** AI's `extraction.md` says the `chunking.*` settings are inside the fingerprint, "so DE's `size`, `overlap` and `splitter` keys repeat part of it. Keeping them is harmless; dropping them is DE's call." So AI does not object, and does not name a mapping. Mine (`size = target_words`, `overlap = overlap_words`) stays; it is DE's decision, recorded.
2. *`unknown` licence in `knowledge_chunks`:* **yes, answered.** AI's code never reads a licence (the view has no licence column, and `gap-checker.md` says "AI's code doesn't check the licence again"). AI applies one rule to every passage: `retrieval.md` says to cite and never paste long copied text (spec section 5), and `source-discovery.md` calls `copyright-summarise-and-cite` the default "short summaries, always cite". So no view filter is needed and none was added.
3. Bonus check: the four labels of `crawl_list()` (`public-domain-us-gov`, `cc-by-4.0`, `cc-by-sa-4.0`, `copyright-summarise-and-cite`, plus `excluded-terms`, which never reaches the crawl list) and the SKILL.md allow-list in AI's `source-discovery.md` and `gap-checker.md` (on the `AI` branch) are **identical** to what `licensing.py` implements.

## Task 4: the adapter

Files:

- `skillforge_data/adapters/__init__.py`, `skillforge_data/adapters/ai.py`
- `pyproject.toml`: optional extra `ai = ["skillforge"]`, `[tool.uv.sources] skillforge = { path = "../ai", editable = true }`, marker `ai_real`, `addopts = "-m 'not ai_real'"`
- `tests/test_ai_adapter.py` (16 tests, always run), `tests/test_ai_adapter_real.py` (7 tests, marker `ai_real`)

What it gives (all AI imports are inside functions, through `importlib`; the first use without the package raises `ImportError` with the install command):

| Our side | AI side | Function |
|---|---|---|
| `NormaliseUrl` | `normalise_url` | `normalise_url` |
| `ExtractConfigLike` | `ExtractConfig` (+ `site_boilerplate`) | `default_extract_config(site_boilerplate=())` |
| `ExtractPage` | `extract_page` | `make_extract(config)`; `convert_page` turns AI's pydantic page into our `ExtractedPage`; AI's `ValueError` (its `ExtractionInputError`) becomes `PipelineError` |
| `Embed` | `embed_sync` | `make_embed()`: one call per page, checks count, 384 dimensions and finite numbers (else `PipelineError`, nothing stored); `RuntimeError` (for example a running event loop) becomes `PipelineError` |
| per-host hashes | `find_site_boilerplate` | `site_boilerplate(pages)` |
| `embedding_version` | `models.yaml` | `EMBEDDING_VERSION` = `Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b06...#model_optimized.onnx:sha256=51f1bd0a...`; `embedding_version_from_ai()` reads the same from AI's config so a test can catch drift |

Tests: the always-run ones use stand-ins shaped like AI's objects and cover the conversion (kept reasons, rejected page, screening as object or dict, tuples), the arguments passed to `extract_page`, the error mapping,
`embed` (role, empty input, wrong count/dimension/NaN/inf, error mapping), the **whole pipeline** (`process_document` with the adapter's wrappers stores chunks and embeddings and the chunk_config of the injected config),
that importing the adapter imports nothing from `core` (a fresh subprocess), and the install hint. The `ai_real` tests check: the documented `normalise_url` example (and that our test fake agrees), the default fingerprint
`f33bf1b5...5483`, chunking 180/40, `chunk_config()` with the real config, `embedding_version_from_ai() == EMBEDDING_VERSION`, `embed` over AI's `use_fake()` gateway (384 unit vectors), a real `extract_page` through the adapter,
and the refusal of an `ftp://` URL.

**The `ai_real` tests have never been run** (the package is not installed here). With `-m ai_real` they currently report 7 *skipped* ("could not import core.knowledge"), which is expected without the package.
They are **deselected**, not skipped, in the default run: `pytest -q -rs` shows `228 passed, 7 deselected`, zero skipped, so `data.yml` is not affected. They were written from AI's source and may need small fixes the first time they run with the package installed.

## Decisions I took for you

- Did not push (the PR does not exist, so the rule's condition was false).
- `ai = ["skillforge"]` is declared as an extra, with the path in `[tool.uv.sources]`. **A plain `pip install ".[ai]"` would look up the name `skillforge` on PyPI** (a package we do not own) and could install the wrong thing; the comment in `pyproject.toml` says to use `uv sync --extra ai` or `pip install -e ../ai`. I did not put a file path in the dependency because pip does not support relative paths there.
- `PINNED_EMBEDDING` is written in the adapter as well as read from AI's config on demand, so the pipeline can run `embedding_version` without importing AI; the drift test (`ai_real`) compares them.
- `make_embed` checks 384 dimensions and finite values, but not unit length: the database CHECK already enforces unit length and rejects the vector.
- I did not install anything and did not run the real package (no heavy installs, as agreed).
- `docs/p3-progress.md` is still **untracked**; I did not commit it because you did not ask. Say if you want it committed (message suggestion: `DE-04..09: P3 progress notes`).

## Open questions for Zeyad (AI)

1. Can you confirm that `chunk_config.size = ChunkSettings.target_words` and `overlap = overlap_words` is acceptable (you said it is DE's call)? Or should we drop `size`, `overlap` and `splitter` from `chunk_config` now that the fingerprint covers them?
2. How should `data/` install your package: path dependency on `../ai` (what I used), or will you publish a wheel? Is the name `skillforge` going to stay? (The data environment needs `en-core-web-sm` from a GitHub URL.)
3. Is there a supported way to run `extract_page` and `embed_sync` without spaCy and the model download for contract tests (your fake gateway covers `embed` only)? And is `embed_sync` safe to call from a worker thread (it uses `asyncio.run`)?
4. Is the `SKILLFORGE_MODEL_CACHE` folder meant to be shared by DE's workers, and who downloads the model (`python -m core.llm.local_embed download`) in the deployed environment?

## Open items for others

- **You:** open the PR and decide whether to push the local commits into it; run the `ai_real` tests once in an environment with `uv sync --extra ai` (they have never run); reset your local volume (`docker compose down -v`, `up -d`) to get the five-key `chunk_config` CHECK.
- **Backend:** review the `chunk_config` CHECK change (five required keys) and the `chunk_provenance` columns; proposals de-04, de-05, de-09 still wait.
- **DevOps:** a separate, optional CI job for `ai_real`; and do not add `data/uv.lock` without thinking about `--all-extras`.

## Round of 17 November 2026 (proposals, audit, reviewer guide, P5 plan)

Four tasks, one commit each (`21dbe82`, `9bb67c7`, `babd360`, `611d161`). Last result: `ruff check .` pass, `pytest -q -rs` **234 passed, 0 skipped, 7 deselected** (`ai_real`, not run).
Pushed once at the end to `Data-Engineering`; no PR opened; nothing pushed to main.

Decisions I took:
- **de-05, `clean_object_key`:** in Case 1 today the function does not touch the key at all, so "fill NULL, never replace" is new behaviour, compatible with the code.
  I added one guard (not filled when `clean_deleted_at` is set) and applied the same rule to Case 3. Tested on a throwaway database inside a transaction.
  Orphans: `sweep_orphans()` in `storage/jobs.py` (daily, 24 h age rule). `schema-draft.sql` was **not** changed.
- **de-04, validators:** the crawler already updated them only after a 200 (a 304 branch never wrote). Now a 200 without validators drops the old pair (before it kept them).
  `ValidatorStore.set` stays as an alias of `replace`. 3 new tests. This is the only code change in the round besides the audit fix.
- **de-09, hosts:** the crawler, cache and pipeline normalise hosts in four different ways (table in the proposal). Decision proposed: one helper built on `normalise_url`
  (`host_of`, `origin_of`); **not implemented**, because the task said proposals only. Hash facts are "from the code, waiting for AI to confirm"; expiry policy is an **assumption**.
- **Audit (Task 2):** only `bench/generate.sql` failed the mandatory CHECK (confirmed by running it on a throwaway database: `chunks_chunk_config_check`); fixed with a placeholder
  fingerprint, benchmark meaning unchanged (a 64-char key more per row). New `tests/test_chunk_config_writers.py` lists every file that inserts into `knowledge.chunks`.
  Migration note written in `data-architecture.md` and both paths tried (delete first / `NOT VALID`, with the warning that a `NOT VALID` check still refuses `UPDATE` of old rows).
- **P5 plan:** `docs/de-task-plan.pdf` could **not be read** (no PDF reader here; installing one was refused by the permission system and I did not work around it).
  The plan uses the "Done when" lines of `CLAUDE.md`. Please compare with the PDF. I also found that **DE-10 is not started** and DE-16 needs it.
- The commit message for Task 4 was not given; I used "DE-11: P5 plan for DE-11 to DE-16".

## ملاحظات الجولة (notes of the round, host helper)

Task: one host helper (`skillforge_data/urls.py`: `host_key(url)` and `origin_key(url)`), decided with Backend in the de-09 review. Not pushed, no PR.
Last result: `ruff check .` pass; `pytest -q -rs` **262 passed, 0 skipped, 7 deselected** (28 new tests in `tests/test_urls.py`).

- **Rules** (AI's `normalise_url`): lower-case; default port dropped (80 for http, 443 for https; other ports kept); `user:password@` dropped; IPv6 with brackets.
  Anything not http(s), or with a bad port, raises `ValueError`.
- **Where it is used:** the crawler's rate limit (`fetcher.py`), the robots.txt cache origin and the "redirected to host" note (`robots.py`, `origin_of`),
  the robots redirect and the page redirect checks, and the cache (`DueSource.host_key`, a property computed from the URL; a source that is not http(s) falls back to `host`).
- **Not changed:** `sources.host` (still `urlsplit(url).hostname.lower()` in `run.py`, `process.py`, `licensing.py`), the deny-list check (it matches the bare hostname, no port, on purpose),
  `DueSource.host` (still the stored value), `storage/keys.py`. No schema or view was touched.
- **One behaviour change you may notice:** a URL written with its default port or with `user:password@` used to get its own rate-limit bucket and robots.txt entry; now it shares the one of the plain URL (tests for each case).
- **Decision:** the trailing dot is **kept** (`example.org.` stays), because that is what AI's `normalise_url` does. The test documents it.

Questions (the stored value and the helper differ):
1. **Port:** `sources.host` has no port, the key has one when it is not the default. So `example.org` and `example.org:8443` are one `host` but two keys. Is `sources.host` meant to name a server or a site? (It matters for DE-09's `host_boilerplate` key, which AI's `find_site_boilerplate` also gives without a port.)
2. **IPv6:** `sources.host` is `::1`, the key is `[::1]`. A migration would be needed to align them; no test or data depends on it today.
3. **Trailing dot and IDN:** neither the stored host nor the key joins `example.org.` with `example.org`, nor converts `bücher.example` to punycode. AI's `find_site_boilerplate` key (`HttpUrl.host`) does convert IDN. Do we want to join the trailing dot too (better for rate limits, but it departs from AI's `normalise_url`)?
4. The crawler fetches the **original** URL and stores the canonical one; the key is computed from the original, so it has the same value as from the canonical URL only for the cases above. Confirm that is what you want for the rate limit.

## ملاحظات الجولة (notes of the round: plan, capacity, corpus, monitoring, retention, restore drill, proposals)

Seven tasks, one commit each (`f7b3fc3`, `80077b8`, `97394eb`, `02cc0e4`, `14b9af2`, `31df035`, `a0aea25`). Nothing pushed, no PR (the commits stay local until the current PR is merged).
Last result: `ruff check .` pass; `pytest -q -rs` **315 passed, 0 skipped, 7 deselected** (`ai_real`, not run). No network, no new container; `knowledge_views.sql`, `schema-draft.sql`, `.github/`, `devops/`, `compose.yaml` and `ai/` untouched.

What was done
- **Plan (`p5-plan.md`):** rewritten from the task plan text you pasted: DE-08 to DE-16 each with real state, what is missing against "Done when", the dependency (OPS-xx, AI-xx, BE-xx) and what to build now; section "Differences from the PDF" (10 points). Corrected: P5 is DE-16 only, and DE-16 needs AI-23 (not DE-10).
- **Capacity (`capacity-plan.md`, `bench/capacity_model.py`):** formulas from the measured benchmark numbers (3.3 KB per chunk in tables, 1.95 KB per vector in HNSW), three scenarios (5k / 50k / 500k pages), inputs needed from AI and DevOps. Every guessed input is marked "assumption".
- **Corpus (`skillforge_data/corpus/`):** `GitHubClient` interface and `CorpusCollector`; 18 tests with a fake client. Refused or unknown licences are counted and never downloaded or stored; a file stored earlier whose repository licence becomes refused is **withdrawn** (deleted).
- **Monitoring (`skillforge_data/monitoring/`):** seven checks (failed run, empty run, stuck run, no success in N days, volume drop, unprocessed documents, no new data), `Alert`, `Notifier` interface, `LogNotifier`, structured JSON log events; 23 tests on a real database.
- **Retention (`storage/retention.py`, `storage/daily.py`):** superseded documents after 90 days and `crawl_runs` after 12 months, database first then objects, idempotent, batched; `run_daily_jobs` = raw job, retention, orphan sweep. 13 tests.
- **Restore drill (`scripts/restore_drill.py`, `docs/backup-restore.md`):** ran twice for real (2,000 and 20,000 chunks) inside the existing container: PASSED, throwaway databases dropped.
- **Proposals:** `de-08-corpus.md`, `de-10-datasets.md`, `de-12-analytics-events.md`, `de-13-user-data.md` (questions only). The SQL of the first three was run on throwaway databases; none is applied.

What I could not do, and why
- **Read `de-task-plan.pdf`:** no PDF tool; you pasted the text, which I used. 
- **A real GitHub client:** needs network, a token (a secret) and OPS-09. The interface and the policy are ready.
- **A real notifier and metrics/traces:** need OPS-10. Only the interface and a log notifier exist.
- **A scheduler, a production backup, a restore at production size, the 1M benchmark:** need DevOps (OPS-12, a server with RAM). The drill proves the procedure, not the timing at scale.
- **User-data deletion (DE-13):** needs BE-04 and Backend's answers; I wrote questions instead of guessing.
- **A type checker, GitHub issues, staging:** not mine to decide or not possible (listed in the plan).
- The AI-04 data format: not on main; the DE-10 proposal is a guess of the shape and says so.

Decisions I took (to confirm)
- Retention counts the age of a superseded document from `fetched_at`, because there is no "superseded at" column; "12 months" is 365 days from `started_at`; a `running` run is never deleted.
- An **empty** `succeeded` run does not count as a success for `no_recent_success` (otherwise a crawler that finds nothing looks healthy).
- Corpus: the licence is the **repository's** (GitHub reports one SPDX id per repository), a file over 1 MB is skipped, and the raw bytes go to the raw bucket only for allowed files.
- The restore drill does not compare the HNSW top-10 sets of source and restore: two builds of an HNSW graph differ (overlap was 4 of 10 at 20,000 random vectors). It compares exact results, the nearest chunk, and recall.
- The audit test of the earlier round (`test_chunk_config_writers.py`) caught my new `test_retention.py` as a writer of `knowledge.chunks`; I listed it (its jsonb has the five keys).
- Correction: earlier notes named the daily storage job `run_daily()`; the real name is `run_daily_storage_job()` (and the new `run_daily_jobs()`). Fixed in the de-05 proposal and the plan.

Open questions (also in the proposals)
1. DE-13: what user data can reach us, and the agreed deletion time (nowhere written; planning assumption 30 days).
2. A "superseded at" column on `documents` (makes retention exact), and a `crawl_runs.pages_refused` counter for the corpus (`de-08-corpus.md`).
3. Corpus: should a repository that turns restrictive be **withdrawn (deleted)** or kept and hidden?
4. AI: where is AI-04, how are runs written (`evaluation.runs`), what do runs record to be repeatable?
5. FE and BE: the events and the weekly-review questions of DE-12; who owns `actor_key`.
6. DevOps: backup method and RPO/RTO, production object storage, and who runs the monthly partition and the daily jobs (a scheduler).

## Review of the retention job (17 November 2026, before the PR is reviewed)

Checked the SQL of `storage/retention.py`, wrote the explicit tests, and ran two mutations. Result: `ruff check .` pass; `pytest -q -rs` **321 passed, 0 skipped, 7 deselected**.

**Problem found and fixed (race, not a logic error).** The old statement was
`DELETE FROM knowledge.documents WHERE id IN (SELECT id ... WHERE NOT is_current AND fetched_at < cutoff LIMIT n)`: the conditions were only in the inner SELECT.
If another session made the same document current between the SELECT and the DELETE (the A -> B -> A case of `record_document_version()`), the DELETE still removed it, because
`id IN (...)` is not evaluated again for the new row version. A current document could be deleted. The conditions are now repeated in the outer WHERE, which Postgres does re-check
on the new row version. A test with two real connections reproduces it (the first connection holds a row lock while making the document current; the DELETE waits, then skips it).
It is very unlikely (it needs a superseded document older than 90 days to become current at that very moment), but the consequence was deleting live data, so it is fixed.
No problem found in the crawl-run delete: one statement, and `documents.crawl_run_id` is `ON DELETE SET NULL`.

**The exact conditions:**
- documents: `DELETE FROM knowledge.documents WHERE NOT is_current AND fetched_at < :now - 90 days AND id IN (SELECT id FROM knowledge.documents WHERE NOT is_current AND fetched_at < :now - 90 days ORDER BY fetched_at LIMIT 500) RETURNING raw_object_key, clean_object_key` (looped until it returns nothing; one transaction per batch).
- crawl runs: `DELETE FROM knowledge.crawl_runs WHERE status <> 'running' AND started_at < :now - 365 days`.

**What a deleted crawl run does to documents:** nothing is deleted and nothing breaks; the foreign key sets `documents.crawl_run_id` to NULL (tested, including the chunks and embeddings of those documents, which stay).
Side effect to know: the DE-11 injection-rejection query groups documents by `crawl_run_id`, so after 12 months the old documents no longer belong to any run in that report.

**Mutation checks (done, then reverted):**
1. Removing `NOT is_current` from both conditions made 4 tests fail (the three "current document is never deleted" tests and the two-connection race test).
2. Removing only the outer guard (the old form) made the two-connection test fail and nothing else, so that test is the one that protects the fix.
