# The worker image: AI's pipeline code (ai/) for the RQ worker that runs it (this file is
# DevOps-owned). Build context: the repo root, filtered by worker.Dockerfile.dockerignore (an
# allow-list next to this file). Used by the `model-init` and `worker` services in compose.yaml:
#   docker compose --profile worker up -d --build
#
# Backend's code is not on main yet (PR #14). When it lands, the worker gets backend/ too (one
# `!backend/...` line in the dockerignore, a COPY, and its locked dependencies), and the real
# command (`rq worker ...`). Its package is `backend.app`, so it does not clash with ai's `core`.
#
# ai/ is NOT pip-installed: its code finds prompts/ and tests/fixtures/ through the ai/ folder
# (Path(__file__).parents[2]), which a wheel would not keep, and an editable install would fetch
# the unpinned build backend (hatchling) at build time. So the ai/ tree is copied as it is and put
# on PYTHONPATH: the same layout as `pip install -e ai`, with nothing built.

# The same base image as api.Dockerfile (the compose CI job checks the two are equal): Python
# 3.11 (>= 3.11.5, which ai/ needs), Debian slim, pinned by digest to an image at least two weeks
# old.
ARG PYTHON_IMAGE=python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

# ---------------------------------------------------------------- dependencies
FROM ${PYTHON_IMAGE} AS deps
# uv, the same version and checksums as api.Dockerfile and CI.
ARG UV_VERSION=0.13.0
ARG UV_SHA256_X86_64=1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154
ARG UV_SHA256_AARCH64=3ccfb6af6e242433eb552f7d9676abd5412c6595c497e990d9c8cb7b5bd4d2c3
RUN set -eu; \
    arch="$(uname -m)"; \
    case "${arch}" in \
      x86_64) sha="${UV_SHA256_X86_64}" ;; \
      aarch64) sha="${UV_SHA256_AARCH64}" ;; \
      *) echo "unsupported architecture ${arch}" >&2; exit 1 ;; \
    esac; \
    name="uv-${arch}-unknown-linux-gnu"; \
    python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/uv.tar.gz')" \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${name}.tar.gz"; \
    echo "${sha}  /tmp/uv.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/uv.tar.gz -C /usr/local/bin --strip-components=1 "${name}/uv"; \
    rm /tmp/uv.tar.gz; \
    uv --version
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
# AI's locked dependencies, the same set as `uv sync --locked --extra pgvector` (pgvector: the
# worker reads DE's knowledge view), installed from a hash-checked requirements export:
#   uv export --locked --no-emit-project  ->  pip install --require-hashes --no-deps  ->  pip check
WORKDIR /src/ai
COPY ai/pyproject.toml ai/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv set -eu; \
    uv export --locked --no-dev --no-emit-project --extra pgvector \
      --format requirements-txt --output-file /tmp/ai-requirements.txt; \
    uv venv /app/.venv --python /usr/local/bin/python; \
    uv pip install --python /app/.venv/bin/python --require-hashes --no-deps \
      --requirement /tmp/ai-requirements.txt; \
    uv pip check --python /app/.venv/bin/python

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONPATH=/app/ai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # The pinned embedding model lives in the `models` volume (written only by model-init).
    SKILLFORGE_MODEL_CACHE=/models \
    # LiteLLM must not download its price map at import (AI review F17; ai/core sets it too).
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    # Hugging Face's download cache (xet). The app user has no home folder, so the default
    # (~/.cache/huggingface) is not writable; the model itself goes to /models, not here.
    HF_HOME=/tmp/huggingface
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    # Owned by app, so an empty named volume mounted here takes that owner on its first mount and
    # model-init (non-root) can write the model into it. Workers mount it read-only.
    && mkdir /models \
    && chown app:app /models
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
# Read-only for the app user: the worker writes nothing to its own files.
COPY ai /app/ai
COPY devops/docker/worker_check.py /app/devops/worker_check.py
# Exports OPENROUTER_API_KEY from the compose secret /run/secrets/openrouter_api_key, if there is
# one, then runs the command: the key stays out of the container's configuration (docker inspect).
COPY --chmod=0555 devops/docker/worker-entrypoint.sh /app/devops/worker-entrypoint.sh
USER app
ENTRYPOINT ["/app/devops/worker-entrypoint.sh"]
# Placeholder until Backend's worker exists: checks the model offline, then waits.
CMD ["python", "/app/devops/worker_check.py"]
