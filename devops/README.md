# devops/

Everything the DevOps department owns lives here. The exceptions are files GitHub or Git only read from fixed
places (listed below).

## Contents

| Path | What it is |
|---|---|
| `github/setup-org.sh` | Applies the GitHub settings: org defaults, repo settings, teams and members, labels, rulesets. Safe to re-run |
| `github/ruleset-main.json` | Protection for `main`: PR required, code owner approval, no force push, no deletion |
| `github/ruleset-departments.json` | Protection for the 5 department branches: no force push, no deletion |
| `github/mirror.sh` | The one-time copy from `mmtrabya/AgentForge` (kept for the record) |
| `ci/changed-folders.sh` | CI: which department folders a PR changed |
| `ci/run-project.sh` | CI skeleton for backend/, frontend/, data/: install, lint, test if they exist |
| `ci/gitleaks.toml` | CI secret scan config: default rules plus allowlisted test sentinels |

## CI (OPS-02)

`.github/workflows/ci.yml` runs on every PR into `main` and every push to `main`:

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
- **CI checks (OPS-02):** add a `required_status_checks` rule to `ruleset-main.json`. Only do this after the CI job
  has run once, or every PR will wait for a check that never reports.

## Files outside devops/

| File | Why it lives there |
|---|---|
| `.github/CODEOWNERS` | GitHub only reads it from the root, `docs/` or `.github/` |
| `.github/pull_request_template.md` | Same three places only |
| `.github/ISSUE_TEMPLATE/` | Issue forms only load from this folder |
| `.github/CONTRIBUTING.md` | GitHub links to it on the new issue and PR pages only from the root, `docs/` or `.github/` |
| `.github/workflows/` | GitHub Actions only runs workflows (and reusable workflows) from here |
| `.github/dependabot.yml` (OPS-11) | Fixed location |
| `/.gitignore`, `/.gitattributes` | Git applies them per folder; only the root copy covers the whole repo |
| `/compose.yaml` (OPS-03) | `docker compose up` looks in the current folder; it will only `include:` files from `devops/compose/` |
