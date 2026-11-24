# Local stack (OPS-03)

One command starts the shared services every department develops against. It's defined in the root
`compose.yaml`:

| Service | What | On your machine | From another container |
|---|---|---|---|
| `postgres` | PostgreSQL 18 + pgvector 0.8.6 | `127.0.0.1:5433` | `postgres:5432` |
| `redis` | Redis 8.8 | `127.0.0.1:6379` | `redis:6379` |
| `web` (only with `--profile web`) | The Next.js app from `frontend/` | `http://127.0.0.1:3000` | `web:3000` |
| `api` (only with `--profile api`) | The FastAPI app from `backend/`, after `migrate` | `http://127.0.0.1:8000` | `api:8000` |
| `model-init`, `worker` (only with `--profile worker`) | The embedding-model cache, and a placeholder worker | (no ports) | (no ports) |

`web` is described in [Web app](#web-app), `api` and `migrate` in [API](#api), and `model-init` and `worker` in
[Worker and model cache](#worker-and-model-cache). The worker is a placeholder until Backend's worker exists.

The ports listen on `127.0.0.1` only, so nothing is reachable from your network. All values in `.env.example`
are for local development only; staging and production get theirs from the secret store.

## Prerequisites
Docker Desktop (Windows, macOS) or Docker Engine (Linux), with Compose v2: `docker compose version`.

## Start
From the repo root:

```
cp .env.example .env      # once; .env is gitignored
docker compose up -d      # starts postgres and redis, in the background
docker compose ps         # both should say "healthy" after a few seconds
```

Without `.env`, compose stops with `POSTGRES_PASSWORD ... copy .env.example to .env`. Change the ports in `.env`
if 5433 or 6379 are taken.

**On the first start** (an empty data volume), postgres runs `devops/compose/postgres-initdb/10-skillforge.sh`:
1. It enables `vector` (pgvector). This always happens.
2. If `data/db/` is checked out, it applies Data Engineering's SQL in their order: `data/db/init/*.sql`,
   `schema-draft.sql`, `knowledge_views.sql`, `roles-local.sql`.
   - That gives the `knowledge` schema, the `knowledge.knowledge_chunks` view and the read-only role
     `skillforge_ai_reader`.
   - On a branch without `data/`, Docker creates an empty `data/db/` folder (Git ignores it), and only step 1
     runs.

It doesn't run again on later starts. To pick up new SQL, reset the data (below).

## Stop

```
docker compose stop       # stop; keep containers and data
docker compose down       # remove the containers; keep the data volumes
```

## Reset the data
Needed after Data Engineering changes anything in `data/db/`, or after a failed first start:

```
docker compose down -v    # removes the containers AND the volumes (skillforge_pgdata, skillforge_redisdata)
docker compose up -d      # fresh database, init runs again
```

This deletes everything in the local database and Redis. Nothing outside your machine is affected.

## Connect
`<POSTGRES_PASSWORD>` is the value in your `.env` (`skillforge_dev` unless you changed it).

| Who | Setting |
|---|---|
| Data Engineering (owner of the `knowledge` schema) | `DATABASE_URL=postgresql+psycopg://skillforge:<POSTGRES_PASSWORD>@localhost:5433/skillforge`. The same as `data/.env.example` |
| AI, reading the knowledge store (read-only, like production) | `SKILLFORGE_VECTOR_STORE=pgvector`<br>`SKILLFORGE_PGVECTOR_DSN=postgresql://skillforge_ai_reader:<password>@localhost:5433/skillforge` (the local password is in `data/db/roles-local.sql`)<br>`SKILLFORGE_PGVECTOR_TABLE=knowledge.knowledge_chunks` |
| AI tests (`pytest -m pgvector`, which create `public.skillforge_test_*` tables) | `SKILLFORGE_PGVECTOR_DSN=postgresql://skillforge:<POSTGRES_PASSWORD>@localhost:5433/skillforge` |
| Backend (later, the `api` service) | `DATABASE_URL=postgresql+<driver>://skillforge:<POSTGRES_PASSWORD>@localhost:5433/skillforge` |
| Anyone, Redis | `REDIS_URL=redis://localhost:6379/0` |

From another compose service, use the hosts `postgres:5432` and `redis:6379` instead of `localhost`.

A psql shell, without installing anything:

```
docker compose exec postgres psql -U skillforge -d skillforge
docker compose exec redis redis-cli
```

## Troubleshooting
- **`container name "/skillforge-postgres" is already in use`:** another container has that name. Find it with
  `docker ps -a --filter name=skillforge-postgres`, remove it with `docker rm -f skillforge-postgres` (this
  deletes the container, not the `skillforge_pgdata` volume), then run `docker compose up -d` again.
- **Port 5433, 6379 or 3000 is already allocated:** something else on your machine uses it, e.g. a local
  PostgreSQL. Stop it, or pick another port in `.env` (`POSTGRES_PORT`, `REDIS_PORT`, `WEB_PORT`).
- **postgres keeps restarting or never becomes healthy:** read `docker compose logs postgres`. A `skillforge:`
  line shows which `data/db/` file failed. Fix it (or ask Data Engineering), then reset the data.
- **`POSTGRES_PASSWORD` required:** you have no `.env`. Run `cp .env.example .env`.

## Web app
The `web` service builds Frontend's Next.js app (`frontend/`) with `devops/docker/web.Dockerfile`. It's in the
`web` profile, so a plain `docker compose up` doesn't build it and still works on branches without
`frontend/`.

```
docker compose --profile web up -d --build    # build the image and start it (plus postgres and redis)
docker compose --profile web logs -f web
docker compose --profile web down             # stop it
```

- **Open** `http://127.0.0.1:3000` (change the port with `WEB_PORT` in `.env`).
- **Rebuild after a frontend change** (`--build`): the image holds a production build, not the dev server. For
  fast edit-and-reload work, Frontend's `npm run dev` in `frontend/` is still the tool.
- **`NEXT_PUBLIC_API_BASE_URL`** (in `.env`, default `http://localhost:8000`):
  - It's the API URL the **browser** calls, so it's a URL on your machine, not a service name.
  - Next.js bakes it into the browser code at build time, so changing it needs a rebuild.
- **The image** (`skillforge-web:local`):
  - three stages: dependencies, build, runtime;
  - it runs Frontend's standalone Next.js server (`output: "standalone"`, the server that `npm run start`
    launches) as the non-root `node` user, on port 3000;
  - the standalone server doesn't serve `.next/static` or `public/` on its own, so the image copies them next
    to it;
  - local `.env*` files are never copied in (`devops/docker/web.Dockerfile.dockerignore`).

## API
The `api` service runs Backend's FastAPI app (`backend/`), built with `devops/docker/api.Dockerfile`. It's in
the `api` profile, so a plain `docker compose up` doesn't build it.

```
docker compose --profile api up -d --build                  # migrate, then the API (plus postgres and redis)
docker compose --profile api --profile web up -d --build    # the API and the web app together
docker compose --profile api logs migrate api
```

- **Migrations:** `migrate` is a one-shot service. It runs `alembic -c backend/alembic.ini upgrade head` and
  exits. `api` starts only after it exits with 0, and it runs again on every `up`, so the database is always
  at the latest migration. A failed migration leaves `api` stopped: read `docker compose --profile api logs
  migrate`.
- **Open** `http://127.0.0.1:8000/docs` (change the port with `API_PORT` in `.env`).
- **Rebuild after a backend change** (`--build`): the image holds the code, not a live mount.
- **Settings in the containers:**
  - `DATABASE_URL=postgresql+psycopg://skillforge:<POSTGRES_PASSWORD>@postgres:5432/skillforge` (SQLAlchemy
    with psycopg 3);
  - `REDIS_URL=redis://redis:6379/0`.
  - Backend's tables live in `public`, next to Data Engineering's `knowledge` schema.
- **What the image needs from `backend/`:**
  - `pyproject.toml` + `uv.lock` (installed with uv, Python 3.11);
  - `alembic.ini` (inside `backend/`);
  - `app/main.py`.
  - The code is copied to `/app/backend` and imported as `backend.app…`. It runs as the non-root user `app`
    (uid 10001), and local `.env*` files and `tests/` are never copied in.
- **The worker:** see [Worker and model cache](#worker-and-model-cache). Backend's package is `backend.app`,
  so it doesn't clash with AI's top-level `core`.

## Worker and model cache
The worker will run the AI pipeline (`ai/core/pipeline/interface.py`) for Backend's queue. AI's retrieval embeds
queries with a local model (`local/BAAI/bge-small-en-v1.5`, about 66 MB), pinned in `ai/core/llm/models.yaml` by
repo, revision, file and sha256.

```
docker compose --profile worker up -d --build       # model-init fills the cache once, then the worker starts
docker compose --profile worker logs model-init worker
docker compose --profile worker run --rm model-init  # check (or fill) the cache by hand
```

- **`model-init`** is a one-shot service. It runs `python -m core.llm.local_embed download` into the `models`
  volume (`skillforge_models`, mounted at `SKILLFORGE_MODEL_CACHE=/models`).
  - **It's idempotent:** when the pinned file is already there and its sha256 matches, it downloads nothing,
    so later runs take a second and need no network.
  - **It's the only writer of `models`.** A file that doesn't match its sha256 makes it fail ("delete the folder
    and download again"), and then no worker starts.
- **`worker`** starts only after `model-init` exits with 0. It mounts `models` **read-only** with
  `HF_HUB_OFFLINE=1`, so a missing model fails loudly instead of downloading at runtime.
  - **For now it's a placeholder** (`devops/docker/worker_check.py`): it checks that the model is there, embeds
    one sentence offline, logs `worker placeholder: model ok (…, 384 dims, offline)`, and waits. With an empty
    volume it exits 1 with a message that names model-init.
  - **When Backend's worker lands,** the service moves into the `api` profile and runs
    `rq worker --with-scheduler --url redis://redis:6379/0 skills`. It gets `env_file: ai/.env` (provider keys,
    never in `compose.yaml`), `DATABASE_URL`, `REDIS_URL`, `SKILLFORGE_VECTOR_STORE=pgvector` and
    `SKILLFORGE_PGVECTOR_DSN` (DE's read-only role), and waits for `migrate` and `redis`. The model check can stay
    as a startup step.
- **For Data Engineering:** when DE's workers join compose, they mount the **same `models` volume read-only**,
  with `HF_HUB_OFFLINE=1` and `SKILLFORGE_MODEL_CACHE=/models`. They never download the model themselves:
  `model-init` is the only writer.
- **The image** (`devops/docker/worker.Dockerfile`, built from the repo root through an allow-list,
  `worker.Dockerfile.dockerignore`):
  - **Base:** the same Python base and uv as the API image.
  - **AI's dependencies:** installed the locked way. That's `uv export --locked --no-emit-project --extra
    pgvector` from `ai/uv.lock`, then a hash-checked install with `--no-deps`, then `pip check`.
  - **AI's code:** copied as the `ai/` tree and put on `PYTHONPATH`, the same layout as `pip install -e ai`.
    It finds `prompts/` through that folder, which a wheel wouldn't keep, and nothing has to be built.
  - **Never in the image:** no `.env`, venv or model is ever copied in. It runs as the non-root user `app`
    (uid 10001).
- **A new model pin** (a new revision or sha256 in `models.yaml`) goes into a new folder in the same volume: run
  `model-init` again. The old folder can go once no worker uses it.
- **Reset the cache:** `docker compose --profile worker down`, `docker volume rm skillforge_models`, then `up`
  again.

## Images
The postgres and redis images, the web image's Node base and the api image's Python base are pinned by digest (the multi-arch index,
amd64 + arm64), each to a release at least two weeks old. To update one:
1. Pick a tag at least 14 days old.
2. Take its digest from Docker Hub (`docker buildx imagetools inspect <image>:<tag>`).
3. Change `compose.yaml`; for pgvector, change `.github/workflows/data.yml` too. For Node, change
   `NODE_IMAGE` in `devops/docker/web.Dockerfile`, in step with `frontend/.nvmrc`. For Python, change
   `PYTHON_IMAGE` in `devops/docker/api.Dockerfile` **and** `devops/docker/worker.Dockerfile` (the two must be
   equal; uv's version and sha256s are in both).
4. Open a PR. The `compose` workflow (`.github/workflows/compose.yml`) starts the stack and checks it. It isn't
   a required check.

To test another branch's `data/db/`, `frontend/` or `backend/` (e.g. before Data Engineering, Frontend or
Backend merges): Actions → compose → Run workflow, with `data-ref`, `frontend-ref` or `backend-ref` set to
the branch. The `api` job builds the image, runs the migration, and checks that `alembic_version` is set,
`/openapi.json` answers and it doesn't run as root. The `web` job builds
the image, starts it, and checks three things:
- the app answers;
- it doesn't run as root;
- the API URL is in the browser code.

The `worker` job builds the worker image from `ai/`. It also runs when `ai/uv.lock`, `ai/pyproject.toml` or the model pin
changes. It checks:
- the base image matches the API image's, pinned by digest;
- it doesn't run as root and holds no `.env`;
- `model-init` fills the cache, and a second run with no network downloads nothing;
- the worker loads the model with no network and a read-only cache;
- an empty cache fails with the model-init message.

## For Data Engineering
This stack is the one local database for every department. Your `DATABASE_URL` (`data/.env.example`) points
at it.
- **First start:**
  - Your `data/db/` SQL is applied in place: `init/*.sql`, `schema-draft.sql`, `knowledge_views.sql`,
    `roles-local.sql`.
  - You don't apply anything by hand.
- **After changing that SQL:** reset the data (`docker compose down -v`, then `up -d`), because the init runs
  only on an empty volume.
- **Test a SQL change before it merges:** run the `compose` workflow with `data-ref` set to your branch (see
  Images).
- **Tell DevOps when the names or the order of the `data/db/` files change:** the init script lists them.
- **Once you have migrations:** give us one entry point (e.g. `data/db/local-init.sql`), and the script will
  run that instead of the list.
