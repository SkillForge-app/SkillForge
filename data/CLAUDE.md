# CLAUDE.md — SkillForge (Data Engineering)

## Project
SkillForge (repo name: AgentForge) is a website + AI pipeline that generates installable
agent skills (SKILL.md + references/) for Claude Code and Codex.
Pipeline: Request Analyzer → Gap Checker → Knowledge Collector → Skill Architect →
SkillSpec (Pydantic-validated) → Platform compilers → Evaluation → Optimizer.
Full details: data/docs/project-spec.pdf and data/docs/de-task-plan.pdf. Read them when unsure.
This file lives in `data/` (the Data Engineering folder of the SkillForge repo); paths below are relative to it.

## My role: Data Engineering (DE)
I own the systems that collect, process and store data:
crawler, processing pipeline, knowledge schemas, pgvector indexes, object storage layout,
provenance, public skill corpus, evaluation datasets, analytics, data privacy.
Boundary: AI team decides WHAT to collect and how to interpret it (sources, chunking,
embeddings, retrieval quality). DE builds and runs the systems that do it at scale.
Do not change AI-owned logic; make it configurable instead.

## Stack
Python 3.11, httpx, Playwright, trafilatura, BeautifulSoup, spaCy, MinHash,
PostgreSQL + pgvector (HNSW), object storage, Redis, Docker / docker-compose,
GitHub Actions, OpenTelemetry. Local Postgres runs on port 5433.

## Tasks in order (follow this order)
P0 Foundations
- DE-01 Knowledge schemas (sources, documents, chunks, embeddings) + retention rules. Done: reviewed by BE and AI.
- DE-02 PostgreSQL + pgvector + HNSW index. Done: similarity query < 100 ms on 1M-chunk test set.
- DE-03 Object storage layout (raw pages, clean text, packages) + lifecycle rules. Done: layout documented.
P1 Walking skeleton
- DE-04 Crawler: httpx + Playwright, robots.txt/terms checks, per-domain rate limits, identified user agent, retries. Done: disallowed URLs never fetched (tested).
- DE-05 Pipeline raw → clean → chunk → embed; idempotent, versioned; chunking/embedding configurable. Done: re-run gives same output.
- DE-06 Provenance: URL, retrieval date, license, content hash on every chunk. Done: every chunk traceable.
P2 MVP
- DE-07 Dedup (MinHash), language detection, quality filters. Done: duplicate rate reported per crawl.
- DE-08 Public SKILL.md corpus + license detection. Done: only permissive licenses used.
- DE-09 Domain knowledge cache + freshness + re-crawl schedule. Done: 2nd request in same domain reuses cache.
- DE-10 Versioned evaluation datasets + human labels. Done: every eval run records dataset version.
P3 Hardening
- DE-11 Data-quality checks + pipeline monitoring. Done: alert on failed/empty runs.
- DE-12 Analytics event schema + dashboards. Done: used in weekly review.
- DE-13 Privacy: personal data, user deletion, retention. Done: deletion within agreed time.
P4 Launch
- DE-14 Scheduled prod pipelines; backup/restore tested. Done: restore drill passed.
- DE-15 Capacity plan for 6 months. Done: reviewed with DevOps.
P5 After launch
- DE-16 Optimizer data + MLflow. Done: every optimizer run reproducible.

## Contracts (change only via PR approved by consumers)
- Database schemas/migrations: shared with Backend.
- Retrieval API: query + domain → passages with sources (consumer: AI).
- Analytics event schema (consumers: FE, BE).
- Embedding dimension: 384 (confirmed by the AI team). The `embeddings` table uses `vector(384)`
  and has `embedding_model` and `embedding_version` columns. The index is HNSW with
  `vector_cosine_ops` (metric confirmed final by the AI team).
- `db/knowledge_views.sql` (`chunk_provenance`, `retrievable_chunks`, `knowledge_chunks`) is the contract between
  DE and AI. Any change to it (name, columns, types, filters) needs the AI team's approval, because AI reads
  `knowledge_chunks` and the retrieval API reads `retrievable_chunks`. Load order: `db/schema-draft.sql`, then
  `db/knowledge_views.sql`, then `db/roles-local.sql`.

## Definition of Done (every task)
Tests added, lint + type checks pass, no secrets or personal data in code/logs,
logs/metrics for new jobs, docs updated, "Done when" check passes.

## Git rules
Same as the repo's `.github/CONTRIBUTING.md`.
- Work only on the branch `Data-Engineering`. No personal or task branches.
- Only change files under `data/`. A change in another department's folder needs that department's approval.
- Never push to `main`. It is protected; code reaches it only through a pull request.
- Before you start: `git switch Data-Engineering` and `git pull origin Data-Engineering`.
- Commit messages start with the task ID: `DE-05: add the crawl run table`. Small, clear commits. Work without a
  task uses `fix:`, `docs:` or `chore:`.
- Before committing: run tests, show me git status and the diff, wait for my OK.
- Never commit .venv, .env, secrets, or dataset files.
- Push with `git push origin Data-Engineering`.
- When a task is done, I open a pull request from `Data-Engineering` into `main` and fill in the template (task ID,
  Definition of Done, contract change). Someone from the Data Engineering team approves it, not me.
- Merge with **Create a merge commit** (the only merge option; squash and rebase are off).
- After it merges: `git pull origin main`, then `git push origin Data-Engineering`.
- Never use `git reset`, `git push --force` or `git rebase`. On a conflict, stop and ask.

## Working style
- Explain to me in Egyptian Arabic; code, comments and commits in English.
- Ask before big design decisions or anything that affects other teams.
- Responsible scraping always: respect robots.txt and terms, rate-limit, store only what is needed.

## Commands (Windows, run from `data/`)
- Activate venv (PowerShell): `.venv\Scripts\Activate.ps1`
- Install / refresh deps: `.venv\Scripts\python -m pip install -e ".[dev]"`
- Playwright browser: `.venv\Scripts\python -m playwright install chromium`
- Start Postgres + pgvector: `docker compose up -d` (project `skillforge-data`, container `skillforge-postgres`, port 5433)
- Stop it: `docker compose down` (add `-v` to wipe the data volume)
- Connection string: see `.env.example` (copy to `.env`, never commit it)
- Check pgvector: `docker exec skillforge-postgres psql -U skillforge -d skillforge -c "SELECT extname FROM pg_extension"`
- Tests: `.venv\Scripts\python -m pytest`
- Lint: `.venv\Scripts\python -m ruff check .`
- The old local PostgreSQL 18 service uses port 5432 and has no pgvector. Do not use it for this project.
