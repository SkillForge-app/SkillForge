# Contributing to SkillForge

How we work in this repository. If something here is unclear, ask in the DevOps channel before you push.

## Where your code goes

Each department has one folder at the root of the repo. Only change your own department's folder.

| Folder | Department | What goes there |
|---|---|---|
| `ai/` | AI | SkillSpec, LLM gateway, prompts, analysis, knowledge, agents, evaluation |
| `backend/` | Backend | API, workers, compilers and templates, CLI, app database migrations |
| `frontend/` | Frontend | The website |
| `data/` | Data Engineering | Crawler, processing pipeline, knowledge database (`data/db/`), datasets |
| `devops/` | DevOps | Docker, Terraform, scripts, GitHub settings |
| `.github/` | DevOps | Files GitHub needs (CODEOWNERS, templates, CI workflows) |
| `docs/` | Everyone | Shared documentation |

The department plans call some of these `apps/api`, `apps/web` and `core/`. In this repo they are `backend/`,
`frontend/` and `ai/core/`.

## Branches

Every department has **one branch**. Work only on your department's branch. You don't need personal or task
branches.

| Department | Branch |
|---|---|
| AI | `AI` |
| Backend | `Backend` |
| Data Engineering | `Data-Engineering` |
| DevOps | `DevOps` |
| Frontend | `Frontend` |

`main` is protected. Nobody can push to it directly. Code reaches `main` only through a pull request.

## Daily workflow

Replace `<your-branch>` with your department's branch, e.g. `Backend`.

**1. Before you start**, get your teammates' latest work:

```
git switch <your-branch>
git pull origin <your-branch>
```

**2. While you work**, commit and push to your branch as often as you like:

```
git add <files>
git commit -m "BE-05: add skill request endpoint"
git push origin <your-branch>
```

**3. When a task is done**, open a pull request on GitHub:
- From `<your-branch>` into `main`.
- Fill in the template: task ID, Definition of Done, contract change.
- GitHub asks your department to review automatically.

**4. To merge**, once it is approved, click **Create a merge commit**. It is the only merge option. Squash and rebase
are turned off, because they would make step 5 conflict.

**5. After it merges**, bring `main` back into your branch:

```
git switch <your-branch>
git pull origin main
git push origin <your-branch>
```

That's all. You never need `git reset`, `git push --force` or `git rebase`.

If `git pull` reports a conflict, stop and ask your department lead or DevOps. Don't delete files to make it go away.

## Who must approve

The file `.github/CODEOWNERS` decides who must approve a pull request into `main`:
- Changes in your department's folder need one approval from **your department** (not from yourself).
- If you change another department's folder, that department must approve too.
- Repo-wide files (`.gitignore`, `.gitattributes`, `LICENSE`) need DevOps approval.
- When you push new commits, earlier approvals are cleared, so ask for a new review.
- All review comments must be resolved before merging.
- The lead (zaid2658a-debug) is a member of every department team, so the lead's approval counts as that
  department's approval when a department reviewer isn't available.

### Contract changes

Some files are shared contracts. If your PR changes one, tick **Contract change** in the template, add the
`contract-change` label, and ask the consumers to review as well:

For these files GitHub enforces it: the PR can't merge until every listed team has approved (see `ruleset-main.json`):
`ai/core/spec/schema.json`, `ai/core/spec/models.py`, `ai/core/analysis/analyzed_request.schema.json` (AI, Backend,
Frontend), `ai/core/pipeline/interface.py` (AI, Backend), `data/db/knowledge_views.sql` (Data Engineering, AI).

| Contract | Owner | Consumers |
|---|---|---|
| SkillSpec schema (Python models + `schema.json`) | AI | Backend, Frontend |
| OpenAPI contract | Backend | Frontend |
| Database schemas and migrations | Backend (app data), Data Engineering (knowledge data) | All |
| Environment variables, Docker images, local setup | DevOps | All |
| AI pipeline interface (functions the worker calls) | AI | Backend |
| Knowledge retrieval (query + domain → passages with sources) | Data Engineering + AI | AI |
| Analytics event schema | Data Engineering | Frontend, Backend |

**The lead's approval doesn't replace the consumer teams.** The lead is in every team, so on GitHub one approval
from the lead counts for all of them. On a contract change, still request review from every consumer team. The
lead approves alone only when the change is urgent, and then says so in the PR: why it's urgent, and that the lead's
approval stands in for the consumer teams.

## Issues

Every task from the department plans gets one issue, made with the **Task** form. Put the task ID at the start of
the title (`AI-10: Extraction and NLP rules`). Write `Closes #<issue>` in the pull request, and the issue closes when
the PR merges.

## Commit messages and PR titles

- Start with the task ID, then say what you did: `DE-01: add sources table`.
- Work that isn't a task starts with `fix:`, `docs:` or `chore:` instead: `docs: fix setup steps`.
- Keep the first line short (72 characters or fewer).
- The PR title follows the same rule. It becomes the merge commit's title on `main`.

## Never

- Never force-push or delete a department branch (GitHub blocks it).
- Never commit secrets, API keys, `.env` files, personal data or large data files. GitHub's push protection blocks
  known secret formats, but it can't catch everything.

## Owner bypass (DevOps only)

The organization owner can merge a pull request without the required approval. This is allowed only when **all**
of these are true:

1. It is the owner's own pull request.
2. It only changes `devops/` or `.github/`.
3. Nobody has answered the review request within 24 hours.

The bypass is never used to skip another department's review. Every use is ticked in the PR template, and GitHub
records it under Settings → Rules → Insights.
