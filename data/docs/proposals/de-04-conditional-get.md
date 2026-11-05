# Proposal: keep ETag and Last-Modified (conditional GET) in the database

Status: proposal, not applied (no schema change was made). 5 November 2026.

## Why

The crawler (DE-04) sends `If-None-Match` / `If-Modified-Since` so an unchanged page costs one small request instead of a
download, and counts it in `crawl_runs.pages_unchanged`. For that it must remember, per source, the `ETag` and `Last-Modified`
of the last successful fetch. The schema has no columns for them, so today `ValidatorStore` keeps them **in memory**: a new process
starts without them and downloads everything once.

## Proposed change

```sql
ALTER TABLE knowledge.sources
    ADD COLUMN etag          text,           -- ETag header of the last 200 response
    ADD COLUMN last_modified text;           -- Last-Modified header, kept as the server sent it
```

Why on `sources` and not `documents`: the validators describe the page at its URL, not one stored version, and they are
overwritten at each fetch. They are not part of any view. Nothing in `knowledge_views.sql` changes.

Then `ValidatorStore` gets a second implementation that reads and writes these two columns (a small change in
`skillforge_data/crawler/run.py` and `store.py`). The interface (`get(url)`, `set(url, validators)`) stays the same.

## Not proposed

Storing the response headers as a whole, or the robots.txt text: not needed, and "store only what is needed".
