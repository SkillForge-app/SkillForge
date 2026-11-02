# FE-14 — Skill library

**Status:** Search, local preview filters, and responsive skill cards implemented; BE-11 registry integration pending
**Route:** `/library`

## Frontend work completed

- Added a searchable skill-library page with category, platform, and sort controls.
- Added responsive cards showing a skill summary, category, platforms, version, and source count.
- Added local preview pagination and a no-results state with a reset action.
- Marked the visible skill records as preview data so they are not mistaken for registry results.

## Contract boundary

The current Backend OpenAPI does not include the BE-11 skill-registry endpoint. Search/filter controls and pagination currently operate on local preview records. Replace those records and local filtering with the registry response when BE-11 defines supported query parameters, filters, sorting, pagination, and response fields. Opening skill details is the following task, FE-15.

FE-14 is complete when the page uses the supported BE-11 search contract, displays the returned skill records, and handles the registry loading, empty, error, and pagination states.
