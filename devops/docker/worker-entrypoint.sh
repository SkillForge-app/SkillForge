#!/bin/sh
# The worker image's entrypoint (DevOps): reads the OpenRouter key from a compose secret, then runs
# the command. Used by worker.Dockerfile's ENTRYPOINT, so every command in the image (the worker,
# model-init, CI's checks, Backend's future `rq worker ...`) goes through it.
#
# Why a secret file and not `environment:`: an environment variable is part of the container's
# configuration, which `docker inspect` (and anything allowed GET /containers/{id}/json, like the
# monitoring stack's socket proxy) shows in plain text. A compose secret sourced from an
# environment variable is copied into /run/secrets inside the container only: no host file, no
# mount, nothing in `docker inspect`. This script exports it to the worker process alone.
#
# No file, or an empty one: nothing is exported (fake mode; compose creates no file for an empty
# value). The value is never printed: no `set -x`, no echo.
set -eu

secret=/run/secrets/openrouter_api_key
if [ -s "${secret}" ]; then
  OPENROUTER_API_KEY="$(cat "${secret}")"
  export OPENROUTER_API_KEY
fi
unset secret

exec "$@"
