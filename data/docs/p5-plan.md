# Plan for what is left of DE-08 to DE-16, aligned with the task plan

Status: 17 November 2026 (rewritten the same day, after the text of `de-task-plan.pdf` was pasted in; I still cannot open the PDF itself).
A plan, not code. Estimates are mine (working days, one person, with tests and docs), so they are **assumptions**. Anything not from the PDF
text, the code or the docs is marked "assumption".

**Corrections to the first version of this file.** (1) The PDF's last phase is **P5 = DE-16 only**; this file used "P5" for DE-11 to DE-16, which was wrong.
(2) **DE-16 needs AI-23, not DE-10.** DE-10 needs AI-04 (the seed benchmark). (3) The first version left out DE-08 (the collector) and DE-10.
(4) Go-live checks of the PDF: crawler compliance tests pass and every chunk has provenance (DE-04, DE-06); backups restored and data deletion works (DE-13, DE-14).

## The state of each task against its "Done when"

| Task | "Done when" (PDF) | Needs | Our real state (from code and docs) | What is missing | Build now |
|---|---|---|---|---|---|
| DE-08 | only permissively licensed files used as examples | DE-04 | policy done: `licensing.py` (allow-list, text detection, `register_skill_file`, 61 tests) | **the collector** (GitHub search for `SKILL.md`, fetch, repo licence): nothing talks to GitHub; "only permissive files used" is true only for files someone registers by hand | the collector with a fake client (the next batch, Task 3); OPS-09 for the real network |
| DE-10 | every evaluation run records its dataset version | AI-04 | **not started**; no tables | tables for dataset versions, items, labels, runs; AI-04's format (10 seed skills with test prompts and rubrics) | proposal `proposals/de-10-datasets.md`; tables only after Backend and AI answer |
| DE-11 | alert on failed or empty runs | OPS-10 (OpenTelemetry collector, logs, metrics, traces, alerts) | `crawl_runs` with status and counters; duplicate rate per crawl; logs; SQL checks written in `data-architecture.md` | the checks as code, an alert object, a notifier; **metrics and traces do not exist** (only `logging`); no alert path | `skillforge_data/monitoring/` with a notifier interface (Task 4); wiring to OPS-10 later |
| DE-12 | dashboard used in the weekly review | BE-18; the schema is a **contract** (producer DE; consumers FE and BE) | nothing | event schema, table, dashboards | proposal `proposals/de-12-analytics-events.md`; no table until FE and BE approve |
| DE-13 | a deletion request removes user data within the agreed time | BE-04 (auth) | retention table documented; raw expiry and orphan sweep run daily (`storage/jobs.py`); knowledge tables hold public content only | superseded documents (90 days) and `crawl_runs` (12 months) are **not enforced**; user-data deletion unknown; the agreed time is not written anywhere | retention job (Task 5); `proposals/de-13-user-data.md` with questions to Backend |
| DE-14 | restore drill passed | OPS-12 | storage job `run_daily_storage_job()` (and `run_daily_jobs()`); `due_for_recrawl` for a scheduler; **no scheduler, no backup, no drill** | scheduled prod pipelines; backup and restore of the database **and the vectors** with DevOps | a restore drill script on a throwaway database (Task 6); the scheduler waits for DevOps |
| DE-15 | reviewed with DevOps | - | benchmark numbers exist (`de-02-benchmark.md`, 1M **estimated**); storage layout documented | the plan itself | `capacity-plan.md` (Task 2) |
| DE-16 | every optimizer run reproducible from stored data | AI-23 | config fingerprints, `chunk_config_hash`, `embedding_version`, `pipeline_version` exist and describe how data was made | optimizer data tables, MLflow, the rule for keeping data a run used | design after AI-23 is known; **P5, after launch** |

For the finished tasks (DE-01 to DE-07, DE-09) see "Differences from the PDF" below: two of them are not fully met either.

## Differences from the PDF

1. **DE-02 is not met.** Done when: "similarity query under 100 ms on a 1M-chunk test set (local first, staging in P1)". The 1M data was generated but the HNSW index
   could not be built on this machine (7.7 GB RAM): the 1M numbers in `de-02-benchmark.md` are **estimated, not measured**. The 100 ms target is met only on smaller sets. And there is no staging.
