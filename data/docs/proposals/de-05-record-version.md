# Proposal / decision: `record_document_version()` and the order of work in DE-05

Status: decision taken for the pipeline (no schema change needed); one **optional** schema change proposed. 5 November 2026.

## The open point

[data-architecture.md](../data-architecture.md) noted: `record_document_version()` makes the new document current, and hides
the old one's chunks from the views, as soon as the page is fetched, before it is processed. If processing then fails, the page
has no chunks in the views even though the old chunks still exist. Backend also asked that old chunks and embeddings are only
deleted after the new version is processed and stored successfully, in the same transaction.

## Decision (implemented in `skillforge_data/pipeline/process.py`, no schema change)

The pipeline does everything that can fail **before** calling the function, then does the database work in **one transaction**:

1. Normalise the URL, upsert the source, check the content hash against what is already stored.
2. Upload the raw bytes (idempotent: the key is the hash; an existing key is skipped).
3. `extract_page`, drop repeated `chunk_id`s, `embed`, check dimensions and unit length. Any failure here ends the run with
   nothing changed in `documents` or `chunks`.
4. One transaction: `record_document_version()`, the page's verdict (`quality_ok`, reasons, `screening`, `status`), the new chunks and
   embeddings, deletion of the chunks of the source's older documents (the cascade removes their embeddings), and `clean_deleted_at` on
   those documents.
5. After the commit: delete the old clean-text objects, then store the new clean text and set `clean_object_key`.

Result: until the commit, the old version is still current and fully visible; if the transaction fails, it is rolled back as a whole
(tested with a chunk that breaks a CHECK after the flip: the old document is still current, with all its chunks); a failure is
logged, counted in `crawl_runs.pages_failed` with its error text, and returned.

Why this is the safest option without a schema change: it never leaves a state where the page has no visible chunks because of a
failed run, and it needs nothing from the database that the schema does not already do.

Known cost: a few seconds of extra work happen before the version flip, so two workers on the same source can both embed the same
new content; the function's per-source advisory lock keeps the flip itself consistent, and the second worker should then find the
document already current and replace the identical chunk set (it deletes the set of its config first). Two workers on one
source at the same time is **not tested**; DE-14 should avoid it by queueing per source.

## Optional schema proposal (not applied): let the caller choose the document id

Status of this part: proposal only. `db/schema-draft.sql` is **not** changed by this file. It would be applied as a migration
(or by editing the draft) after approval.

**Who must approve: Backend.** The function is part of the database schema, and "database schemas/migrations" are shared with
Backend (`CLAUDE.md`, contracts). AI does not need to approve: the change does not touch `knowledge_views.sql` or any view.

**After it is applied, the local database volume must be reset** (`docker compose down -v`, then `docker compose up -d` from the repo
root). The root `compose.yaml` runs `db/schema-draft.sql` only on the first start of an empty volume, so an existing local database
keeps the old function until it is recreated. DevOps should know, because the same applies to any shared development database.

### Why

Today the clean-text key `<document_id>/<extract_fingerprint>.txt` contains the document id, which exists only after the
function ran. So the clean text can only be uploaded **after** the commit, and `clean_object_key` is set in a second small
transaction. If the process dies between them, the document is processed but has no clean text key. If the pipeline can choose the
id first, the clean text is uploaded before the transaction like the raw bytes ("upload first, then the database",
[object-storage.md](../object-storage.md) section 3), and the key is stored by the function itself.

### Why a plain `CREATE OR REPLACE FUNCTION` is wrong

A function is identified by its name **and its argument types**. `CREATE OR REPLACE` with two more arguments creates a second function
beside the old one (an overload); it does not replace it. With both present, a call with the nine arguments the pipeline uses today
fails with `function knowledge.record_document_version(...) is not unique` (checked, see "Tested" below). So the old function is
dropped first, and because dropping removes its privileges, the `REVOKE` that `schema-draft.sql` runs for the old signature is
repeated for the new one.

### The SQL (complete; run it in one transaction)

Only two things change in the body: `p_document_id` and `p_clean_object_key` are used when a row is inserted (case 2), and
`p_clean_object_key` when an old row is brought back (case 3); the comment about chunks is corrected. Case 1 is unchanged.

