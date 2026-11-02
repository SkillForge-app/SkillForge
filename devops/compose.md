# Local stack (OPS-03)

One command starts the shared services every department develops against. It's defined in the root
`compose.yaml`:

| Service | What | On your machine | From another container |
|---|---|---|---|
| `postgres` | PostgreSQL 18 + pgvector 0.8.6 | `127.0.0.1:5433` | `postgres:5432` |
| `redis` | Redis 8.8 | `127.0.0.1:6379` | `redis:6379` |
| `web` (only with `--profile web`) | The Next.js app from `frontend/` | `http://127.0.0.1:3000` | `web:3000` |

`api` and `worker` are commented-out placeholders in `compose.yaml`. Each one has a TODO saying what Backend
still needs to decide. `web` is described in [Web app](#web-app).

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

## Images
The postgres and redis images and the web image's Node base are pinned by digest (the multi-arch index,
amd64 + arm64), each to a release at least two weeks old. To update one:
1. Pick a tag at least 14 days old.
2. Take its digest from Docker Hub (`docker buildx imagetools inspect <image>:<tag>`).
3. Change `compose.yaml`; for pgvector, change `.github/workflows/data.yml` too. For Node, change
   `NODE_IMAGE` in `devops/docker/web.Dockerfile`, in step with `frontend/.nvmrc`.
4. Open a PR. The `compose` workflow (`.github/workflows/compose.yml`) starts the stack and checks it. It isn't
   a required check.

To test another branch's `data/db/` or `frontend/` (e.g. before Data Engineering or Frontend merges):
Actions → compose → Run workflow, with `data-ref` or `frontend-ref` set to the branch. The `web` job builds
the image, starts it, and checks three things:
- the app answers;
- it doesn't run as root;
- the API URL is in the browser code.

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
