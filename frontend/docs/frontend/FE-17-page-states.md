# FE-17 — Loading, empty, and error states

**Status:** App-level loading, route error recovery, not-found, and list empty states implemented

## Frontend work completed

- Added a shared route loading screen so navigation and streamed routes do not render a blank page while waiting.
- Added a route error boundary with retry and home navigation, plus a root-level fallback if the application shell fails.
- Added an explicit not-found page with links back to Home and the skill library.
- Preserved recoverable no-results/empty states in the Skill Library and My Skills lists.
- Kept error text generic so internal exception details are not exposed to users.

## Contract boundary

The current Backend OpenAPI does not define the skill-list APIs, so loading and server-error states cannot yet be exercised against those endpoints. The route boundaries cover rendering failures, and list pages already handle empty results. Add API-specific loading/retry/empty mapping when those endpoints are published.
