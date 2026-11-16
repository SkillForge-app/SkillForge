# P4 progress: sync with main, the real AI adapter

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
