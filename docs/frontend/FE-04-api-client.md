# FE-04 — Generated API client

**Status:** Generated client and typed Projects/Repositories CRUD calls are ready  
**Contract:** [`openapi/openapi.json`](../../openapi/openapi.json), OpenAPI 3.1.0, AgentForge Backend 0.1.0  
**Source:** [Backend branch](https://github.com/SkillForge-app/SkillForge/blob/Backend/openapi-backend-current.json)

## What FE-04 adds

- `openapi-typescript` generates `apps/web/lib/api/schema.d.ts` from the backend contract.
- `openapi-fetch` creates a typed HTTP client from the generated paths and operations.
- `projectsApi` and `repositoriesApi` expose typed CRUD calls for the endpoints currently
  available in the contract.
- `npm run api:generate` regenerates the types after an OpenAPI change.
- `npm run api:check` regenerates them and checks for a stale generated file.
- Frontend CI runs that check on every pull request and push to `main`.

The generated schema is the source for request and response types. Do not edit `schema.d.ts` by
hand. The CRUD input aliases in `projects.ts` and `repositories.ts` refer directly to generated
operation request bodies; they do not duplicate the wire schemas.

## Using the client

Copy `apps/web/.env.example` to `apps/web/.env.local` for local development. It uses the local
backend origin `http://127.0.0.1:8000`. Staging has no confirmed URL yet. The environment variable
is `NEXT_PUBLIC_API_BASE_URL`.

```ts
import { createApiClient } from "@/lib/api/client";
import { projectsApi } from "@/lib/api/projects";

const api = projectsApi(createApiClient());
const { data, error } = await api.get(projectId);
```

The API functions return the typed `{ data, error, response }` result from `openapi-fetch`; a page
should handle loading, validation errors, network failures, and success before updating the UI.

## Backend behavior confirmed on 1 November 2026

- Projects and Repositories endpoints currently do not require authentication. This describes the
  current implementation; it does not settle the final product security model.
- `404` means a project or repository was not found.
- Deleting a project returns `409` when related records prevent deletion. Repositories are not
  cascade-deleted, so they must be deleted first; other related records can also prevent deletion.
- `422` covers validation errors, including `null` for a required field. The `detail` value can be
  a string or an array, depending on the error source.
- In `PATCH`, omitted fields stay unchanged. `null` clears Project `description` or Repository
  `default_branch`; `name`, `provider`, and `repository_url` cannot be null.
- `provider` is currently a free string from 1 to 50 characters.
- Local development uses `http://127.0.0.1:8000`; the staging origin is still pending.

## OpenAPI update requested

The current generated OpenAPI file does not list the confirmed `404` and `409` responses, and its
validation error schema describes `detail` as an array only. Backend should add the `404` and `409`
response schemas and describe `detail` as either a string or a validation-error array. Until that
updated file arrives, the UI can inspect the HTTP status and treat unrecognized error bodies as
unknown data; it must not assume the generated error type completely describes these cases.

List operations currently return arrays without pagination. This is fine for an initial small
workspace; add pagination before project/repository lists can grow large.
