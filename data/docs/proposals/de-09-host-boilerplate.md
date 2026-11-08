# Proposal: a table for the per-host site boilerplate (DE-09)

Status: proposal, not applied. No schema or view was changed. 8 November 2026.

## Why

[data-architecture.md](../data-architecture.md) ("Site boilerplate: once per host, in the DE-09 cache") says AI's `find_site_boilerplate(...)`
should run **once per host, not once per page**, and its result be cached with the domain knowledge cache: a small record per host with the
sentence hashes that `ExtractConfig.site_boilerplate` needs. The schema has no place for it, so the pipeline cannot reuse it between runs and the
cache code in `skillforge_data/cache.py` does not cover it.

## Proposed SQL

```sql
CREATE TABLE knowledge.host_boilerplate (
    host              text        PRIMARY KEY CHECK (host = lower(host) AND btrim(host) <> ''),
    sentence_hashes   text[]      NOT NULL DEFAULT '{}',       -- AI's per-site hashes, stored as AI returns them
    pages_used        integer     NOT NULL CHECK (pages_used >= 0),   -- how many pages of the host it was computed from
    extractor_version text        NOT NULL,                    -- AI's EXTRACTION_VERSION when it was computed
    computed_at       timestamptz NOT NULL DEFAULT now()
);
```

The record is not part of the chunk config hash (AI's fingerprint leaves `site_boilerplate` out on purpose), so changing it does not rebuild
chunks by itself; whether a changed record should trigger a re-extraction of the host's pages is for AI to say.

## Who must approve

- **Backend**: it is a change to the database schema (shared with Backend).
- **AI**: they own the content and the format of `site_boilerplate` (hash type and length, how it ages, when to recompute), and the function that makes it.
- Not a change to `knowledge_views.sql`: AI and the retrieval API do not read this table.

After it is applied the local database volume must be reset (`docker compose down -v`, then `up -d`), because the root `compose.yaml` applies the schema
only on the first start of an empty volume.

## What the code will do once it exists

`cache.py` gets two functions: read the record for a host (and tell if it is older than the freshness window or from another `extractor_version`),
and write it after AI's function ran. `process_document` takes the hashes through the extraction adapter. Until then nothing in P2 depends on it.
