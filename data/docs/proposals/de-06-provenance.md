# Proposal: add the crawl run (and three more fields) to `chunk_provenance`

Status: proposal, not applied. `db/knowledge_views.sql` is the DE-AI contract and was not touched. 5 November 2026.

## What was checked

Asked for in the task plan: "URL, retrieval date, license and content hash stored with every chunk" and "every chunk traceable to
its source". The brief for this work added: the source, the page, the licence and **the run**.

| Asked for | Where it is stored | In `chunk_provenance`? |
|---|---|---|
| Source (URL, host) | `sources.url`, `sources.host` | yes: `url`, `host`, `source_id` |
| Retrieval date | `documents.fetched_at` | yes: `retrieved_at` |
| Licence | `documents.license` (the licence at the latest fetch); `sources.license` + `license_source` | yes: `license` (from the document) |
| Content hash | `chunks.content_hash` (of the text), `documents.content_hash` (of the raw bytes) | yes: `chunk_hash`, `document_hash` |
| Page (title) | `documents.title` | **no** |
| Run | `documents.crawl_run_id` | **no** |
| Pipeline / chunk config that produced the chunk | `documents.pipeline_version`, `chunks.chunk_config_hash` | **no** |

So the view covers the task plan's four items (URL, date, licence, hash). It does not cover the run, the page title or the version of
the pipeline. Everything is *stored* by the pipeline (tested in `tests/test_provenance.py`); only the view lacks the columns.

## How the code works around it today

`skillforge_data/provenance.get_provenance()` reads `chunk_provenance` and joins `documents` for `crawl_run_id` and `title`.
`check_provenance()` checks that each chunk appears in the view with a URL, a time, a licence and a document hash, that
`chunks.content_hash` is the sha256 of the text, and that raw objects still match their `content_hash`. Nothing needs the view to change.

## Proposed change (optional)

Append four columns at the end, so existing columns keep their names, types and order (`CREATE OR REPLACE VIEW` allows exactly that):

```sql
CREATE OR REPLACE VIEW knowledge.chunk_provenance AS
SELECT c.chunk_id      AS chunk_id,
       c.id            AS chunk_uuid,
       c.content_hash  AS chunk_hash,
       d.id            AS document_id,
       d.content_hash  AS document_hash,
       s.id            AS source_id,
       s.url,
       s.host,
       d.fetched_at    AS retrieved_at,
       d.license,                                     -- license as of the latest fetch
       d.crawl_run_id,                                -- NEW: the run that first stored this version
       d.title         AS page_title,                 -- NEW
       d.pipeline_version,                            -- NEW: fetch/clean code version
       c.chunk_config_hash                            -- NEW: which chunk set
FROM knowledge.chunks c
JOIN knowledge.documents d ON d.id = c.document_id
JOIN knowledge.sources   s ON s.id = d.source_id;
```

AI reads only `knowledge_chunks`, so this does not change what AI sees, but the file is the contract, so it needs AI's approval
like any change to `knowledge_views.sql`. The load order and the grants do not change (`roles-local.sql` gives AI no access to this view).

## Two things that are by design, not gaps

- `documents.crawl_run_id` is the run that **first** stored the version. A later run that finds the same content only refreshes `fetched_at`.
  "Which run last saw it" is not recorded (it would need a link table).
- `chunk_provenance` is not filtered by `is_current`, but old versions' chunks are deleted when a newer clean text replaces them (agreed retention),
  so a superseded chunk can no longer be traced after that. The `documents` row stays for 90 days.