2. **DE-03: "applied to staging storage in P1"** is not met: the layout is documented and coded (S3 adapter, in-memory storage), nothing runs on real object storage (MinIO needs DevOps).
3. **DE-04:** the Playwright fetcher is **not written** (only the `PageFetcher` interface; httpx only). Needs OPS-09 for a scraping network. "Disallowed URLs are never fetched (tested)" is met.
4. **DE-08 lacks the collector** (see the table). The policy is complete.
5. **DE-07:** duplicate rate per crawl is met. Language detection and quality filters are AI's (`extract_page`) and only stored by us; I read the task that way (p2-progress.md) and asked AI to confirm.
6. **There is no type checker in `data/`.** The PDF's Definition of Done says "lint and type checks"; `pyproject.toml` has `ruff` and `pytest` only (no mypy or pyright). Adding one is a choice for the owner (assumption: mypy, 1 to 2 days to get a clean run on the code; AI's `ai/pyproject.toml` already uses mypy with the pydantic plugin, so it would match).
7. **Metrics and traces do not exist yet** (the Definition of Done asks for "logs, metrics and traces for new jobs"). We have logs and `crawl_runs` counters only. It depends on OPS-10.
8. **Staging deployment** (also in the Definition of Done) is not possible: no staging yet (OPS-06 in the PR template).
9. **There are no GitHub issues for our tasks.** The Definition of Done says "PR linked to an issue", and the PR template has `Closes #`. Someone must open one issue per task (DE-04 to DE-16) before the PRs.
10. **Go-live check "backups restored and data deletion works"** is open: DE-13 and DE-14 are not done.

## Order (assumption) and size

| Order | Task | Unblocked now? | Estimate (assumption) | Waits for |
|---|---|---|---|---|
| 1 | DE-11 checks, alert interface | yes | 3 days | OPS-10 for the real notifier |
| 2 | DE-13 retention job; user-data questions | the job yes | 2 days + answers | BE-04, Backend (deletion time, user data) |
| 3 | DE-15 capacity plan | yes | 2 days | DevOps review |
| 4 | DE-08 collector | with a fake client yes | 3 days | OPS-09 for the real client |
| 5 | DE-14 restore drill, then schedules | the drill yes | 3 days + 3 | OPS-12, DevOps |
| 6 | DE-10 datasets | proposal only | 1 day + 3 | AI-04, Backend, AI |
| 7 | DE-12 analytics | proposal only | 1 day + 3 | BE-18, FE, BE |
| 8 | DE-16 optimizer data, MLflow | no | 3 + 4 | **AI-23**, DevOps (MLflow service) |

Reason: DE-11 first because the other jobs report through it; DE-13 and DE-15 shape what DE-14 schedules and how big the backups are; DE-10, DE-12 and DE-16 wait for other departments, so the proposals go out early.
About 25 to 30 days in all, about 13 of them not blocked by anyone (assumption).

## Per task: what to build now, what waits

- **DE-08:** collector package `skillforge_data/corpus/` with a `GitHubClient` interface (search `SKILL.md`, fetch file, fetch repo licence), policy from `licensing.py`, idempotent, rate-limited; counts refused files without storing their content. Waits: the real client needs OPS-09 and a token (a secret: DevOps).
- **DE-10:** tables (dataset, dataset_version, item, label, eval_run with `dataset_version_id`), versioned and immutable once released. Needs AI-04's format first. Labels are human data: who may write them is a question for AI.
- **DE-11:** checks (failed run, empty run, no successful run for N days, sudden volume drop), `Alert` + `Notifier` interface, structured log events. Later: metrics and traces with OPS-10.
- **DE-12:** event schema as a **contract** (versioned, no personal data, anonymous actor id), `analytics` schema, views for the weekly review. Ask FE and BE for the review's questions first.
- **DE-13:** retention job (documents 90 days, `crawl_runs` 12 months; the DB first, then the files), then user-data deletion once Backend says what user data can reach us. The agreed time is unknown.
- **DE-14:** drill on a throwaway database inside the existing container (dump, restore, compare counts, check the HNSW and a similarity query); then a scheduler and real backups with DevOps. HNSW rebuild time is part of the drill (assumption: it is slow on a large set).
- **DE-15:** `capacity-plan.md` with formulas from measured numbers, three scenarios, inputs needed from AI and DevOps.
- **DE-16:** run record (dataset version, data snapshot as document hashes, `chunk_config_hash`, `embedding_version`, code version, seed, metrics). **Documents are deleted by retention** (documents after 90 days when superseded), so "reproducible" needs a rule for what a run keeps: ask AI. MLflow is heavy: keep it in an optional extra, like `ai`.

## Dependencies in one place

| On | What we need | Tasks |
|---|---|---|
| DevOps | OPS-09 (scraping network), OPS-10 (collector, alerts), OPS-12 (backups), a scheduler, prod object storage, the MLflow service, a staging | DE-04 (Playwright), DE-08, DE-11, DE-14, DE-16 |
| Backend | answers on proposals de-04, de-05, de-09; BE-04 (auth) and what user data reaches DE; BE-18 (analytics) | DE-13, DE-12 |
| AI | AI-04 (seed benchmark), AI-23 (optimizer), confirm `host_boilerplate` and DE-07's scope | DE-10, DE-16 |
| Frontend | the questions of the weekly review | DE-12 |
| Owner | open one GitHub issue per task; decide on a type checker; the agreed deletion time | all |
