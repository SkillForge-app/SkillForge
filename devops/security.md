# Security scanning (OPS-11)

What checks the repository for security problems, where the results show up, and who handles them.

## What runs

| Check | What it looks for | When | Blocks a merge? |
|---|---|---|---|
| gitleaks (`ci.yml`, `secret-scan` job) | Secrets in the history being merged (`main` + the PR); config `devops/ci/gitleaks.toml`; checked non-secrets in `devops/ci/gitleaksignore` | Every PR and push to `main` | **Yes**, through `ci-ok` |
| GitHub secret scanning + push protection | Known secret formats; push protection rejects a push that contains one | Every push | Push protection blocks the push |
| CodeQL (`.github/workflows/codeql.yml`) | Code weaknesses in Python, JavaScript/TypeScript and the workflows themselves | PRs to `main`, pushes to `main`, Mondays | No |
| Trivy (`.github/workflows/trivy.yml`) | Known HIGH/CRITICAL vulnerabilities in lock files (`ai/uv.lock`, …) and misconfigurations (Dockerfiles, compose, Terraform) | PRs to `main`, pushes to `main`, Mondays | No |
| Dependabot alerts | Known vulnerabilities in dependencies | When an advisory is published | No |
| Dependabot updates (`.github/dependabot.yml`) | Version updates (Mondays, grouped, at most 3 open PRs per ecosystem, releases ≥ 14 days old) and security updates (when an alert opens) | Weekly / on alert | Their PRs need `ci-ok` and a review, like any PR |

`ci-ok` is the only required check. CodeQL and Trivy report and never block, so a new finding doesn't stop the team.
CodeQL scans only the languages present in the repo: today `actions`; Python joins when `ai/` is on `main`, and
JavaScript/TypeScript when `frontend/` has code.

## Where results show up

- **Security tab → Code scanning:** CodeQL (`/language:…`) and Trivy (`trivy`) findings, per branch and per PR.
- **Security tab → Dependabot:** vulnerable dependencies. Dependabot opens fix PRs labelled `dependencies`.
- **Security tab → Secret scanning:** secrets GitHub found; push-protection bypasses are listed there too.
- **PR checks:** gitleaks fails `ci-ok`. CodeQL and Trivy add annotations on the PR's changed lines.

## Who handles alerts

The DevOps lead (`zaid2658a-debug`) watches the Security tab and triages:

- **Critical and high:** within a week. Fix it, or dismiss it with a reason (false positive, used in tests, not
  reachable). The owning department fixes code in its own folder.
- **A real secret:** rotate it first, with whoever owns the key. Removing it from Git does not make it safe again:
  the repo is public and the history is copied. Then remove it.
- **Dependabot PRs:** reviewed by the owning department (CODEOWNERS), like any PR. The lead can approve them
  because Dependabot, not the lead, is the author.

## Out of scope until deploy

- **HTTPS/TLS, CORS and security headers** need a running service: OPS-16 (production environment).
- **Container image scanning** comes with the Docker image builds in OPS-03 (Trivy on each image).

## Known limits

- **`ai/` updates and `exclude-newer`:** `ai/pyproject.toml` only allows releases older than its `[tool.uv]
  exclude-newer` date. A Dependabot update (or security fix) newer than that date cannot be locked, so its PR fails
  until AI moves the date on purpose. AI owns that file.
- **backend/, frontend/, data/:** Dependabot entries are written but commented out in `.github/dependabot.yml`
  until each folder is on `main` and its package manager is known.
