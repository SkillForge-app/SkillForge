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

Today the clean-text key `<document_id>/<extract_fingerprint>.txt` contains the document id, which exists only after the
function ran. So the clean text can only be uploaded **after** the commit, and `clean_object_key` is set in a second small
transaction. If the process dies between them, the document is processed but has no clean text key. A way to avoid it is to let the
pipeline generate the id first, so the clean text is uploaded before the transaction like the raw bytes ("upload first, then the
database", [object-storage.md](../object-storage.md) section 3).

```sql
-- add one optional parameter at the end; the rest of the function stays as it is
CREATE OR REPLACE FUNCTION knowledge.record_document_version(
    p_source_id        uuid,
    p_content_hash     text,
    p_fetched_at       timestamptz,
    p_title            text,
    p_license          text,
    p_pipeline_version text,
    p_crawl_run_id     uuid    DEFAULT NULL,
    p_http_status      integer DEFAULT NULL,
    p_raw_object_key   text    DEFAULT NULL,
    p_document_id      uuid    DEFAULT NULL,      -- NEW: used only when a new row is inserted (case 2)
    p_clean_object_key text    DEFAULT NULL       -- NEW: stored on insert, or on case 3 after the reset
) RETURNS uuid ...
-- case 2: INSERT INTO knowledge.documents (id, ..., clean_object_key) VALUES (COALESCE(p_document_id, gen_random_uuid()), ..., p_clean_object_key)
-- case 3: after the reset of clean_object_key, SET clean_object_key = p_clean_object_key when it is not NULL
```

Also worth fixing in the same change: the comment inside the function ("its chunks and embeddings are still there, so nothing
is embedded twice") is no longer true once old chunks are deleted when a newer version replaces them.

Not urgent. The current pipeline works without it.
