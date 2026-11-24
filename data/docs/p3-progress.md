# P3 progress: Zeyad's review of PR #18 and the follow-up tasks

Status: 10 November 2026. Branch `Data-Engineering`. Only Task 3 was pushed (up to `e25d9f9`); everything after it is **local**.
Nothing outside `data/` was touched. `compose.yaml`, `.github/` and `devops/` are unchanged. `db/` changed only where the tasks named it:
`knowledge_views.sql` (Task 2, the last view, 4 columns) and `schema-draft.sql` (Task 8, the `chunk_config` CHECK).

## Result per task

| # | Task | Done | Commit | ruff | pytest after it |
|---|---|---|---|---|---|
| 1 | Merge main | yes | merge `b585d15` | pass | 128 passed, 0 skipped |
| 2 | `chunk_provenance` +4 columns | yes | `e25d9f9` | pass | 129 passed, 0 skipped |
| 3 | Push + PR link | yes (push), PR not open yet | none | - | - |
| 4 | robots.txt redirects (RFC 9309) | yes | `62d73ea` | pass | 135 passed, 0 skipped |
| 5 | Retry-After dates, long waits fail | yes | `976b009` | pass | 141 passed, 0 skipped |
| 6 | Licence passes through `Crawler.run` | yes | `61f204a` | pass | 147 passed, 0 skipped |
| 7 | Licence policy (DE-08) | yes | `db7eb3b` | pass | 208 passed, 0 skipped |
| 8 | `chunk_config` from the extract config | yes, 2 commits | `54b453b`, `e0a5f75` | pass | 212 passed, 0 skipped |
| 9 | Real adapter: exploration | yes (read only), plus the `embedding_version` fix | `cf4b843` | pass | 212 passed, 0 skipped |

At the start the local Postgres container was stopped (Docker had not started): 79 tests were skipped, so I started Docker and
`skillforge-postgres` (the existing container, no new one) and ran the whole suite again. Every number above is with the database up.

## Task 1: merge main

`git pull --no-rebase origin main`: no conflict. New on main outside `data/`: only workflow action bumps (`.github/workflows/ai.yml`, `backend.yml`,
`codeql.yml`, `data.yml`, `trivy.yml`) and `devops/github/setup-org.sh` (OPS-01, org owner as reviewer). **There is no `ai/` folder on main.**
AI's code is still only on the branches `origin/AI`, `origin/AI-deps` (10 Nov), `origin/AI-live-runs`, `origin/AI-search-fix` (see Task 9).

## Task 2: `chunk_provenance`

