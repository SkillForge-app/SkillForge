# FE-15 — Skill detail

**Status:** Detail route and tab navigation implemented with clearly labeled preview data; registry integration pending  
**Route:** `/library/[skillId]`

## Frontend work completed

- Linked the skill cards in FE-14 to their detail routes.
- Added an Arabic, responsive skill detail view with overview, versions, sources, files, and ratings tabs.
- Added the available preview metadata: category, supported platforms, current version, update date, and source count.
- Added unavailable states for details not present in the current OpenAPI contract. Use, customize, and download actions remain disabled until their APIs are defined.
- Unknown preview IDs return the standard not-found page.

## Contract boundary

The adopted Backend OpenAPI currently contains Projects and Repositories APIs only. It does not define a skill registry/detail endpoint, version history, source records, file listing, ratings, or download actions. The visible records are local previews and are not presented as live registry results. Replace the preview data and enable actions after Backend publishes those contracts.
