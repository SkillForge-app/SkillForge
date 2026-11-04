# FE-16 — My skills

**Status:** Searchable, filterable responsive preview page implemented; account and list APIs pending  
**Route:** `/my/skills`

## Frontend work completed

- Added a workspace list for created skills with ready/draft badges, version, platform, and updated date.
- Added local search and status/platform filters, including a recoverable no-results state.
- Added links to create a skill, open a skill, and discover the public library.
- Kept rating disabled until the feedback contract exists.
- Marked all records as preview data; no user-owned data is implied.

## Contract boundary

The adopted Backend OpenAPI currently contains Projects and Repositories APIs only. The private skill list, status vocabulary, authentication/ownership behavior, and rating endpoint are not defined there. Replace local preview records and filters with the agreed API response when Backend publishes those contracts.
