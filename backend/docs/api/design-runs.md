# Design runs (API) and downloading compiled files

All paths start with `/api/v1`. `docs/openapi.json` is not regenerated yet; run the app and use
`/openapi.json` for the exact schemas.

## Flow

```
POST /design-runs {project_id, request, targets}      -> 202, status "queued"
  poll GET /design-runs/{id}                           -> running -> ...
    needs_input   questions[] -> POST /design-runs/{id}/answers {answers}   -> 202, continues
    completed     spec_version_id -> POST /runs {project_id, spec_version_id, target_platform}
    blocked | retry_later | failed   user_message (safe to show), error_code, issues
```

## Design runs

| Method and path | Purpose |
|---|---|
| `POST /design-runs` | Start a run. Returns at once; the pipeline runs in the background. 404 unknown project, 422 invalid body, 503 AI package not installed |
| `GET /design-runs/{run_id}` | Status, `questions`, `progress` events, `usage`, `spec_version_id`, `version_number` |
| `GET /projects/{project_id}/design-runs` | The project's runs, newest first |
| `POST /design-runs/{run_id}/answers` | Answer the questions (any may be skipped: omit it or send `text: null`). 409 if the run is not waiting or already continuing, 422 for a question that was not asked |

Statuses: `queued`, `running`, `needs_input`, `completed`, `blocked`, `retry_later`, `failed`.

- `completed` means a SkillSpec passed the backend validator and was stored as the project's
  next version. The status and the version are committed together.
- `blocked` stores nothing: the analyzed request is cleared and no version is created (BE-14).
- `retry_later` and `failed` store no version. To try again, start a new run.
- `progress` is a list of `{step, stage, attempt, message}`; poll the run to read it while the
  design is running. A streaming (SSE) endpoint is not built yet.

`SKILLFORGE_PIPELINE=fake` uses the AI package's `FakePipeline` (example data, no model calls).
The default is `real`. Both need the `ai/` package (`core`) installed next to the backend.

## Compiling and downloading (runs API)

Compiling is the existing `POST /runs` (queues a compiler job, the worker writes the files to
`ARTIFACTS_DIR/<run_id>/`) and `GET /runs/{id}` for the status. This adds:

| Method and path | Purpose |
|---|---|
| `GET /runs/{run_id}/download` | A zip of the compiled files. 404 unknown run, or a run with no files of ours; 409 if the run is not `completed`, or a file is missing or its SHA-256 no longer matches the one recorded |

Artifacts sent by an external runner through `POST /runs/{id}/result` are not files of ours
(`storage_url` is whatever the runner sent), so they are not in the zip.
