# FE-10 — Generation progress

**Status:** UI preview implemented; BE-08 job read and SSE contract pending  
**Route:** `/skills/jobs/[jobId]`

## Frontend work completed

- Added a job progress screen with named stages, source records, failure/retry, and ready states.
- Added a local state picker to preview running, failed, and completed layouts.
- Avoided invented percentages and ETAs; progress is shown as named stages only.
- The completed preview links to FE-06's result route using the current job ID.

## Contract boundary

Stage names and sources in `progress-page.tsx` are preview fixtures, not a finalized AI event schema. BE-08 must define how the job is loaded on refresh, the SSE URL and event names/payloads, stage and source fields, reconnect/resume behavior, error format, and retry semantics. The current retry control only changes local preview state. Source links stay disabled until actual source URLs are supplied.

FE-10 is complete when a refresh restores the real job state, live events update stages and sources, and retry/recovery follows the agreed API behavior.
