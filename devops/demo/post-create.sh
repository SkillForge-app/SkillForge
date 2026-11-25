#!/usr/bin/env bash
# Runs once when the codespace (or a local dev container) is created: postCreateCommand in
# .devcontainer/devcontainer.json. How the demo works: docs/devops/demo-codespaces.md.
#
#   bash devops/demo/post-create.sh               # uv, then everything `demo.sh prepare` does
#   bash devops/demo/post-create.sh --tools-only  # uv only (CI)
#
# It needs no secret: OPENROUTER_API_KEY is read only when the demo starts (demo.sh up).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

log() { printf 'post-create: %s\n' "$*"; }

# ---------------------------------------------------------------- uv
# The same version and sha256s as the images, read from devops/docker/api.Dockerfile, so there is
# one place to update them.
install_uv() {
  local dockerfile=devops/docker/api.Dockerfile version arch sha name tmp
  version="$(sed -n 's/^ARG UV_VERSION=//p' "${dockerfile}")"
  arch="$(uname -m)"
  case "${arch}" in
    x86_64) sha="$(sed -n 's/^ARG UV_SHA256_X86_64=//p' "${dockerfile}")" ;;
    aarch64) sha="$(sed -n 's/^ARG UV_SHA256_AARCH64=//p' "${dockerfile}")" ;;
    *) log "unsupported architecture ${arch}"; exit 1 ;;
  esac
  if [ -z "${version}" ] || [ -z "${sha}" ]; then
    log "cannot read UV_VERSION / UV_SHA256 from ${dockerfile}"
    exit 1
  fi
  if command -v uv > /dev/null && [ "$(uv --version | awk '{print $2}')" = "${version}" ]; then
    log "uv ${version} already installed"
    return
  fi
  name="uv-${arch}-unknown-linux-gnu"
  tmp="$(mktemp -d)"
  curl -fsSL --retry 3 -o "${tmp}/uv.tar.gz" \
    "https://github.com/astral-sh/uv/releases/download/${version}/${name}.tar.gz"
  echo "${sha}  ${tmp}/uv.tar.gz" | sha256sum -c - > /dev/null
  tar -xzf "${tmp}/uv.tar.gz" -C "${tmp}" --strip-components=1 "${name}/uv" "${name}/uvx"
  if command -v sudo > /dev/null && sudo -n true 2> /dev/null; then
    sudo install -m 0755 "${tmp}/uv" "${tmp}/uvx" /usr/local/bin/
  else
    mkdir -p "${HOME}/.local/bin"
    install -m 0755 "${tmp}/uv" "${tmp}/uvx" "${HOME}/.local/bin/"
  fi
  rm -rf "${tmp}"
  log "installed $(uv --version) (sha256 checked)"
}

install_uv
if [ "${1:-}" = "--tools-only" ]; then
  exit 0
fi

# ---------------------------------------------------------------- docker
# docker-in-docker starts its daemon with the container; give it a minute.
for _ in $(seq 1 30); do
  if docker info > /dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! docker info > /dev/null 2>&1; then
  log "the Docker daemon is not answering; run 'bash devops/demo/demo.sh prepare' once it is"
  exit 1
fi

# ---------------------------------------------------------------- sources, images, model cache
bash devops/demo/demo.sh prepare
log "done. Start the demo with: bash devops/demo/demo.sh"
