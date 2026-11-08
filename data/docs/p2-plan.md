# P2 plan: DE-07 dedup, DE-08 public skill corpus, DE-09 domain cache, DE-10 evaluation datasets

Status: plan, 8 November 2026. Written from [de-task-plan.pdf](de-task-plan.pdf), [data-architecture.md](data-architecture.md),
[p1-progress.md](p1-progress.md) and the P1 code. P2 is "MVP features, weeks 7 to 10" in the task plan. Where a document was silent, the
assumption is marked **Assumption**.

Warning that applies to everything below: chunks stored before 4 November 2026 are not final and will be rebuilt.

## 1. What P1 already gives P2

`process_document` (one page, one transaction, idempotent), the crawler with `crawl_runs` counters (`pages_duplicate` exists and is not
yet written by anyone), `documents.minhash`, `documents.duplicate_of`, `documents.language` and `source_domains` in the schema, the storage
code, the provenance check, 97 tests on a real Postgres. P2 adds behaviour on top of these; **only DE-10 needs new tables.**

## 2. DE-07: deduplication, language detection, quality filters

**Acceptance criteria:** "Duplicate rate reported per crawl" (task plan). Architecture doc: `documents.minhash` (datasketch signature),
`duplicate_of`; exact duplicates by `content_hash`, near duplicates by MinHash; `crawl_runs.pages_duplicate` gives the rate per crawl;
**duplicates must not make content disappear** (the DE-07 note): when a canonical document stops being current, a current duplicate is
promoted, in the same transaction; test: B, C duplicate of B, supersede B, C's chunks are in `retrievable_chunks`; same for A, B, A.

**Files:** `skillforge_data/dedup.py` (shingles, MinHash signature, finder, canonical promotion, rate), a hook in
`pipeline/process.py` (compute the signature after extraction, set `duplicate_of`, promote on supersession), a counter in
`crawler/run.py`, `tests/test_dedup.py`.

**Language detection and quality filters are AI's:** `extract_page` returns `language` and the quality verdict (`wrong_language`,
`too_short`, `boilerplate`, `injection` ...), which P1 already stores. DE-07 adds nothing to them except reporting. **Assumption:** that is what
the task plan means by "language detection, quality filters" for DE.

**Decisions to take (and write down when built):** shingle = 5 consecutive words of the clean text; 128 permutations; near-duplicate threshold
0.85 estimated Jaccard (configurable); duplicates keep their chunks and embeddings (hidden by the views) so a promoted duplicate needs no
reprocessing; the canonical document is the earliest one by `fetched_at`.

**Buildable now:** all of it. No schema change (the columns exist). **TODO:** a persistent index for the near-duplicate search (the first
version builds an in-memory LSH from the stored signatures, about 1 KB per document, fine for tens of thousands of documents, to be revisited in the
capacity plan, DE-15).
**Dependencies:** AI none. Backend none. DevOps none.
**Estimate:** 4 working days (2 for the finder and the hook, 1 for the promotion rule and its tests, 1 for reporting and docs).

## 3. DE-08: public SKILL.md corpus

**Acceptance criteria:** "Only permissively licensed files used as examples." Collect public SKILL.md files, detect licences, store metadata
(task plan). Architecture doc: licence `unknown` is allowed as background knowledge only and never copied as examples; `sources.source_type`
has `skill_md` and `repo_file`; `license_source` can be `repo`. Spec: the corpus is "license-checked", used for gap checking, style examples and
benchmark data.

**Files:** `skillforge_data/corpus/licenses.py` (SPDX allow-list and the "permissive" test), `corpus/detect.py` (licence of a repository from its
LICENSE text, `SPDX-License-Identifier` headers and package metadata), `corpus/skill_md.py` (parse the front matter and the `references/` folder),
`corpus/scan.py` (walk a local checkout or git repository, return the skills with their licence), `corpus/store.py` (write sources and documents),
`tests/test_corpus.py` (local git repositories created in the test, no network).

**Buildable now:** everything that works on a local folder or a local git repository. **Assumption:** the permissive list is MIT, Apache-2.0,
BSD-2-Clause, BSD-3-Clause, ISC, 0BSD, Unlicense and CC0-1.0. Creative Commons "BY" and "BY-SA" are not on it (attribution and share-alike duties for
text we may show as examples). **This list needs AI's approval, they use the examples.**
**TODO:** fetching repositories from GitHub (needs the scraping network with egress control, OPS-09, an API token and rate limits, and robots/terms
review per source); a place for the corpus metadata (skill name, description, repository, commit, path): the schema has no columns for it,
so a proposal with a small table is part of the work (`docs/proposals/`); whether corpus files are embedded into `knowledge_chunks`
or served separately (**question for AI**: mixing them would show examples as web knowledge).
**Dependencies:** AI (policy list, how examples are retrieved, AI-04 seed skills as a first test set), DevOps (OPS-09). Backend none.
**Estimate:** 5 working days (1 licences, 1.5 detection, 1 SKILL.md parser and scan, 1 store and proposal, 0.5 docs), plus about 3 days
later for the GitHub collector once OPS-09 exists.