```sql
-- 1. The old signature goes (nine arguments, as in db/schema-draft.sql). Its privileges go with it.
DROP FUNCTION knowledge.record_document_version(
    uuid, text, timestamptz, text, text, text, uuid, integer, text);

-- 2. The new function: the same nine arguments, plus two optional ones at the end.
-- record_document_version: what the DE-05 pipeline calls for every fetched page.
-- It keeps "one current version per source" true in all three cases:
--   1. same content as the current version     -> refresh fetched_at
--   2. new content                              -> demote the current row, insert a new current row
--   3. old content comes back (A -> B -> A)     -> demote the current row, bring the OLD row back
-- Case 3 matters because UNIQUE (source_id, content_hash) makes a plain insert fail, and an
-- insert-or-ignore would leave B current and A hidden even though the page now serves A.
-- If A's clean text was already deleted, A goes back to status 'fetched' so it is cleaned
-- again. Its chunks and embeddings were deleted when B replaced it (retention), so the pipeline
-- chunks and embeds A again; this function does not touch chunks.
-- p_document_id (case 2 only) lets the caller choose the id of a NEW row, so an object key that
-- contains it can be uploaded before the transaction. p_clean_object_key is stored on a new row
-- (case 2) and on a returning row (case 3, after the reset).
CREATE FUNCTION knowledge.record_document_version(
    p_source_id        uuid,
    p_content_hash     text,
    p_fetched_at       timestamptz,
    p_title            text,
    p_license          text,
    p_pipeline_version text,
    p_crawl_run_id     uuid    DEFAULT NULL,
    p_http_status      integer DEFAULT NULL,
    p_raw_object_key   text    DEFAULT NULL,
    p_document_id      uuid    DEFAULT NULL,
    p_clean_object_key text    DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_id         uuid;
    v_is_current boolean;
BEGIN
    -- One writer per source at a time, so two workers cannot both demote and insert.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_source_id::text, 0));

    SELECT id, is_current INTO v_id, v_is_current
    FROM knowledge.documents
    WHERE source_id = p_source_id AND content_hash = p_content_hash;

    IF v_id IS NOT NULL AND v_is_current THEN                       -- case 1
        UPDATE knowledge.documents
        SET fetched_at = p_fetched_at,
            license = p_license,
            http_status = p_http_status,
            raw_object_key = COALESCE(p_raw_object_key, raw_object_key),
            raw_deleted_at = CASE WHEN p_raw_object_key IS NULL THEN raw_deleted_at END
        WHERE id = v_id;
        RETURN v_id;
    END IF;

    -- Demote first: the partial unique index allows only one current row per source.
    UPDATE knowledge.documents SET is_current = false
    WHERE source_id = p_source_id AND is_current;

    IF v_id IS NOT NULL THEN                                        -- case 3
        UPDATE knowledge.documents
        SET is_current = true,
            fetched_at = p_fetched_at,
            license = p_license,
            http_status = p_http_status,
            raw_object_key = COALESCE(p_raw_object_key, raw_object_key),
            raw_deleted_at = CASE WHEN p_raw_object_key IS NULL THEN raw_deleted_at END
        WHERE id = v_id;
        UPDATE knowledge.documents
        SET status = 'fetched', clean_object_key = NULL, clean_deleted_at = NULL
        WHERE id = v_id AND clean_deleted_at IS NOT NULL;
        IF p_clean_object_key IS NOT NULL THEN
            UPDATE knowledge.documents SET clean_object_key = p_clean_object_key WHERE id = v_id;
        END IF;
        RETURN v_id;
    END IF;

    INSERT INTO knowledge.documents                                 -- case 2
        (id, source_id, crawl_run_id, fetched_at, http_status, content_hash, license,
         pipeline_version, title, raw_object_key, clean_object_key)
    VALUES
        (COALESCE(p_document_id, gen_random_uuid()), p_source_id, p_crawl_run_id, p_fetched_at, p_http_status,
         p_content_hash, p_license, p_pipeline_version, p_title, p_raw_object_key, p_clean_object_key)
    RETURNING id INTO v_id;
    RETURN v_id;
END
$$;

-- 3. Functions are executable by everyone by default. Only the pipeline's role should call this.
--    Repeat what db/schema-draft.sql does for the old signature, now for the new one. (That file has no
--    GRANT for this function: "grant EXECUTE to it when that role exists".)
REVOKE EXECUTE ON FUNCTION knowledge.record_document_version(
    uuid, text, timestamptz, text, text, text, uuid, integer, text, uuid, text) FROM PUBLIC;
```

The pipeline calls the function with the nine arguments it uses today, so it keeps working unchanged. Using the two new arguments
is a small change in `skillforge_data/pipeline/process.py` after approval (not made).

When `db/schema-draft.sql` itself is edited, its own comment above the function, the function and the `REVOKE` after it must be
replaced by the text above, so the draft and the migration agree.

Not urgent. The current pipeline works without it.

## Tested

The SQL above was applied to a throwaway database (PostgreSQL 18.6, pgvector 0.8.6) that had `db/schema-draft.sql` and
`db/knowledge_views.sql` loaded, inside transactions that were rolled back. The throwaway database was dropped afterwards; the real
database and `db/schema-draft.sql` were not touched.

| Check | Result |
|---|---|
| Functions named `record_document_version` before | 1 (nine arguments) |
| `CREATE FUNCTION` for the new signature **without** the `DROP` | 2 functions (9 and 11 arguments); the pipeline's nine-argument call fails: `function knowledge.record_document_version(...) is not unique` |
| The SQL above | 1 function (11 arguments); the old one is gone |
| A plain role can execute the new function | **No** (the `REVOKE` works); the owner can |
| Same SQL **without** the `REVOKE` | a plain role **can** execute it, so the `REVOKE` must be repeated |
| Today's function, for comparison | a plain role cannot (the `REVOKE` in `schema-draft.sql`) |
| Nine-argument call (what the pipeline does today), new row | works; `clean_object_key` is empty |
| Case 2 with `p_document_id` and `p_clean_object_key` | the row has the chosen id and the key |
| Case 1 (same content again) | same id; the key is not changed |
| Case 3 (A, B, A, with A's clean text deleted in between) | the old row comes back, is current, `status = 'fetched'`, `clean_deleted_at` cleared, key = the new one; B is demoted |
| After the rollback | 1 function again (nine arguments); the test role does not exist |
| The 97 tests of `data/tests`, run on a **copy** of `data/` whose `schema-draft.sql` had this SQL appended | **97 passed, 0 skipped** |

What the 97 tests do not cover: the two new arguments are not used by any test or by the pipeline yet (the cases above were run by hand
in the transaction), and nothing was tried against a database that already has data (the `DROP` + `CREATE` does not touch the rows).
