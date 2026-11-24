# P2 progress: DE-07 and DE-09 built; DE-08 and DE-10 not started

Status: 8 November 2026. Plan: [p2-plan.md](p2-plan.md). Everything below is committed **locally** on `Data-Engineering`, except this file
(not committed, so you can read it first). **Only the CodeQL fix was pushed.** Nothing outside `data/` was touched; `db/schema-draft.sql`,
`db/knowledge_views.sql`, `compose.yaml`, `.github/` and `devops/` are unchanged.

## Result

| Check | Result |
|---|---|
| `ruff check .` (from `data/`) | **All checks passed** |
| `pytest -q -rs` | **128 passed, 0 skipped** (97 before P2; +17 for DE-07, +14 for DE-09), about 25 s on the local Postgres |
| Mutation check on DE-07 | with the promotion rule switched off, 4 DE-07 tests fail (the "duplicates must not make content disappear" ones); restored afterwards |

## Task 1: CodeQL fix: done, pushed

`fcd4ba1` "DE-05: avoid URL-substring pattern in test assertion (CodeQL)": `tests/test_pipeline.py` line 226 now compares the first path
segment with the host (`key.split("/")[0] == "docs.example.org"`), same meaning. Pushed with `git push origin Data-Engineering` (`1637053..fcd4ba1`).
Two minutes later PR #18 (head `fcd4ba1`): `CodeQL` **success**, "No new alerts in code changed by this pull request"; `data / build` **success**;
`ci-ok` success; all 14 checks green or skipped (`backend`, `frontend`, `ai` skipped as before); `mergeable_state: clean`. The alert is closed.

## Task 2: the plan: done

[p2-plan.md](p2-plan.md), commit `6e4d227` "DE-07..10: P2 plan": acceptance criteria, files, dependencies, what can be built now, estimates (about 18 working
days for the four tasks) and an order: DE-07, DE-09, DE-08, DE-10.

## Task 3: what I built (two tasks, as asked; they need nobody and no schema change)

### DE-07: deduplication: done (commit `aff184e`)

Files: `skillforge_data/dedup.py` (new), `skillforge_data/pipeline/process.py` (an optional `dedup` argument, `ProcessResult.duplicate_of`),
`skillforge_data/crawler/run.py` (counts `pages_duplicate`, `CrawlSummary.duplicates`), `tests/test_dedup.py` (17 tests).
What it does: a page that is a copy (estimated Jaccard of 5-word shingles at least 0.85) of **another source's** current, canonical document
gets `duplicate_of`; its signature goes to `documents.minhash`. Copies keep their chunks and embeddings; the existing views already hide them.
When a canonical document stops being current (a new version, a rejected new version) a current copy is promoted **in the same transaction**
and the others are re-pointed (the rule of the DE-07 note); a page that returns (A, B, A) is checked again. The duplicate rate of a crawl is
`pages_duplicate / pages_fetched` (`duplicate_rate`). Tests cover: copy hidden but kept, near copy, unrelated pages, a new version of the same page is never its own
duplicate, signature stored and deterministic, no finder = P1 behaviour, a new finder loaded from the database, B/C promotion, a changed page that is still a copy
of the promoted one, A-B-A with a copy, a rejected new version, no current copy, the rate per crawl.

Decisions I took:
- **Own MinHash instead of `datasketch`'s classes.** The signature is stored in the database for years; datasketch 2.0 (installed here) changed how signatures are
  represented (a new `scheme`, 32-bit values), so a signature from one version cannot be read by another. The implementation is about 40 lines, deterministic (`blake2b`,
  fixed seed) and 1024 bytes per document. `datasketch` stays in `pyproject.toml` from the start but is **not used**; it could be removed.
- **Same-source versions are never duplicates**; the canonical document is the earliest by `fetched_at`; the in-memory index only proposes candidates and the database
  decides (`is_current`, not a duplicate, readable, other source), so a stale index cannot cause a wrong mark.
- **Promotion always runs** in `process_document` (cheap query, no effect when there are no duplicates); marking copies only happens when a `DuplicateFinder` is passed.
- **Language detection and quality filters are AI's** (`extract_page`), already stored by P1; DE-07 adds only the duplicate part. Please confirm this reading of the task plan.
- Defaults: 128 permutations, 5-word shingles, threshold 0.85, 16 bands of 8 rows. They are `DedupConfig` values; changing seed, permutations or shingle size means recomputing signatures.

### DE-09: domain knowledge cache: done (commit `3c1c38f`)

Files: `skillforge_data/cache.py`, `skillforge_data/freshness.py`, `tests/test_cache.py` (14 tests), `docs/proposals/de-09-host-boilerplate.md` (proposal).
What it does: `plan_domain` says **reuse**, **refresh** (enough known sources, some stale) or **crawl** (with how many are missing); `ensure_domain` calls the crawl only when needed,
so a second request in the same domain reuses the cache (tested); `due_for_recrawl` is the re-crawl schedule (oldest first, never fetched first, never robots-forbidden).
A domain also counts the sources of its parents and children (AI's retrieval rule), and a source serves several skills.

Decisions I took: freshness 30 days for web pages, 90 days for `skill_md` and `repo_file`, 5 fresh documents cover a domain (all `FreshnessRules` configuration, assumptions until AI gives the real
number); a usable document is current, not a duplicate, `quality_ok` and `status = 'embedded'`; the cache and the schedule are functions of the database and a `now` argument, so DE-14 can call them
from any scheduler and tests use any clock. The per-host boilerplate record needs a table: proposal only.

## Not done

- **DE-08 (public SKILL.md corpus):** not started. It can be built locally (licence allow-list, licence detection from LICENSE text, SKILL.md parser, local repository scan), but I did not take the
  decision for AI: the list of "permissive" licences is theirs to approve, and where corpus metadata and examples live (a table; served with `knowledge_chunks` or not) needs a proposal and an answer. Details in the plan.
- **DE-10 (evaluation datasets):** not started. It needs new tables (a proposal first, Backend approves) and AI-04's seed benchmark format.

## TODOs and dependencies

- **AI:** confirm DE-07's scope (language/quality are theirs); the number of documents that "covers" a domain; the permissive licence list (DE-08); `find_site_boilerplate` and the format of `site_boilerplate` (DE-09 proposal);
  AI-04's format (DE-10).
- **Backend:** approve `docs/proposals/de-09-host-boilerplate.md` (and the P1 proposals `de-04` and `de-05`); how the worker asks for domain coverage (`ensure_domain`).
- **DevOps:** a scheduler that calls `due_for_recrawl` (DE-14); OPS-09 (scraping network) before the GitHub collector of DE-08.
- **DE:** a persistent near-duplicate index (the in-memory one is rebuilt from the database; about 1 KB per document); wire `DuplicateFinder` and `ensure_domain` into the real crawl entry point when it exists;
  other processes that add documents do not update this process's index (a missed copy, never a wrong mark).
- The CI check for the P2 commits only runs when you push them and open or update a PR.

## Suggested commits

Already made, locally:
1. `fcd4ba1` DE-05: avoid URL-substring pattern in test assertion (CodeQL), pushed.
2. `6e4d227` DE-07..10: P2 plan.
3. `aff184e` DE-07: MinHash duplicates, promotion rule, duplicate rate per crawl.
4. `3c1c38f` DE-09: domain cache (coverage, freshness rules, re-crawl schedule).

For this file: `DE-07/09: P2 progress notes`.
