# The API image (OPS-03): FastAPI from backend/ (Backend's code; this file is DevOps-owned).
# Build context: backend/. Used by the `migrate` and `api` services in compose.yaml:
#   docker compose --profile api up -d --build
# api.Dockerfile.dockerignore (next to this file) decides what of backend/ is sent to the build.
#
# Backend's code imports `backend.app...`, so the image keeps that layout: the code is in
# /app/backend and /app is the import root. Dependencies come from backend/pyproject.toml and
# backend/uv.lock (installed with uv, like ai/).

# Python 3.11 (the same as ai/, because the worker will run both), Debian slim, pinned by digest
# (multi-arch index) to an image at least two weeks old.
ARG PYTHON_IMAGE=python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

# ---------------------------------------------------------------- dependencies
FROM ${PYTHON_IMAGE} AS deps
# uv, the same version as CI, from its release tarball checked by sha256 (slim has no curl).
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
# The image's own Python, never a downloaded one; the venv lives outside the code folder.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
# Read-only for the app user: the API writes nothing to its own files.
COPY . /app/backend
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
