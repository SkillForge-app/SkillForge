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

## Two rules the columns must follow

These are implemented today for the in-memory `ValidatorStore.replace()` in `skillforge_data/crawler/run.py` and tested in
`tests/test_crawler.py`; a database version of the store must keep them.

1. **Never erase `etag` or `last_modified` because of a 304 without headers.** A 304 (or any non-200: a failure, a block, a 429)
   does not touch the stored values, whether it carries headers or not. A bare 304 is legal; the page is unchanged, so the old
   validators are still right. (Test: `test_a_304_without_headers_does_not_erase_the_stored_validators`.)
2. **Update them only after a successful 200.** A 200 replaces the pair as a whole: if the new response has no `ETag`, the old one is
   dropped (`NULL`), because the next request would otherwise send a validator that belongs to another version of the page.
   (Tests: `test_validators_change_only_after_a_successful_200`, `test_validator_store_ignores_everything_that_is_not_a_200`.)

In SQL terms, the crawler's `UPDATE knowledge.sources SET etag = $1, last_modified = $2 WHERE id = $3` runs only in the branch where the
outcome is a fetched 200, in the same place where `pages_fetched` is counted, and never in the `not_modified` branch.

## Not proposed

Storing the response headers as a whole, or the robots.txt text: not needed, and "store only what is needed".
