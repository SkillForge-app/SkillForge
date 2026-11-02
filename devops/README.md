# devops/

Everything the DevOps department owns lives here. The exceptions are files GitHub or Git only read from fixed
places (listed below).

## Contents

| Path | What it is |
|---|---|
| `github/setup-org.sh` | Applies the GitHub settings: org defaults, repo settings, teams and members, labels, rulesets. Safe to re-run |
| `github/ruleset-main.json` | Protection for `main`: PR required, code owner approval, no force push, no deletion. The org owner may bypass it on PRs |
| `github/ruleset-main-ci.json` | `main` requires the `ci-ok` check. No bypass, not even for the owner |
| `github/ruleset-departments.json` | Protection for the 5 department branches: no force push, no deletion |
| `github/mirror.sh` | The one-time copy from `mmtrabya/AgentForge` (kept for the record) |
| `ci/changed-folders.sh` | CI: which department folders a PR changed |
| `ci/run-project.sh` | CI skeleton for backend/, frontend/, data/: install, lint, test if they exist |
| `ci/gitleaks.toml` | CI secret scan config: default rules plus allowlisted test sentinels |
| `ci/gitleaksignore` | Individual gitleaks findings a person checked and confirmed are not secrets (by fingerprint, with the reason) |
| `security.md` | Security scanning (OPS-11): what runs, where results show up, who handles alerts |
| `compose.md` | The local stack (OPS-03): start, stop, reset the data, connect |
| `compose/postgres-initdb/` | First-start init for the local postgres: pgvector, then Data Engineering's `data/db/` SQL |
| `docker/web.Dockerfile` (+ `.dockerignore`) | The web app image, built from `frontend/` (Frontend's code). DevOps-owned |

## Local stack (OPS-03)

See [compose.md](compose.md). In short: `cp .env.example .env`, then `docker compose up -d` from the repo root
starts postgres + pgvector (`127.0.0.1:5433`) and redis (`127.0.0.1:6379`); add `--profile web --build` for the
web app (`127.0.0.1:3000`). `.github/workflows/compose.yml` checks the stack (`stack`) and the web image (`web`);
neither is a required check. `frontend.yml` runs Frontend's `npm ci`, checks and build.

## Security (OPS-11)

See [security.md](security.md). In short: `.github/workflows/codeql.yml` (CodeQL) and `trivy.yml` (Trivy) report to
the Security tab and are **not** required checks; `.github/dependabot.yml` opens grouped weekly update PRs for
GitHub Actions and `ai/`; Dependabot alerts, security updates, secret scanning and push protection are on.

## CI (OPS-02)

`.github/workflows/ci.yml` runs on every PR into `main` or a department branch, and every push to `main`
(`ci-ok` is required only on `main`). `data.yml` tests against a throwaway pgvector database and fails
if any test is skipped:

| Job | What it does |
|---|---|
| `changes` | Finds which department folders changed. A change to the CI itself runs everything |
| `repo-checks` | actionlint, shellcheck on `devops/`, JSON files parse, CODEOWNERS has no errors |
| `secret-scan` | gitleaks over the full history |
| `ai`, `backend`, `frontend`, `data` | That department's workflow, only when its folder changed |
| `ci-ok` | Passes when every job above passed or was skipped. **The only required check** |

Each department owns its workflow file together with DevOps (`.github/workflows/<department>.yml`). Every
action is pinned to a commit SHA of a release at least two weeks old; downloaded tools are checked by sha256.

## Changing GitHub settings

Edit the file, then apply it. In Git Bash, from the repo root, as an org owner (gh scopes `repo`, `admin:org`,
`workflow`):

```
devops/github/setup-org.sh --dry-run   # shows what it would change
devops/github/setup-org.sh
```

- **Add or remove a person:** edit `MEMBERS` in `setup-org.sh` and re-run. New people get an org invite. People
  not listed are removed from that team.
- **Change branch protection:** edit the ruleset JSON and re-run. The script updates the ruleset with the same name.
- **CI checks (OPS-02):** required checks live in `ruleset-main-ci.json` (no bypass). Only add a new one after the CI job
  has run once, or every PR will wait for a check that never reports.

## Files outside devops/

| File | Why it lives there |
|---|---|
| `.github/CODEOWNERS` | GitHub only reads it from the root, `docs/` or `.github/` |
| `.github/pull_request_template.md` | Same three places only |
| `.github/ISSUE_TEMPLATE/` | Issue forms only load from this folder |
| `.github/CONTRIBUTING.md` | GitHub links to it on the new issue and PR pages only from the root, `docs/` or `.github/` |
| `.github/workflows/` | GitHub Actions only runs workflows (and reusable workflows) from here |
| `.github/dependabot.yml` | Fixed location: Dependabot only reads it from there |
| `/.gitignore`, `/.gitattributes` | Git applies them per folder; only the root copy covers the whole repo |
| `/compose.yaml` (OPS-03) | `docker compose up` looks for it in the current folder. Its init script lives in `devops/compose/` |
| `/.env.example` (OPS-03) | Compose reads `.env` from the same folder as `compose.yaml`. Local-dev placeholders only |
