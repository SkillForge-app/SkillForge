# Proposal: versioned evaluation datasets and labels (DE-10)

Status: proposal, **not applied**. `db/schema-draft.sql` and the views were not changed. 17 November 2026.
DE-10 in the task plan: *versioned benchmark sets and human labels*. **Done when: every evaluation run records its dataset version.** Needs: AI-04 (the seed benchmark:
10 seed skills with test prompts and rubrics).

**Who must approve: Backend** (a new schema is part of the shared database) **and AI** (they produce the data and the runs, and define what an item and a label are).
After it is applied the local database volume must be reset (`docker compose down -v`, then `up -d`): the root `compose.yaml` runs the schema files only on the first start.

## What I know and what I do not

Known: the format of AI-04 is "10 seed skills, each with test prompts and rubrics". I have **not seen it**: nothing of AI-04 is in this repository on main (checked: no
benchmark file under `ai/`), so the tables below are a **guess of the shape** and every column that depends on it is marked *(depends on AI-04)*. The questions are at the end.

## Design in one paragraph

A **dataset** has many **versions**; a version is a frozen list of **items** (a prompt, a rubric, the skill it belongs to). Humans (and AI's judge) attach **labels** to items.
An **evaluation run** always points to exactly one dataset version (`NOT NULL` foreign key: this is the "Done when", enforced by the database, not by discipline), and records what
was evaluated (code and config versions) and the results. A released version can no longer change: a change is a new version.

## Proposed SQL (a separate schema `evaluation`; draft, untested against real AI-04 data)

```sql
CREATE SCHEMA evaluation;

CREATE TABLE evaluation.datasets (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9_.-]*$'),   -- e.g. 'seed-benchmark'
    description text        NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evaluation.dataset_versions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id    uuid        NOT NULL REFERENCES evaluation.datasets (id),
    version       integer     NOT NULL CHECK (version >= 1),               -- 1, 2, 3...; or a label such as '2026-11-seed'? (question 4)
    status        text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'released', 'retired')),
    content_hash  text        CHECK (content_hash ~ '^[0-9a-f]{64}$'),     -- sha256 over the items, set when released: two equal versions are detectable
    source_ref    text,                                                    -- where the version came from: a file path or commit of AI-04 (depends on AI-04)
    created_at    timestamptz NOT NULL DEFAULT now(),
    released_at   timestamptz,
    UNIQUE (dataset_id, version),
    CHECK ((status = 'draft') = (released_at IS NULL) OR status = 'retired'),
    CHECK (status = 'draft' OR content_hash IS NOT NULL)
);

CREATE TABLE evaluation.items (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id uuid        NOT NULL REFERENCES evaluation.dataset_versions (id) ON DELETE CASCADE,
    item_key           text        NOT NULL CHECK (btrim(item_key) <> ''),  -- a stable id inside the dataset, e.g. 'seed-03/prompt-2' (depends on AI-04)
    skill_domain       text,                                                -- the domain of the skill, if AI-04 gives one
    prompt             text        NOT NULL CHECK (btrim(prompt) <> ''),    -- the test request
    rubric             jsonb       NOT NULL,                                -- AI's rubric, stored as AI writes it (depends on AI-04)
    UNIQUE (dataset_version_id, item_key)
);

CREATE TABLE evaluation.labels (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id     uuid        NOT NULL REFERENCES evaluation.items (id) ON DELETE CASCADE,
    label_kind  text        NOT NULL CHECK (label_kind IN ('human', 'judge')),   -- human label or an automatic judge's
    value       jsonb       NOT NULL,                                            -- score(s) as AI defines them (depends on AI-04)
    labeler_ref text,                                                            -- a pseudonym or a role, NEVER a name or an email (question 6)
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    superseded_by uuid REFERENCES evaluation.labels (id)                        -- a corrected label replaces, it does not overwrite
);

CREATE TABLE evaluation.runs (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id uuid        NOT NULL REFERENCES evaluation.dataset_versions (id),   -- the "Done when": no run without a dataset version
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    code_version       text        NOT NULL,         -- git commit of the evaluated pipeline
    pipeline_version   text,                         -- knowledge pipeline_version used for retrieval
    chunk_config_hash  text,                         -- the active chunk config (knowledge.active_config) at the time
    embedding_version  text,
    settings           jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- model ids, prompts' versions, seeds (what AI needs to repeat the run)
    metrics            jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- scores, cost, latency (depends on AI)
    status             text        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE evaluation.run_items (               -- one row per item of a run: the result for that item
    run_id   uuid NOT NULL REFERENCES evaluation.runs (id) ON DELETE CASCADE,
    item_id  uuid NOT NULL REFERENCES evaluation.items (id),
    result   jsonb NOT NULL,
    PRIMARY KEY (run_id, item_id)
);

-- A released version is frozen: no item of it can be inserted, changed or deleted, and a run can only point to a released version.
CREATE FUNCTION evaluation.guard_frozen_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_status text;
BEGIN
    SELECT status INTO v_status FROM evaluation.dataset_versions
    WHERE id = COALESCE(NEW.dataset_version_id, OLD.dataset_version_id);
    IF v_status <> 'draft' THEN
        RAISE EXCEPTION 'dataset version is % and cannot change; create a new version', v_status;
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER items_frozen BEFORE INSERT OR UPDATE OR DELETE ON evaluation.items
    FOR EACH ROW EXECUTE FUNCTION evaluation.guard_frozen_version();

CREATE FUNCTION evaluation.guard_run_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT status FROM evaluation.dataset_versions WHERE id = NEW.dataset_version_id) <> 'released' THEN
        RAISE EXCEPTION 'an evaluation run needs a released dataset version';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER runs_need_released_version BEFORE INSERT ON evaluation.runs
    FOR EACH ROW EXECUTE FUNCTION evaluation.guard_run_version();
```

Notes: labels are separate from items so that labeling continues after a version is frozen (labels can be added to a released version; correcting one adds a new row and sets
`superseded_by` on the old one). The `runs` columns `pipeline_version`, `chunk_config_hash` and `embedding_version` are the same values as in `knowledge`, so a run can be tied to the data
it ran on (DE-16 needs this too). The `knowledge` schema is not touched and no view changes.

## Tested (17 Nov 2026)

The SQL above was run on a throwaway database (dropped afterwards; the real one was not touched): a run on a draft version is refused ("needs a released dataset version"); a run
with no version is refused (`NOT NULL`); after release, inserting or changing an item is refused; a run on the released version works, and so do `run_items` and labels added after the release.
It was **not** tested with AI-04 data, which I have not seen.

## Questions for AI (AI-04)

1. **Where is AI-04** (the seed benchmark): a file, a directory, a branch? What is its exact format: one JSON per seed skill? What fields have the prompt and the rubric, and is the rubric structured (a list of criteria with weights) or free text? The `rubric jsonb` and `value jsonb` columns assume structure but not which.
2. Is one **item** a (seed skill, prompt) pair? How many prompts per skill (10 skills with how many prompts: the size decides whether a table per item is right)?
3. **Which runs write rows:** does AI's evaluation code insert into `evaluation.runs` and `run_items` directly (it then needs a role with `INSERT`), or does it call a Backend or DE function? Who creates dataset versions: a DE script that loads AI's files?
4. How do you want to **name versions**: integers (`seed-benchmark` v1, v2) or labels (`2026-11-seed`)? When does a dataset change: only when AI adds items, or also when rubrics change (a rubric change should be a new version, since old scores are not comparable)?
5. What does a run **record to be repeatable**: model ids, prompt versions, seeds, temperature? The `settings jsonb` is open; tell us the keys so we can validate them.
6. **Labels:** what scale or schema (pass/fail, 1 to 5, per criterion)? Who labels (staff, outsiders)? We do not store names: is a pseudonymous `labeler_ref` enough, or do you need to know who labeled (then it is personal data and DE-13 applies: question 4 of `de-13-user-data.md`)?
7. Do human labels and the automatic judge's labels live together (`label_kind`), and is inter-labeler agreement needed (several labels per item allowed here)?
8. Should the evaluation data keep the retrieved passages of a run (chunk ids)? Not included: retention deletes superseded chunks after 90 days, so the ids could dangle; say if you need them and for how long.
9. Do you need the database to enforce "released versions are frozen", or is a convention enough (the triggers above are the strict form)?

## Questions for Backend

1. A new schema `evaluation` next to `knowledge` is a change to the shared database: acceptable, or should the tables live in the `knowledge` schema or Backend's?
2. Who owns migrations (which tool)? The draft is plain SQL.
3. Roles: a role for AI's evaluation job with `INSERT` on `runs` and `run_items`, read access elsewhere.

## Not proposed

An API for datasets, a labeling tool, and storing the generated skills of a run (they are Backend's `packages`).
