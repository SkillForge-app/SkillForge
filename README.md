# SkillForge

SkillForge helps people create, review, and package reusable skills for AI agents.

## Frontend workspace

The Next.js application lives in `apps/web`.

```bash
npm ci
npm run dev
```

## Quality checks

Run these from the repository root:

```bash
npm run format:check
npm run lint
npm run typecheck
npm run build
```

The frontend CI workflow runs the same checks for pull requests and pushes to `main`.

## Frontend planning

- [Design system](DESIGN.md)
- [FE-04 generated API client](docs/frontend/FE-04-api-client.md)
- [FE-05 create-skill wizard](docs/frontend/FE-05-create-skill-wizard.md)
- [FE-06 result and download page](docs/frontend/FE-06-result-download.md)
- [FE-07 account screens](docs/frontend/FE-07-accounts.md)
- [FE-08 clarifying questions](docs/frontend/FE-08-clarifying-questions.md)
- [FE-09 gap-check result](docs/frontend/FE-09-gap-check.md)
- [FE-10 job progress](docs/frontend/FE-10-job-progress.md)
- [FE-11 SkillSpec review](docs/frontend/FE-11-skillspec-review.md)
- [FE-12 package preview](docs/frontend/FE-12-package-preview.md)
- [FE-02 user flows and API touchpoints](docs/frontend/FE-02-user-flows.md)
- [FE-02 low-fidelity wireframes](docs/frontend/FE-02-wireframes.md)
