# FE-09 — Gap-check result

**Status:** UI preview implemented; AI-08 matching and BE-11 endpoint contract pending  
**Route:** `/skills/requests/[requestId]/match`

## Frontend work completed

- Added the proposed request-scoped match-result route.
- Added preview states for one match, multiple matches, no match, and lookup error.
- Match cards show a title, summary, platform, version, and descriptive tags without inventing a similarity score.
- Added use, customize, create-new, and retry actions. They explain that service behavior is pending instead of navigating to routes or sending made-up requests.
- Added a state picker so reviewers can inspect all result states while the API is unavailable.

## Contract boundary

All match data and the state picker are local UI fixtures. The proposed route is from the frontend flow map, not a confirmed API path. AI-08 and BE-11 still need to define the match operation, candidate fields, thresholds (if a score is shown), result states, errors, and the behavior and payloads for use/customize/generate. No API call is made by this screen.

FE-09 is complete when the real matching response renders these states and the selected user action starts the agreed flow.