## 4. DE-09: domain knowledge cache

**Acceptance criteria:** "A second request in the same domain reuses the cache." Reuse documents across skills, freshness rules, re-crawl
schedule (task plan). Architecture doc: a domain is covered when it has enough fresh current documents (query given, the window is config, not a
column); a source can have several domains so pages are shared; the per-host site boilerplate (`find_site_boilerplate`) is cached here, once per host.

**Files:** `skillforge_data/cache.py` (coverage of a domain, the decision "reuse or crawl", the list of sources due for re-crawl),
`skillforge_data/freshness.py` (freshness rules as config), `tests/test_cache.py`.

**Buildable now:** coverage and decision with domain parents/children (the same rule as AI's filter), freshness per source type, the re-crawl
list ordered by age (only sources whose robots check allowed them, never `robots_allowed = false`), all as functions of the database and the clock.
**Assumptions:** default freshness 30 days for web pages (the window in the architecture doc), "enough" = 5 current documents per domain until AI
gives the number; a source is due when its latest fetch is older than the freshness window.
**TODO:** the per-host boilerplate record (needs a small table, proposal first, and AI's `find_site_boilerplate`); the scheduler that calls
the re-crawl list (DE-14, DevOps); persistent ETag for cheap re-crawls (proposal `de-04-conditional-get.md`, Backend).
**Dependencies:** AI (the number of documents that counts as covered, the boilerplate function), Backend (how the worker asks for coverage),
DevOps (scheduling). **Estimate:** 4 working days.

## 5. DE-10: evaluation datasets

**Acceptance criteria:** "Every evaluation run records its dataset version." Versioned benchmark sets and human labels (task plan). Needs
AI-04 (seed benchmark: 10 seed skills with test prompts and rubrics) and feeds AI's evaluation harness.

**Files:** `skillforge_data/evaluation/dataset.py` (an immutable, content-addressed dataset version: items plus a manifest, version = sha256 of the
canonical content), `evaluation/labels.py` (human labels with annotator, time, and agreement between annotators), `evaluation/registry.py`
(store and resolve versions), `tests/test_evaluation.py`, and **a schema proposal** (`docs/proposals/de-10-evaluation.md`): tables for datasets,
versions, items, labels and the link from an evaluation run to a dataset version.

**Buildable now:** the version format, the validator, the labels model and agreement, and a registry on files or object storage. **Not without a
decision:** where the tables live (the `knowledge` schema is for knowledge data; evaluation data probably needs its own schema, shared with AI), and
who writes the run record (AI's evaluation engine; DE only provides the version id and a function that resolves it).
**TODO:** the tables (needs Backend's approval, database schemas are shared), a labelling interface (Backend or Frontend), loading AI-04's seed set
(needs its format from AI), the bucket for large datasets (DevOps).
**Dependencies:** AI (AI-04 format, how runs record the version), Backend (tables, labelling UI), DevOps (bucket). **Estimate:** 5 working days for
the code and the proposal, more once the tables are approved.

## 6. Time and order

| Task | Estimate (working days) | Waits for | Schema change |
|---|---|---|---|
| DE-07 | 4 | nobody | no |
| DE-09 | 4 | nobody (AI for numbers, can be config) | proposal for the boilerplate table (later) |
| DE-08 | 5 (+3 for GitHub) | AI approves the permissive list; OPS-09 for collecting | proposal for corpus metadata |
| DE-10 | 5 (+ tables) | AI-04 format, Backend approves tables | **yes**, proposal first |
| Total | about 18 days of work, 4 weeks on the calendar with reviews (weeks 7 to 10) | | |

Estimates are ideal days for code, tests and docs, with the same method as P1, and do not include waiting for reviews.

**Suggested order:** 1) **DE-07** first: no dependency, it touches the pipeline invariants (what the views show), and DE-09 should count
duplicates correctly. 2) **DE-09**: no dependency once DE-07 exists, and it is the first thing the AI pipeline asks for ("is this domain covered?").
3) **DE-08**: ask AI for the permissive list now so the answer is ready; build the local part meanwhile. 4) **DE-10** last: its proposal can go to
Backend early (it takes a review cycle), and the code follows when AI-04's format is known.

**What will be built next (decided in this plan):** DE-07 and DE-09, because they need nobody and no schema change.
