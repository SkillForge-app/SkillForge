# FE-06 — Result and download page v0

**Status:** UI states implemented; job/package API integration pending  
**Route:** `/skills/jobs/[jobId]/result`  
**Dependencies:** BE-08 job status, BE-10 package/download

## Frontend work completed

- Added pending, failed, and ready result states.
- Pending state never shows a made-up progress percentage or ETA.
- Failed state gives a safe recovery path to start a new request.
- Ready state shows Claude Code and Codex package cards; download stays disabled without a real
  package URL. Preview and install actions stay disabled until those routes exist.
- The route reads the job ID and uses the FE-03 color and responsive tokens.

## Previewing the states

The route defaults to the pending state. For UI review, use `?preview=failed` or `?preview=ready`.
These query values are local presentation previews, not backend status values. The ready preview
clearly identifies itself as sample UI and does not pretend to download a package.

## API boundary

The Backend contract currently does not include the BE-08 job status or BE-10 package/download
operations. Once those are added to OpenAPI, replace the preview state with the API response and
enable each platform's download only when its response contains a usable URL or stream. FE-06 is
complete when job status and package download work end to end on staging.
