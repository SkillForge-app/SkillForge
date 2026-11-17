# P5 plan: DE-11 to DE-16 (hardening, launch, after launch)

Status: 17 November 2026. A plan only; **no code was written for it**. Written for the owner of Data Engineering.

> **What this plan is based on, and what it is not.** I could not read `docs/de-task-plan.pdf`: no PDF reader is installed here (`pdftoppm` is
> missing), and installing a PDF library was refused by the permission system, so I did not work around it. The acceptance criteria below are the
> **"Done when" lines in `CLAUDE.md`** (they come from that plan) plus what `data-architecture.md`, `object-storage.md`, `p1-progress.md`,
> `p2-progress.md` and the workflows already say. If the PDF has more criteria, **add them**: marked "check the PDF" below. Time estimates are
> **my own**, in working days for one person, with the tests and docs the Definition of Done asks for; they are assumptions, not from the plan.

## Summary and suggested order

| Order | Task | Can start now? | Estimate | Waits for |
|---|---|---|---|---|
| 1 | DE-11 data-quality checks + monitoring | yes, mostly | 4 to 5 days | DevOps (where alerts go) for the last step |
| 2 | DE-13 privacy: personal data, deletion, retention | partly (retention jobs yes) | 4 days | Backend + owner (agreed deletion time, user data location) |
| 3 | DE-15 capacity plan | yes (numbers from our own tests) | 2 days | DevOps review (that is its "Done when") |
| 4 | DE-14 scheduled prod pipelines, backup/restore | the code yes; the schedule and the drill need DevOps | 5 to 6 days | DevOps (scheduler, storage, backup target) |
| 5 | DE-12 analytics events + dashboards | only the schema proposal | 3 days now, 3 later | Frontend + Backend (they consume the schema) |
| 6 | DE-16 optimizer data + MLflow | design only | 3 days now, 4 later | **DE-10 (not started, 3 to 4 days, outside this plan's range)**, AI (what the optimizer reads and writes), DevOps (an MLflow service) |

Why this order: DE-11 first because every later job needs "did it run and was it empty" (its checks are used by DE-14 and by the drill).
DE-13 next because retention jobs and the deletion path change what DE-14 must schedule and back up. DE-15 before DE-14 because the numbers
decide the sizes of disk, backup and schedule. DE-12 and DE-16 depend on other departments, so their proposals go out early and the work waits.
Total if nothing blocks: about **21 to 25 working days**, and about 10 of them are not blocked by anyone.

## Dependencies in one place

| On | What we need | Tasks |
|---|---|---|
| **DevOps** | a scheduler (cron, GitHub Actions schedule or a job runner); the alert channel; object storage in prod (MinIO/S3, see `object-storage.md` "open questions"); backup target; an MLflow service; OPS-09 (scraping network) | DE-11, 14, 15, 16 |
| **Backend** | answers on the three schema proposals (`docs/proposals/`); where user data and request text live; the agreed deletion time; review of the knowledge-schema changes | DE-13, 14, and the proposals |
| **AI** | confirm the `host_boilerplate` format; what the optimizer reads and writes; evaluation dataset needs (DE-10 is **not started**: `p2-progress.md` says it needs new tables, a proposal Backend approves, and AI-04's seed benchmark format) | DE-16, DE-09 follow-up |
| **Frontend** | which events and dashboard views they need | DE-12 |

---

## DE-11: Data-quality checks + pipeline monitoring

**Acceptance (CLAUDE.md):** alert on failed or empty runs. Check the PDF for more.

**Already in the repo:** `crawl_runs` with status and counters (`succeeded`/`partial`/`failed`; an empty run ends `succeeded` with zeros "so DE-11
alerts on that", `p1-progress.md`); the duplicate rate per crawl (DE-07); logs from every job; three checks written as SQL in
`data-architecture.md` (duplicate `chunk_id` in `knowledge_chunks`, injection rejections per run, `embeddings.domains` against `source_domains`);
"`active_config` missing is an alert".

**Files to create**
- `skillforge_data/quality/checks.py`: one function per check, each returns a `CheckResult(name, ok, detail, count)`; no side effects.
- `skillforge_data/quality/report.py`: runs all checks and a "last run" summary; exit code non-zero when a check fails (so a scheduler can alert on it).
- `skillforge_data/quality/metrics.py`: counters and timings (OpenTelemetry names; see below).
- `docs/monitoring.md`: the list of checks, thresholds, what each alert means and what to do.
- `tests/test_quality_checks.py`.

**Checks (all from existing documents or tables)**
1. Failed run: `crawl_runs.status = 'failed'`, or `partial` above a threshold of failed pages. 2. Empty run: finished with `pages_fetched = 0` and `pages_unchanged = 0`.
3. A source that stopped producing (no new document for N days). 4. Duplicate `chunk_id` in `knowledge_chunks` (must return nothing).
5. `embeddings.domains` differs from sorted `source_domains`. 6. No row in `active_config`, or chunks of the active config missing.
7. Rise in injection rejections per run. 8. Duplicate rate per crawl above a threshold. 9. A current, embedded document with no chunk or no embedding.
10. Embedding with the wrong dimension or a non-finite value (the adapter already refuses them; this is the safety net on stored data).
11. Raw/clean objects that no row references (orphan count growing: the daily sweep should keep it near zero), and rows pointing at missing objects (`reconcile_raw` repairs the raw case).

**Build now (nobody needed):** items 1 to 11 as SQL + Python, tests on throwaway databases, the report command, `docs/monitoring.md`, metric names.
**TODO / needs others:** where the alert goes (DevOps: channel, who is paged); thresholds (**assumptions** until real data exists: propose, then tune after the first real crawls);
OpenTelemetry exporter configuration (DevOps). Optional schema change: a counter `crawl_runs.pages_rejected_injection` (the file says the schema has room; Backend must approve).
**Risk:** thresholds on an empty system are guesses; start with "failed" and "empty" only (the task's wording) and add the rest as warnings.
**Estimate:** 4 to 5 days.

## DE-13: Privacy: personal data, user deletion, retention

**Acceptance (CLAUDE.md):** deletion within agreed time. **The agreed time is not written anywhere in the repo** (open question 3 for Backend in `data-architecture.md`).

**Already in the repo:** a full retention table (`data-architecture.md`, "Retention"): raw 30 days, clean text until replaced, superseded documents 90 days,
inactive-config chunks 30 days, sources 12 months, `crawl_runs` 12 months, logs 90 days; the daily raw expiry and orphan sweep (`storage/jobs.py`).
The knowledge tables hold **public web content only**; user accounts and requests belong to Backend ("should not add user columns here").

**Files to create**
- `skillforge_data/retention.py` (or `jobs/retention.py`): one function per row of the retention table that is **not** implemented yet (superseded documents 90 days, inactive config 30 days, stale sources, old `crawl_runs`), each returning a report like `JobReport`.
- `docs/privacy.md`: what personal data exists in which store (a data map), what DE stores (public content, URLs, hashes, crawl logs), what it never stores, how deletion works, the agreed times.
- `skillforge_data/privacy/scan.py`: a scan for personal data in stored text and logs (emails, phone numbers) with a report, because pages can contain names and emails; plus a check that logs never contain request text.
- `tests/test_retention.py`, `tests/test_privacy_scan.py`.

**Build now:** the missing retention jobs (they are agreed in review, except the numbers marked PROPOSED), the data map, the scan, and tests of each rule at its boundary (day 29/30/31).
**TODO / needs others:**
- **Backend:** where user request text and accounts live, and who runs "delete this user". If analytics events (DE-12) carry a user id, they must be deletable by that id: decide that **before** DE-12 fixes its schema.
- **Owner/legal:** the agreed deletion time (days), and whether any crawled page counts as personal data (named people on public pages): the proposed answer is "yes, remove on request by URL" (`DELETE FROM knowledge.sources WHERE url = ...` cascades; object storage keys follow from the rows).
- A deletion-by-URL command with an audit line (what, when, no personal data in the log).
**Estimate:** 4 days.

## DE-15: Capacity plan for 6 months

**Acceptance (CLAUDE.md):** reviewed with DevOps. Check the PDF for the expected form (document, spreadsheet).

**Already in the repo:** benchmark results (`docs/de-02-benchmark.md`: 1M numbers are **estimated, not measured**, on a 7.7 GB machine); the retention table;
the object layout and sizes per bucket (`object-storage.md`); the storage key sizes; "revisit with the capacity plan" notes in `p1-progress.md` (sweeps hold key lists in memory).

**Files to create:** `docs/capacity-plan.md` (and optionally `bench/capacity_model.py`, a small script that turns assumptions into numbers so DevOps can change them).
Content: pages per day and per domain, chunks per page (measured on the test pages), bytes per chunk/embedding/HNSW entry (measure on a 100k and 1M set on a bigger machine if DevOps can give one), raw and clean storage with the 30-day rule, WAL and backup size, RAM needed for HNSW (the benchmark says about 2 GB per million vectors; check), crawl bandwidth and time with per-domain rate limits, embedding CPU time per chunk (from AI's local model), growth over 6 months in three scenarios.
**Build now:** the model, the document, a measured bytes-per-chunk from a real small crawl (needs network and the owner's OK to crawl; or use the test pages as a floor).
**TODO / needs others:** expected traffic and the number of domains (product/Backend), DevOps's real limits and costs, and the **1M benchmark on real hardware** (the one number that is only estimated today).
**Estimate:** 2 days, plus the review meeting. **Do it before DE-14**: the schedule and backups depend on these numbers.

## DE-14: Scheduled prod pipelines; backup/restore tested

**Acceptance (CLAUDE.md):** restore drill passed.

**Already in the repo:** `due_for_recrawl` and the freshness rules (DE-09, "functions of the database and a `now` argument, so DE-14 can call them"); the daily storage job `run_daily()`; the crawler and `process_document`; the note that two workers on one source are not tested ("DE-14 should avoid it by queueing per source").

**Files to create**
- `skillforge_data/jobs/runner.py`: one entry point per job (`crawl`, `process`, `storage-daily`, `retention-daily`, `quality-report`), with a lock so a job cannot run twice at once, exit codes, structured logs, run records.
- `skillforge_data/jobs/queue.py`: a queue of work **per source** (Redis is in the stack, or a table), so two workers never process one source.
- `docs/operations.md`: the schedule (table of job, frequency, expected duration, owner), how to run a job by hand, what to do when one fails.
- `docs/backup-restore.md`: what is backed up (Postgres, object storage), how often, where, how to restore, and the **restore drill** log.
- `tests/test_jobs.py` (locking, per-source queue, exit codes).
- Scripts for the drill (`scripts/backup.sh`, `scripts/restore_drill.sh`), run against a **throwaway** database, never against the real one by default.

**Build now:** the runner, the lock, the per-source queue, the job functions that already exist wrapped for scheduling, the drill scripts tested locally on a throwaway database (dump, restore, compare row counts and a sample retrieval query).
**TODO / needs others (DevOps):** the scheduler and where jobs run; production Postgres with pgvector and its backup tooling (`pg_dump`/WAL archiving or the cloud's snapshots); object storage in prod and its versioning/replication; secrets; the real drill on prod-like infrastructure (the "Done when"); OPS-09 (the scraping network) before any crawl from production.
**Risks:** restoring an HNSW index is slow (plan for a rebuild time in the drill and write it down); the schema applies only on first start of an empty volume (a migration tool is needed before prod: **ask Backend which one they use**).
**Estimate:** 5 to 6 days of our work, plus the drill with DevOps (half a day).

## DE-12: Analytics event schema + dashboards

**Acceptance (CLAUDE.md):** used in the weekly review. This is a **contract** (consumers: Frontend and Backend): changes only through a PR they approve.

**Already in the repo:** nothing specific. Events that DE itself can produce: crawl runs, pages processed, rejected pages by reason, duplicate rate, cache hit (`plan_domain` reuse), retrieval calls (if Backend reports them), and later skill-generation events from Backend/Frontend.

**Files to create:** `docs/proposals/de-12-analytics-events.md` (the schema proposal: event name, version, timestamp, an **anonymous** actor id, properties; no personal data; naming rules; how a schema change is versioned); `db/analytics-draft.sql` (a separate schema `analytics`, append-only `events` table, partitioned by month, plus summary views); `skillforge_data/analytics/events.py` (a small validated model per event type); `docs/dashboards.md` (the weekly-review questions and the SQL behind each); tests.
**Build now:** the proposal and the DE-owned events (pipeline and crawl), the table and views on a throwaway database, validation tests.
**TODO / needs others:** Frontend and Backend: which events they emit and which questions the weekly review asks (we should **ask for the questions first** and design the schema backwards from them); the dashboard tool (DevOps/owner: Grafana, Metabase or plain SQL views); the privacy link with DE-13 (can a user's events be deleted?). Nothing is applied until Backend and Frontend approve.
**Estimate:** 3 days for the proposal and the DE-owned part; 3 more after the answers.

## DE-16: Optimizer data + MLflow

**Acceptance (CLAUDE.md):** every optimizer run reproducible. This is "after launch" (P5): do not start before DE-14 is stable.

**Not yet in the repo:** DE-10 (versioned evaluation datasets, "every eval run records the dataset version") is not started; DE-16 depends on it, so **DE-10 must come first** (add it to the order, before DE-16). **Already in the repo:** the config fingerprint (`ExtractConfig.fingerprint()`), `chunk_config_hash`, `embedding_version` and `pipeline_version`, which together describe how a data set was produced.

**Files to create:** `skillforge_data/optimizer/runs.py` (record a run: dataset version, data snapshot, `chunk_config_hash`, `embedding_version`, code version, random seed, parameters, metrics); `docs/optimizer-data.md` (what is logged and how to reproduce a run from it); optionally `docker/mlflow` is **DevOps's** (not ours); tests with a local file-based MLflow store (no server) if the package is allowed in the dev extras.
**Reproducible means:** given the logged run id, the same dataset version + the same data snapshot (a dated export, or the set of document hashes) + the same configs + the same seed gives the same inputs. Data snapshots are the hard part: **documents are deleted by retention**, so a run must record document **hashes** and keep what it needs, or the run cannot be re-created after 90 days. Decide the rule with AI.
**Build now:** the design and the run record (on our tables), snapshot of ids and hashes. **TODO / needs others:** AI (what the optimizer reads and writes, its metrics, where MLflow is called from); DevOps (an MLflow service, its database and artifact store, access); a decision about dependencies (MLflow is a heavy package: keep it in an optional extra, like `ai`, and not in `data.yml`'s install).
**Estimate:** 3 days now (design, run record), 4 more with AI and DevOps.

---

## Open questions (to close early, because they block work)

1. **Owner/Backend:** the agreed user-deletion time for DE-13. 2. **Backend:** which migration tool the shared schema will use, and the answer to the three proposals (`de-04`, `de-05`, `de-09`).
3. **DevOps:** scheduler, alert channel, prod object storage, backup target, MLflow service, OPS-09. 4. **AI:** confirm the `host_boilerplate` format and the optimizer's inputs.
5. **Frontend + Backend:** the weekly-review questions that DE-12 must answer. 6. **Owner:** the PDF criteria this file could not read: compare once and add what is missing.

## What to do in the first week, with nobody's help

DE-11 checks and report command (2 days), the missing retention jobs of DE-13 (2 days), the capacity model (1 day). Send the questions above in the same week, so the answers arrive while the unblocked work is done.