`db/knowledge_views.sql`: `d.crawl_run_id`, `d.title AS page_title`, `d.pipeline_version`, `c.chunk_config_hash` appended at the end of
`chunk_provenance`, exactly as in the proposal. The diff is one hunk (5 insertions, 1 deletion) inside the first view; `retrievable_chunks` and
`knowledge_chunks` are untouched, and a test pins their column lists (and the order of the first ten `chunk_provenance` columns). `provenance.py`
now reads the four columns from the view (it joined `documents` before) and `Provenance` has `pipeline_version` and `chunk_config_hash`.
The proposal is marked **applied** (Zeyad approved it in the review of PR #18); `data-architecture.md` says so.

## Task 3: push

`git push origin Data-Engineering` (`fcd4ba1..e25d9f9`). **Open the PR yourself** with the compare link; checks only start when it is open
(workflows run on `pull_request`). When I looked, GitHub had no open PR for the branch and no check runs. The PR will show the commits up to `e25d9f9`;
the commits of Tasks 4-9 need a second push if you want them in the same PR.

## Task 4: robots.txt redirects

`HttpFetcher._fetch_robots` follows up to 5 redirects (`ROBOTS_MAX_REDIRECTS`). A sixth, a loop, a redirect without `Location`, a target that is not
http(s) or a deny-listed host all give `RobotsResponse(None)`, which is the existing "unavailable" rule (origin disallowed for 10 minutes, then asked again).
Every hop is rate-limited by its host. A redirect to **another host** is followed but recorded: a warning in the log, `RobotsResponse.redirects`, and the
policy reason says `robots.txt (redirected to host ...)`. Tests: one redirect, a chain of 5, a chain of 6 (the sixth is not requested and the page is never fetched),
a loop, a cross-host redirect (mock transport) and a deny-listed target.

## Task 5: Retry-After

`Retry-After` is read as seconds or as an HTTP-date (relative to the fetcher's clock; a date in the past means 0; garbage means the normal backoff).
If the wait is longer than `max_wait` (60 s) the page is **not retried and not waited for**: the fetch ends `failed` with `HTTP 429 for <url>: the server asked
to wait 7s (more than max_wait 3s), not retried`, which the crawler counts in `pages_failed` and writes in `crawl_runs.error`. This **changes** the old behaviour
(it used to wait `max_wait` and retry); the old test was replaced. Tests: seconds, future date, date beyond the limit, past date, unreadable value, and the crawl run counter.

## Task 6: licence through `Crawler.run`

`Crawler.run(urls, ...)` accepts, per item: a plain URL (the old call, unchanged), a `(url, label)` pair (the shape of `crawl_list()`), or a `CrawlTarget(url,
license, license_source)`. The licence of a fetched page is: **what the page declares** (`detect_license`), else **the list's**, else `unknown`. It is stored on
the source and on the document; both now agree (the document takes the source's stored licence, and a known licence is never replaced by `unknown`).
A page that was not fetched (blocked, failed) gets no licence from the list. Decision: the licence from the list is stored only when the page was actually fetched.

## Task 7: licence policy (DE-08), `skillforge_data/licensing.py`

- **(a) SKILL.md files:** open list = MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, CC0-1.0, Unlicense, CC-BY-4.0. Everything else is refused with a reason
  (share-alike, GPL family, MPL, NC, ND, unknown, "not on the list"). Simple `OR`/`AND` expressions are read (`OR`: one open alternative is enough; `AND`: all); parentheses and
  `WITH` are refused. `detect_licence_text` recognises LICENSE texts (and reads a text that mentions two licences as the stricter). `register_skill_file` stores an allowed file as a
  `skill_md` source with its `url` and `license` (`license_source = 'repo'`), and **does not store** a refused one.
- **(b) web pages:** the four labels map as you wrote them; the page's own licence wins (`license_source = 'page'`); an unknown or empty label is `unknown` and logs a warning.
- **Schema check:** `sources.license_source` already has `CHECK IN ('page','repo','manual','unknown')`, so the values fit. **No schema change, so no proposal file** (`de-08-licence.md` was not needed).
- No view was changed. 61 new tests: every allowed and refused licence, expressions, text detection, each mapping, "the page wins", and a real crawl through the local test server.

## Task 8: `chunk_config` from the extract config

- `interfaces.py`: `ChunkingSettings` (`target_words`, `overlap_words`) and `ExtractConfigLike` (`chunking`, `fingerprint()`). `PipelineConfig(pipeline_version, embedding_version, extract_config)`;
  `extract_fingerprint` is read once from `extract_config.fingerprint()` and must be 64 lower-case hex characters (else `ValueError`). No 500/50 left anywhere.
- **Decision:** AI's `ChunkSettings` has no `size`/`overlap`/`splitter`. I mapped `size = chunking.target_words` (180 by default) and `overlap = chunking.overlap_words` (40), and kept
  `splitter = "sentence"` as a plain value of ours (AI's chunker works on sentences). AI's docs say these keys repeat part of the fingerprint and keeping them is harmless. **Please confirm with Zeyad.**
- Tests use a fake with **123/17**, which are neither 500/50 nor AI's 180/40: the stored `chunk_config` must show 123 and 17, other values give another chunk set, and the clean key uses the fingerprint.
- `schema-draft.sql` (own commit): `is_valid_chunk_config` now needs exactly five keys; `extract_fingerprint` must be a 64-hex lower-case string; the old "TODO, optional" comment is replaced.
  Tests: nine bad forms are refused (no fifth key, null, not hex, upper case, 63 characters, a number, another name, a sixth key, `size` missing).
- Docs: `data-architecture.md` says chunks stored before 4 November are not final, the local volume must be reset (`docker compose down -v`, then `up -d`) to get the new CHECK, and that **Backend must know** (a change to the shared schema).
  I did **not** reset your local volume: the test suite builds its own throwaway databases from the files, so it passes either way, but the `skillforge-postgres` volume still has the old CHECK.
- `object-storage.md` and `storage/keys.py`: the `v0` clean-key placeholder is no longer written by the pipeline.

## Task 9: the real adapter (exploration, no adapter code, no dependency added)

**Where AI's code is.** Not on main. On `origin/AI` (and `AI-deps`, `AI-live-runs`, `AI-search-fix`) under `ai/`; I read it with `git show` only (no checkout, nothing copied, nothing imported or installed).
It is a project named `skillforge` (`ai/pyproject.toml`, hatchling, `packages = ["core", "evaluation"]`, `uv.lock`, Python >= 3.11), imported as `core.*`.
Their CI (`ai.yml`) does `uv sync --locked` with hash checking and an `exclude-newer` date.

**Signatures** (from `ai/core/knowledge/extract.py` and `ai/core/llm/gateway.py`):

| Function | Signature | Notes |
|---|---|---|
| `extract_page` | `(html: str\|bytes, *, url: str, retrieved: date, config: ExtractConfig\|None = None) -> ExtractedPage` | Never fetches. Raises `ExtractionInputError` (a `ValueError`) for a non-http(s) URL. Normalises the URL itself. |
| `normalise_url` | `(url: str) -> str` (`core.knowledge.urls`, re-exported by `core.knowledge`) | Raises `ValueError`. |
| `embed_sync` | `(texts: Sequence[str], *, model_role: str = "embedding") -> list[list[float]]` (`core.llm`) | `asyncio.run(embed(...))`: **cannot be called inside a running event loop**. Local model (fastembed, ONNX, CPU), 384-d, unit length. |
| `ExtractConfig` | pydantic model; `.chunking: ChunkSettings`, `.site_boilerplate: tuple[str, ...]`, `.fingerprint() -> str` | Default fingerprint `f33bf1b5...5483` (a test pins it). |
| `ChunkSettings` | `target_words=180`, `max_words=250`, `max_chars=1800`, `min_words=50`, `overlap_sentences=2`, `overlap_words=40` | No `size`/`overlap`/`splitter`. |
| `find_site_boilerplate` | in `extract.py` (about line 822) | I did not read its exact signature; needed once per host. |

**What the adapter converts** (AI's pydantic `ExtractedPage` -> our dataclass): `quality.ok` -> `quality_ok`; `quality.reasons` -> `quality_reasons`; `quality.language` -> `language`;
`screening.model_dump()` -> `screening`; each `Chunk` -> `ExtractedChunk` (`chunk_id`, `text`, `position`, `word_count`, `content_hash`, `section`, `concepts` as tuples); `url` -> `str`.
Our `ExtractPage` protocol has the config already bound, so the adapter builds `ExtractConfig().model_copy(update={"site_boilerplate": ...})` per host (the fingerprint ignores `site_boilerplate`).

**`embedding_version`**: AI's `retrieval.md` gives the long form
`Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b060edb00e03bfdd08813a2949946c8ba55#model_optimized.onnx:sha256=51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`
(from `models.yaml`, role `embedding`). I changed the documentation (`data-architecture.md`: the `embeddings` table row, the AI contract note and the answered question 3) and the comment in `PipelineConfig`.
The CHECK only requires non-empty, so nothing else changed. Old rows with the bare revision stay valid. Anything that already stored the bare revision needs a rebuild.

**Does importing it break or slow CI?** Probably, yes, if done naively (not measured: I installed nothing):
- `import core.knowledge` runs `core/knowledge/__init__.py`, which imports extraction, injection guard, search and retrieval. That pulls in **spaCy** (+ the `en_core_web_sm` model wheel, a direct URL dependency),
  `py3langid`, `trafilatura`, `lxml`, `beautifulsoup4`, `pydantic`, `PyYAML`, and `core.llm` (`litellm` is imported lazily, only when the real LLM backend is created; the embedding path through the gateway probably still loads it).
- Real embeddings need **fastembed 0.9.x** (ONNX runtime, tokenizers, huggingface-hub, numpy; no torch) and the model file, fetched once with `python -m core.llm.local_embed download` into `SKILLFORGE_MODEL_CACHE` (about 30 MB, from memory, to be checked).
- AI pins with `uv.lock` and `exclude-newer`; our `data/pyproject.toml` uses loose ranges (`trafilatura>=1.12`, AI wants `>=2.3,<3`). They resolve together on Python 3.11, but two supply-chain policies in one install must be agreed with DevOps.
- `data.yml` has a 10-minute timeout and **fails if any test is skipped**, so real-model tests cannot be "skipped when missing".

**Plan to connect it:**
1. **Not before** `ai/` is on main (or AI publishes it as an installable package). Until then the adapter would import something that is not in the repository.
2. Files: `skillforge_data/adapters/__init__.py`, `skillforge_data/adapters/ai.py` (`make_extract(config_factory)`, `embed_batch(texts)` wrapper over `embed_sync` with a 384-d / unit-length check and batching, `normalise_url` passthrough, a function that builds the per-host `ExtractConfig`),
   `tests/test_ai_adapter.py`, a short doc.
3. Dependencies: a **separate optional extra** `ai` in `data/pyproject.toml` (the AI project, installed from `../ai` or a git ref); the default `pip install -e ".[dev]"` and the current CI stay as they are. The adapter imports `core.*` lazily inside functions, never at module import.
4. Tests, in two kinds so CI never skips: (a) **adapter tests with stand-ins** shaped like AI's objects (plain classes with the same attributes; they check the conversion, the per-host config, errors mapped to `PipelineError`, the 384-d check) run in the normal suite;
   (b) **contract tests against the real code** (default fingerprint equals `f33bf1b5...`, `ExtractConfig().chunking` defaults, `extract_page` on a small HTML, `normalise_url` parity with our test fake, `embed_sync` with `SKILLFORGE_LLM_BACKEND=fake`, and one with the real model) under a marker that `addopts` **deselects** (deselected is not skipped), run in a separate CI job after DevOps agrees.
5. `embed_sync` is for scripts: the batch worker is synchronous, so it fits; if the worker ever becomes async, call it in a thread.
6. Check later: whether `embed_local` caches the loaded model between calls (otherwise the model is reloaded per call and a pipeline run must batch all chunks of a page into one call).

## Decisions I took for you

- Started Docker and the existing `skillforge-postgres` container to run the tests (no new container).
- `ROBOTS_MAX_REDIRECTS = 5`; a cross-host robots redirect is followed, logged and recorded, not forbidden. A deny-listed host is never followed.
- A Retry-After longer than `max_wait` fails the page instead of waiting (as asked); a date in the past means "retry now".
- The licence from the list is stored only for pages that were fetched; the page's own licence wins; a known licence is never overwritten by `unknown`.
- A refused SKILL.md file is not stored at all (it could never be returned by mistake).
- `size`/`overlap` mapped to `target_words`/`overlap_words`; `splitter` stays `"sentence"`.
- `embedding_version`: long form in the docs (AI's answer); no code constant added.
- I read AI's branch with `git show` for Tasks 8 and 9 (the main branch has none of it). Nothing was copied.
- I did not reset the local database volume.

## Open questions

1. **AI:** does your code treat `license = 'unknown'` (and `CC-BY-SA-4.0`, `LicenseRef-us-gov-public-domain`) in `knowledge_chunks` in any special way? The views do not hide or filter by licence; `knowledge_chunks` has no licence column.
   If "summarise and cite only" must be enforced on the AI side, it needs to be told per chunk (a column) or the view must filter, which is a contract change.
2. **AI:** is `size = target_words`, `overlap = overlap_words` the mapping you want in `chunk_config`, or should those two keys be dropped now that the fingerprint covers them?
3. **AI:** the exact signature and return shape of `find_site_boilerplate`; and how `ai/` will be installable from `data/` (path dependency, git ref, or a published package).
4. **Backend:** the `chunk_config` CHECK change (five required keys) and the `chunk_provenance` columns need their review in the PR; the proposals `de-04`, `de-05` and `de-09` are still not applied.
5. **DevOps:** is a second, optional CI job for the real-AI contract tests acceptable, and which supply-chain policy (AI's `uv.lock` + `exclude-newer`) should the `ai` extra follow?
6. **You:** reset your local volume (`docker compose down -v`, `up -d`) when convenient, to get the five-key CHECK.
7. **You:** push the commits of Tasks 4-9 (they are local) into the PR, or open a second PR.

## Commits (local ones after `e25d9f9`)

```
cf4b843 DE-05: record embedding_version in the long form (AI's answer)
e0a5f75 DE-01: require extract_fingerprint in chunk_config
54b453b DE-05: take chunk_config from the extract config, fingerprint required
db7eb3b DE-08: licence policy (open-licence files, web-page mapping)
61f204a DE-04: pass the licence from crawl_list through Crawler.run
976b009 DE-04: honour Retry-After dates and fail pages that ask for long waits
62d73ea DE-04: follow robots.txt redirects (RFC 9309)
e25d9f9 DE-06: add run, title and pipeline columns to chunk_provenance   (pushed)
```

Suggested message for this file: `DE-04..09: P3 progress notes` (not committed, so you can read it first).
