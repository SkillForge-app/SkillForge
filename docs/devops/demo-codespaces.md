# The demo in GitHub Codespaces

We have no cloud staging (the Terraform in `devops/terraform/` on `OPS-04-staging` stays unapplied). The demo
runs in a **GitHub Codespace**: the same root `compose.yaml` the team uses locally, inside a cloud VM that
GitHub gives every account for free, for a limited number of hours a month.

| Piece | What runs in the demo |
|---|---|
| postgres + redis | The local stack (pgvector, Data Engineering's `data/db/` SQL on the first start) |
| migrate, api | Backend's FastAPI app and its Alembic migrations, with one seeded project |
| model-init, worker | The pinned embedding model cache, and the **placeholder** worker (it checks the model offline, then waits) |
| web | Frontend's Next.js app. Its pages still show **mock data**: they don't call the API yet |

`main` has no `backend/` or `frontend/` yet, so the demo builds them from the `Backend` and `Frontend` branches
(see [Which code runs](#which-code-runs)). Once they merge into `main`, the copies on the branch are used instead.

Files: `.devcontainer/devcontainer.json`, `devops/demo/` (`demo.sh`, `post-create.sh`, `fetch-sources.sh`,
`seed.py`, `compose.demo.yaml`). The local stack itself is described in `devops/compose.md`.

---

## 1. Start

### Once: the OpenRouter key (optional)
Without a key the demo runs in **fake LLM mode** (below), which is fine for rehearsals.

1. In OpenRouter, create a **separate key just for the demo** with a **small credit limit** (for example $3).
   Never use the main team key here.
2. On github.com: your avatar → **Settings → Codespaces → Secrets → New secret**.
   - Name: `OPENROUTER_API_KEY`, Value: the demo key.
   - Repository access: `SkillForge-app/SkillForge`.
3. The secret lives only in GitHub. It is never in a file in the repo or the codespace, and `demo.sh` never
   prints it (only `set` / `not set`).

A new or changed secret reaches a codespace only after the codespace **restarts** (stop it, then open it again).

### Create the codespace
Your own settings first (github.com → Settings → Codespaces): **Default idle timeout 20 minutes**, **Default
retention period 7 days**. Then either:

- **On github.com:** the repo → **Code → Codespaces → ⋯ → New with options**. Pick the branch, machine type
  **2-core**, then **Create codespace**.
- **With the GitHub CLI:**
  ```
  gh codespace create -R SkillForge-app/SkillForge -b <branch> -m basicLinux32gb --idle-timeout 20m --retention-period 168h
  ```
  (`gh codespace create --help` lists the flags; the machine picker shows the exact machine names.)

**The first creation is slow, so do it the day before, not on demo day.** It hasn't been timed in a real codespace
yet; on a slow home connection it took about an hour (see [Measured](#measured)). `post-create.sh` runs once,
on its own, and does all the slow work:
1. installs uv (the same version and sha256 as the images);
2. exports `backend/` and `frontend/` from their branches into `.demo/src/` (gitignored);
3. builds the api, worker and web images;
4. downloads the embedding model **once** into the `skillforge_models` volume, checked against the sha256 in
   `ai/core/llm/models.yaml`.

Its log is in the terminal tab "Creation log" (or **View Creation Log** from the command palette). Later starts
of the same codespace do none of this: images, the model and the database are kept while the codespace exists.

### Which machine, and what it costs
- **The 2-core machine (8 GB RAM, 32 GB disk) is enough.** The stack's containers use about **0.3 GB RAM**, so
  about **1.3 GB** with the editor server; the first build peaks higher. Disk: about 11 GB of the 32 (see
  [Measured](#measured)).
- **Who pays:** the person who creates the codespace, from their **personal free quota**:
  - The repo is public, and GitHub organization plans include no Codespaces quota. Our org has no Codespaces
    billing, so GitHub bills the user's own account.
  - With no payment method on that account, usage is **blocked** at the end of the quota. There is never a
    surprise bill.
- **The free quota (GitHub Free):** 120 core-hours and 15 GB-month of storage a month. That's **60 hours of a
  running 2-core codespace**. GitHub Pro: 180 core-hours (90 hours), 20 GB-month.
- **Storage is billed while the codespace exists, even when stopped:** about 11 GB for this one, so a week
  costs ≈2.5 of the 15 GB-month. `docker builder prune` frees about 4.5 GB of that.
- **Only the presenter needs a codespace.** Each teammate who opens one spends their own quota.

---

## 2. Run

In the codespace's terminal, from the repo root:

```
bash devops/demo/demo.sh
```

It creates `.env` from `.env.example` **only if it's missing** (local placeholders only; it never overwrites
yours, and it never reads it for secrets). Then it fetches the sources, starts everything in order (postgres and
redis → migrate → api; model-init → worker; web), seeds the database through the API and prints a table:

```
  SERVICE   STATE DETAIL
  postgres  up    pg_isready ok, on 127.0.0.1:5433 (never forward this port)
  redis     up    PONG, on 127.0.0.1:6379 (never forward this port)
  migrate   done  alembic at 524c2b6b81e5
  api       up    /health ok on 127.0.0.1:8000 (keep this port Private)
  seed      ok    project 'SkillForge demo' exists
  worker    up    placeholder: model ok, offline (the real RQ worker comes after Backend PR #14)
  llm             LLM mode FAKE: no model is called; answers are the canned examples in ai/examples/ (...)
  web       up    HTTP 200 on 127.0.0.1:3000
  backend   src   Backend at a1caf3b86986
  frontend  src   Frontend at e237e042d92b
```

It exits non-zero if anything is down. Other commands:

| Command | What |
|---|---|
| `bash devops/demo/demo.sh status` | The table again |
| `bash devops/demo/demo.sh logs [service]` | The last 200 log lines (`TAIL=500` for more) |
| `bash devops/demo/demo.sh stop` | Stops the containers; keeps the data and the model |
| `bash devops/demo/demo.sh reset` | Deletes the containers **and volumes** (asks first); the next run downloads the model again |

### Fake or live LLM mode
| | When | What happens |
|---|---|---|
| **FAKE** | No `OPENROUTER_API_KEY` in the codespace, or `DEMO_LLM_MODE=fake` | `SKILLFORGE_PIPELINE=fake` and `SKILLFORGE_LLM_BACKEND=fake`: AI's FakePipeline answers with the canned examples in `ai/examples/`. No model is called, nothing costs money, and the key (if any) is not passed on |
| **LIVE** | The secret is set (and `DEMO_LLM_MODE` isn't `fake`) | OpenRouter, billed to the demo key. The key goes to the **worker only**, as a compose secret: the worker's entrypoint reads it from `/run/secrets/openrouter_api_key`, so it is not in the container's configuration (`docker inspect`) |

The mode is shown in three places: the banner at the top of `demo.sh`, the `llm` row of the table, and the
worker's log (`worker: LLM mode ...`). The worker log also lists the warnings of AI's own startup check
(`core.ops` check), which name variables, never values.

- **Force fake mode for a rehearsal, even with the key set:** `DEMO_LLM_MODE=fake bash devops/demo/demo.sh`.
- **Live mode that fails if the key is missing:** `DEMO_LLM_MODE=live`.

> Today no service calls the LLM yet in either mode: the worker is still the placeholder, and the API image has no
> `ai/`. The switch is wired and logged so the real worker picks it up when it lands (see [Follow-ups](#follow-ups)).

### Which code runs
| Variable | Default | Takes |
|---|---|---|
| `DEMO_BACKEND_REF` | `Backend` | a branch name or a **full 40-character** commit SHA |
| `DEMO_FRONTEND_REF` | `Frontend` | the same |

- **Example:** `DEMO_BACKEND_REF=a1caf3b8698670895ef067e73dc480a951a489b7 bash devops/demo/demo.sh`.
- **How the code gets there:** `fetch-sources.sh` exports the folder with `git archive` into `.demo/src/`. The
  working tree and the index are never touched, and the table shows the commit used.
- **On a full clone (a laptop) it never runs a shallow fetch.** It uses `--depth=1` only when the repository
  already is shallow (a CI checkout, or a codespace if its clone is shallow).
- **If a fetch fails** (no network) and an earlier export of the **same** ref exists, that export is used, with a
  warning. Another branch or SHA never stands in: the script stops instead. A pinned SHA that is already in the
  repository needs no network at all.

---

## 3. Make the frontend port public (demo day only)

Every forwarded port starts **Private**: only you, signed in to GitHub, can open it. `devcontainer.json`
**can't** change that. Its `portsAttributes` only knows `label`, `protocol`, `onAutoForward`,
`requireLocalPort` and `elevateIfNeeded`, so visibility is always set by hand.

**Only port 3000 (web) may be made Public. 8000 (api), 5433 (postgres) and 6379 (redis) always stay Private.**

- **In VS Code (desktop or browser):** open the **Ports** tab of the panel, right-click port **3000** → **Port
  Visibility** → **Public**.
- **With the GitHub CLI (from your laptop):**
  ```
  gh codespace ports -c <codespace-name>                       # list ports and their visibility
  gh codespace ports visibility 3000:public -c <codespace-name>
  ```
- **The link to share:** `https://<codespace-name>-3000.app.github.dev`. `demo.sh status` prints it.

Things to know:
- **A Public URL needs no sign-in.** Anyone with the link can open it while the codespace runs.
- **Changing a Public port's protocol to HTTPS turns it back to Private.**
- **"Private to Organization" needs GitHub Team or Enterprise**, so it isn't available to us.
- **GitHub doesn't document whether a Public setting survives a restart.** Check the Ports tab after every start.

**Undo right after the demo:** `gh codespace ports visibility 3000:private -c <codespace-name>` (or the Ports
tab → Private).

---

## 4. Stop

1. Set port 3000 back to **Private** (above).
2. `bash devops/demo/demo.sh stop`. This is optional: stopping the codespace stops everything anyway.
3. Stop the codespace: github.com/codespaces → ⋯ → **Stop codespace**, or `gh codespace stop -c <codespace-name>`.
   It also stops on its own after the idle timeout.

What a stopped codespace costs and keeps:
- **It uses no compute hours**, only storage.
- **It is deleted after the retention period (7 days).** Unpushed changes are deleted with it.
- **Demo week:** github.com/codespaces → ⋯ → **Keep codespace**, so the prepared one isn't deleted.

---

## 5. Demo day

**The day before:**
1. Pin both sources to known-good commits. Find them with `git ls-remote origin Backend Frontend`, or from
   the table of a good run.
2. Rehearse with **exactly** those:
   ```
   export DEMO_BACKEND_REF=<full sha> DEMO_FRONTEND_REF=<full sha>
   bash devops/demo/demo.sh
   ```
3. Write the two SHAs down, and use the same `export` line on the day.

**The key and the public window:**
- **Use the separate demo key with its small credit limit, never the main key.** Its limit caps what a mistake can cost.
- **Keep the public window short.** Today the web pages don't call the API, so a Public port 3000 exposes only
  the mock pages. Once Frontend wires the API, a Public port 3000 in **live** mode lets anyone with the link make
  model calls on that key. Make port 3000 Public just before you present, and Private right after.

**Idle timeout:**
- **The codespace stops after the idle timeout without terminal or editor input.** GitHub doesn't document
  whether visits to a Public port count as activity.
- **On the day, either touch the terminal now and then, or create the demo codespace with
  `--idle-timeout 60m`.** A codespace also never runs longer than 12 hours in one go.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Docker is not answering` | Right after a start the daemon needs up to a minute. Run again. If post-create failed on this, run `bash devops/demo/demo.sh prepare` |
| `.env contains OPENROUTER_API_KEY` | Remove that line. Keys never go in files; the key comes only from the Codespaces secret |
| The mode is FAKE although you added the secret | Secrets reach a codespace only on start: stop the codespace, open it again, run `demo.sh` |
| `migrate FAIL` | `bash devops/demo/demo.sh logs migrate`. A migration that doesn't fit the database: `demo.sh reset`, then run again |
| `worker DOWN`, "not ready in /models" or a sha256 mismatch | The model cache is missing or damaged: `docker volume rm skillforge_models`, then `bash devops/demo/demo.sh prepare` |
| `could not fetch Backend` | No network, or the branch doesn't exist. Check `git ls-remote origin Backend`; pin a SHA that's already fetched |
| `looks like a short SHA` | Use the full 40-character SHA: `git rev-parse <short>` |
| The Public link asks for a GitHub sign-in | Port 3000 is still Private (or turned Private when its protocol changed). Set it again |
| "port is already allocated" (laptop) | Another app uses the port. Change `WEB_PORT` / `API_PORT` / `POSTGRES_PORT` in `.env` |
| The disk is full | `docker builder prune` (build cache), then `docker image prune` |
| "You've used all of your included usage" | The monthly quota is used up. Wait for the next billing cycle, or run the demo on a laptop (below) |

---

## 7. Fallback: the same compose on a laptop

The same scripts run on a laptop with Docker Desktop (Windows, macOS) or Docker Engine (Linux). On Windows, use
**Git Bash**. From the repo root:

```
bash devops/demo/demo.sh
```

- **The key:** for live mode, set it only in your shell for that run, e.g. `export OPENROUTER_API_KEY=...`
  (never in `.env` or any file). Without it, fake mode.
- **The URLs:** `http://127.0.0.1:3000` (web) and `http://127.0.0.1:8000/docs` (api).
  - Every port listens on 127.0.0.1 only, so nothing is reachable from the network.
  - To show it to the room, share your screen.
- **Ports:** change taken ones in `.env`, e.g. `API_PORT=18000`. `.env` is yours: the script never overwrites it.
- **It shares the local stack's volumes** (the compose project is `skillforge`). So `demo.sh reset` also deletes
  your local development database and model cache.

---

## Measured
Measured on 2026-11-25 with this dev container, run locally (dev container CLI 0.90.0 on Docker Desktop, WSL 2),
the whole stack in fake mode. The numbers come from `docker stats --no-stream` and `docker system df` inside the
dev container. These are not yet numbers from a real codespace: the first real run should replace them.

| Container | RAM, running |
|---|---|
| web (Next.js standalone) | 144 MiB |
| api (uvicorn) | 91 MiB |
| postgres | 40-78 MiB |
| worker (placeholder; the model is loaded only for its check) | 27 MiB |
| redis | 6 MiB |
| **Total** | **≈0.3 GB** |

| Disk | Size |
|---|---|
| The dev container image (Python 3.11, Docker, Node) | 3.4 GB |
| Images inside it (postgres, redis, api, worker, web) | 2.6 GB |
| Build cache | 4.5 GB (`docker builder prune` frees it; later builds then take longer) |
| Volumes (database, redis, model) | 0.13 GB |
| **Total** | **≈10.7 GB** (the storage that is billed while the codespace exists) |

| Time | Measured |
|---|---|
| Image and features, then `post-create.sh` (first creation) | 44 min + 17 min, on a slow home connection with resets. GitHub's network is much faster, so expect well under that; the first real codespace will tell |
| `demo.sh` on a prepared codespace | 204 s (3.4 min) for the first start; about 1 min for a restart |
| `demo.sh` on a laptop, images not built yet | 413 s |

**RAM in a codespace:** add the editor server and the container itself (about 0.8-1 GB), so ≈1.3 GB in use while
the demo runs. That fits easily in the 2-core machine's 8 GB. The first creation peaks higher while `next build`
and the Python installs run.

---

## Follow-ups
- **The end-to-end demo needs three things first:**
  - **Frontend:** the pages still show mock data (`frontend/` last changed Nov 5). They need to call the API
    through a **same-origin proxy**, a Next.js server-side rewrite to `api:8000`, so the API port never has to
    be Public.
  - **Backend PR #14 into `main`.**
  - **The real worker (OPS-03):** a backend+ai image running Backend's RQ worker in place of the placeholder,
    with `ai/examples/` for fake mode (already in the worker image).
- **A UI banner for fake mode** (Frontend). Today the mode is shown in the script's output and the worker's
  log only.
- **A Dependabot `devcontainers` entry**, to keep the feature pins in `.devcontainer/devcontainer.json` fresh.
- **CI:** `.github/workflows/devcontainer.yml` checks the pins, builds the dev container and validates the
  demo's compose files. It runs only when these files change and is not a required check.
