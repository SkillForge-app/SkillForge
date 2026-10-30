<!-- Title: "<TASK-ID>: <what you did>", e.g. "AI-10: Add chunk quality filter". Work without a task: "fix: …", "docs: …" or "chore: …". -->

## Task

Task ID: <!-- e.g. AI-10 -->
Closes #<!-- issue number -->

## What changed

<!-- A few lines: what and why. Mention anything reviewers should look at first. -->

## Definition of Done

- [ ] Linked to the task issue above; approved by the owning department (CODEOWNERS requests them automatically)
- [ ] Tests added or updated; CI is green (lint, type checks, tests, security scans)
- [ ] No secrets, keys or personal data in the code or logs
- [ ] New endpoints, jobs and pipelines emit logs, metrics and traces (or: not applicable)
- [ ] Documentation updated (README, API docs or a `docs/` page)
- [ ] Deployed to staging and checked there (not applicable until staging exists, OPS-06)

## Contract change

- [ ] No shared contract changed
- [ ] Yes, this changes: <!-- contract name --> and I requested review from its consumers and added the `contract-change` label

| Contract | Owner | Consumers to request |
|---|---|---|
| SkillSpec schema (Python models + `schema.json`) | AI | Backend, Frontend |
| OpenAPI contract | Backend | Frontend |
| Database schemas and migrations | Backend (app data), Data Engineering (knowledge data) | All departments |
| Environment variables, Docker images, local setup | DevOps | All departments |
| AI pipeline interface (functions the worker calls) | AI | Backend |
| Knowledge retrieval (query + domain → passages with sources) | Data Engineering + AI | AI |
| Analytics event schema | Data Engineering | Frontend, Backend |

## Owner bypass (DevOps only)

- [ ] I merged with the owner bypass. This PR only touches `devops/` or `.github/`, and nobody answered the review request within 24 hours: <!-- link to the review request -->
