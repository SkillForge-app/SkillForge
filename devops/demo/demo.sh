#!/usr/bin/env bash
# The SkillForge demo in one command (OPS): the root compose.yaml plus devops/demo/compose.demo.yaml,
# in a codespace or on a laptop (Docker + Git Bash). Guide: docs/devops/demo-codespaces.md.
#
#   bash devops/demo/demo.sh [up]       # DB, migrations, seed, api, worker, web, then the health table
#   bash devops/demo/demo.sh status     # the health table only
#   bash devops/demo/demo.sh logs [svc] # recent logs (TAIL=200)
#   bash devops/demo/demo.sh stop       # stop the containers (monitoring too), keep the data
#   bash devops/demo/demo.sh reset      # delete the containers AND the volumes, monitoring's too (asks first)
#   bash devops/demo/demo.sh prepare    # sources, images, model cache, no start (post-create)
#   bash devops/demo/demo.sh check      # sources + the compose files are valid (CI)
#
# Settings, all optional, from your shell:
#   OPENROUTER_API_KEY  the Codespaces secret. Set: live LLM mode. Not set: fake mode.
#   DEMO_LLM_MODE       auto (default), fake (even with a key), live (fail without a key)
#   DEMO_BACKEND_REF, DEMO_FRONTEND_REF   branch or full commit SHA (devops/demo/fetch-sources.sh)
#   DEMO_MONITORING=1   `up` also starts monitoring (devops/monitoring/monitor.sh up: Prometheus,
#                       AI-21's alerts, Grafana). With the ONCALL_TELEGRAM_BOT_TOKEN and
#                       ONCALL_TELEGRAM_CHAT_ID Codespaces secrets, alerts go to Telegram; without,
#                       it runs with no on-call channel. devops/monitoring.md.
#
# The key is never printed, never written to a host file and never read from one: it reaches only
# the worker, as a compose secret (compose.demo.yaml), so it is not in `docker inspect`. This
# script never runs `set -x` or `docker compose config` without --quiet.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"
export DEMO_ROOT="${ROOT}"

# The monitoring file is always listed, so its services belong to the project: `up
# --remove-orphans` must not delete a running monitoring stack. They start only with its profile.
FILES=(-f compose.yaml -f devops/demo/compose.demo.yaml -f devops/monitoring/compose.monitoring.yaml)
PROFILES=(--profile api --profile worker --profile web)
SEED_PROJECT="SkillForge demo"

# Monitoring's compose secrets need their variables to EXIST (empty is fine: no file, no channel).
# Only a missing one is set, to empty; a value from the Codespaces secrets is kept as it is.
export ONCALL_TELEGRAM_BOT_TOKEN="${ONCALL_TELEGRAM_BOT_TOKEN-}" ONCALL_TELEGRAM_CHAT_ID="${ONCALL_TELEGRAM_CHAT_ID-}"

dc() { docker compose "${FILES[@]}" "${PROFILES[@]}" "$@"; }
# The same, monitoring included: for stop, reset and status.
dcm() { dc --profile monitoring --profile monitoring-test "$@"; }

monitoring_wanted() {
  case "${DEMO_MONITORING:-0}" in
    1) return 0 ;;
    0 | "") return 1 ;;
    *) die "DEMO_MONITORING must be 1 or 0 (got '${DEMO_MONITORING}')" ;;
  esac
}

# Starts monitoring after the stack. Its failure is reported, not fatal: the demo still runs.
monitoring_up() {
  local mode=telegram
  if [ -z "${ONCALL_TELEGRAM_BOT_TOKEN}" ]; then
    mode=off
    say "monitoring: no ONCALL_TELEGRAM_BOT_TOKEN in this shell, so no on-call channel (alerts stay in Grafana/Alertmanager)"
  fi
  MONITOR_ONCALL="${mode}" bash devops/monitoring/monitor.sh up \
    || say "WARNING: monitoring did not start: bash devops/monitoring/monitor.sh logs"
}
say() { printf 'demo: %s\n' "$*"; }
die() { printf 'demo: ERROR: %s\n' "$*" >&2; exit 1; }

need_docker() {
  docker info > /dev/null 2>&1 \
    || die "Docker is not answering. In a codespace, wait a minute after it starts; on a laptop, start Docker Desktop."
}

# .env holds compose's local placeholders (POSTGRES_PASSWORD, ports). It is created only when
# missing, never overwritten, and never read by this script for secrets.
ensure_env() {
  if [ -e .env ]; then
    say ".env exists; left as it is"
  else
    cp .env.example .env
    say "created .env from .env.example (local placeholders only; gitignored)"
  fi
  # Keys never go in files. This looks for the NAME only; no value is read or printed.
  if grep -qE '^[[:space:]]*(export[[:space:]]+)?OPENROUTER_API_KEY[[:space:]]*=' .env; then
    die ".env contains OPENROUTER_API_KEY: remove that line. The key comes only from the Codespaces secret (or your shell)."
  fi
}

# Where compose builds backend/ and frontend/ from: this checkout once they are on the branch,
# else the export made by fetch-sources.sh.
contexts() {
  if [ -f backend/app/main.py ]; then
    DEMO_BACKEND_CONTEXT=./backend
  else
    DEMO_BACKEND_CONTEXT=./.demo/src/backend
  fi
  if [ -f frontend/package.json ]; then
    DEMO_FRONTEND_CONTEXT=./frontend
  else
    DEMO_FRONTEND_CONTEXT=./.demo/src/frontend
  fi
  export DEMO_BACKEND_CONTEXT DEMO_FRONTEND_CONTEXT
}

need_sources() {
  [ -f "${DEMO_BACKEND_CONTEXT}/app/main.py" ] \
    || die "no backend at ${DEMO_BACKEND_CONTEXT}; run: bash devops/demo/demo.sh prepare"
  [ -f "${DEMO_FRONTEND_CONTEXT}/package.json" ] \
    || die "no frontend at ${DEMO_FRONTEND_CONTEXT}; run: bash devops/demo/demo.sh prepare"
}

# Picks live or fake, exports the switches compose passes on, and prints the banner.
llm_mode() {
  local want="${DEMO_LLM_MODE:-auto}" mode reason
  case "${want}" in
    auto | live | fake) ;;
    *) die "DEMO_LLM_MODE must be auto, live or fake (got '${want}')" ;;
  esac
  if [ "${want}" = fake ]; then
    mode=fake
    reason="DEMO_LLM_MODE=fake was set; the key (if any) is not passed on."
  elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
    mode=live
    reason="OPENROUTER_API_KEY: set (Codespaces secret). Model calls cost money on that key."
  elif [ "${want}" = live ]; then
    die "DEMO_LLM_MODE=live, but OPENROUTER_API_KEY is not set in this shell (a new or changed Codespaces secret needs a codespace restart)"
  else
    mode=fake
    reason="OPENROUTER_API_KEY: not set (no Codespaces secret in this shell)."
  fi
  if [ "${mode}" = live ]; then
    export SKILLFORGE_PIPELINE=real SKILLFORGE_LLM_BACKEND=litellm
  else
    export SKILLFORGE_PIPELINE=fake SKILLFORGE_LLM_BACKEND=fake
    # Empty, not unset: compose needs the secret's variable to exist, and creates no file for an
    # empty value, so the worker has no key.
    export OPENROUTER_API_KEY=
  fi
  echo "=========================================================================="
  if [ "${mode}" = live ]; then
    echo "  LLM MODE: LIVE (OpenRouter)"
  else
    echo "  LLM MODE: FAKE: no model is called. Pipeline answers are the canned"
    echo "  examples in ai/examples/ (AI's FakePipeline)."
  fi
  echo "  ${reason}"
  echo "  SKILLFORGE_PIPELINE=${SKILLFORGE_PIPELINE}  SKILLFORGE_LLM_BACKEND=${SKILLFORGE_LLM_BACKEND}"
  echo "=========================================================================="
}

# The build and model steps need no key: make sure none is passed while they run.
no_key() {
  export SKILLFORGE_PIPELINE=fake SKILLFORGE_LLM_BACKEND=fake
  export OPENROUTER_API_KEY=  # empty, not unset: see llm_mode
}

# wait_until <seconds> <description> <command...>
wait_until() {
  local seconds="$1" what="$2"
  shift 2
  local end=$((SECONDS + seconds))
  until "$@" > /dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${end}" ]; then
      say "${what}: not ready after ${seconds} s"
      return 1
    fi
    sleep 3
  done
}

healthy() { [ "$(dc ps "$1" --format '{{.Health}}' 2> /dev/null)" = healthy ]; }
worker_ready() { dc logs --no-log-prefix worker 2> /dev/null | grep -q 'worker placeholder: model ok'; }

# host:port that a service publishes (127.0.0.1 only, from compose.yaml), or empty.
published() { dc port "$1" "$2" 2> /dev/null | head -n 1 | tr -d '\r' || true; }

seed_present() {
  dc exec -T api python -c "import json, sys, urllib.request; sys.exit(0 if any(p['name'] == sys.argv[1] for p in json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/projects', timeout=5))) else 1)" "${SEED_PROJECT}"
}

# ---------------------------------------------------------------- commands

cmd_prepare() {
  need_docker
  ensure_env
  no_key
  bash devops/demo/fetch-sources.sh
  contexts
  need_sources
  say "building the api, worker and web images (cached after the first time)"
  dc build
  say "model cache: downloads the pinned model once, checked against models.yaml's sha256"
  dc run --rm model-init
  if monitoring_wanted; then
    say "monitoring images (DEMO_MONITORING=1)"
    dcm pull --quiet prometheus alertmanager grafana blackbox redis-exporter docker-socket-proxy
  fi
  say "prepared. Start the demo with: bash devops/demo/demo.sh"
}

cmd_up() {
  need_docker
  ensure_env
  llm_mode
  bash devops/demo/fetch-sources.sh
  contexts
  need_sources
  say "starting: postgres + redis, migrate, api, model-init + worker, web"
  if ! dc up --detach --build --remove-orphans; then
    dc ps --all
    die "compose could not start the stack. Read: bash devops/demo/demo.sh logs migrate model-init"
  fi
  local ok=1
  wait_until 240 api healthy api || ok=0
  wait_until 120 worker worker_ready || ok=0
  wait_until 240 web healthy web || ok=0
  if [ "${ok}" = 1 ]; then
    dc exec -T api python - < devops/demo/seed.py
  else
    say "skipping the seed: the stack is not up (see the table below)"
  fi
  if monitoring_wanted; then
    monitoring_up
  fi
  cmd_status
}

cmd_status() {
  need_docker
  [ -e .env ] || die "no .env yet: run bash devops/demo/demo.sh"
  contexts
  local bad=0 addr out
  row() { printf '  %-9s %-5s %s\n' "$1" "$2" "$3"; }
  echo
  echo "  SERVICE   STATE DETAIL"

  if dc exec -T postgres pg_isready -h 127.0.0.1 -U skillforge -d skillforge > /dev/null 2>&1; then
    row postgres up "pg_isready ok, on $(published postgres 5432) (never forward this port)"
  else
    row postgres DOWN "pg_isready failed: demo.sh logs postgres"
    bad=1
  fi

  if [ "$(dc exec -T redis redis-cli ping 2> /dev/null | tr -d '\r')" = PONG ]; then
    row redis up "PONG, on $(published redis 6379) (never forward this port)"
  else
    row redis DOWN "no PONG: demo.sh logs redis"
    bad=1
  fi

  out="$(dc ps --all migrate --format '{{.State}} {{.ExitCode}}' 2> /dev/null || true)"
  if [ "${out}" = "exited 0" ]; then
    out="$(dc exec -T postgres psql -U skillforge -d skillforge -Atc 'SELECT version_num FROM alembic_version' 2> /dev/null | tr -d '\r' || true)"
    row migrate "done" "alembic at ${out:-?}"
  else
    row migrate FAIL "state '${out:-not run}': demo.sh logs migrate"
    bad=1
  fi

  addr="$(published api 8000)"
  if [ -n "${addr}" ] && curl -fsS --max-time 5 "http://${addr}/health" 2> /dev/null | grep -q healthy; then
    row api up "/health ok on ${addr} (keep this port Private)"
  else
    row api DOWN "/health did not answer: demo.sh logs api"
    bad=1
  fi

  if seed_present > /dev/null 2>&1; then
    row seed ok "project '${SEED_PROJECT}' exists"
  else
    row seed MISS "no '${SEED_PROJECT}' project (run demo.sh up again)"
    bad=1
  fi

  out="$(dc logs --no-log-prefix worker 2> /dev/null | tr -d '\r' || true)"
  if [ "$(dc ps worker --format '{{.State}}' 2> /dev/null)" = running ] \
    && printf '%s\n' "${out}" | grep -q 'worker placeholder: model ok'; then
    row worker up "placeholder: model ok, offline (the real RQ worker comes after Backend PR #14)"
  else
    row worker DOWN "no model check yet: demo.sh logs model-init worker"
    bad=1
  fi
  out="$(printf '%s\n' "${out}" | grep 'worker: LLM mode' | tail -n 1 || true)"
  row llm "" "${out#worker: }"

  addr="$(published web 3000)"
  if [ -n "${addr}" ] && curl -fsS --max-time 10 -o /dev/null "http://${addr}/" 2> /dev/null; then
    row web up "HTTP 200 on ${addr}"
  else
    row web DOWN "no answer: demo.sh logs web"
    bad=1
  fi

  if [ "$(dcm ps prometheus --format '{{.State}}' 2> /dev/null)" = running ] \
    && out="$(MSYS_NO_PATHCONV=1 dcm exec -T ai-metrics python /ops/monitor_query.py oncall 2> /dev/null | tr -d '\r')"; then
    row monitor up "Grafana on $(dcm port grafana 3000 2> /dev/null | head -n 1 | tr -d '\r'), on-call: ${out} (details: devops/monitoring/monitor.sh status)"
  elif monitoring_wanted; then
    row monitor DOWN "DEMO_MONITORING=1 but it is not running: bash devops/monitoring/monitor.sh logs"
    bad=1
  else
    row monitor off "not started (DEMO_MONITORING=1 starts it with the demo)"
  fi

  local dir context ref commit
  for dir in backend frontend; do
    context="${DEMO_BACKEND_CONTEXT}"
    [ "${dir}" = frontend ] && context="${DEMO_FRONTEND_CONTEXT}"
    if [ "${context}" = "./${dir}" ]; then
      row "${dir}" src "this checkout ($(git rev-parse --short HEAD))"
    elif [ -f ".demo/src/${dir}.ref" ]; then
      read -r _ ref commit < ".demo/src/${dir}.ref"
      row "${dir}" src "${ref} at ${commit:0:12}"
    else
      row "${dir}" src "not fetched yet"
    fi
  done

  echo
  if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
    echo "  Web (Private until YOU make port 3000 Public, by hand, on demo day):"
    echo "    https://${CODESPACE_NAME}-3000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
    echo "  API docs, for you only (port 8000 stays Private):"
    echo "    https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/docs"
    if [ "$(dcm ps grafana --format '{{.State}}' 2> /dev/null)" = running ]; then
      echo "  Grafana, for you only (port 3001 stays Private):"
      echo "    https://${CODESPACE_NAME}-3001.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
    fi
    echo "  Ports 8000, 5433 and 6379 always stay Private, and so do monitoring's 3001, 9090 and 9093."
  else
    echo "  Web: http://$(published web 3000)   API docs: http://$(published api 8000)/docs"
  fi
  echo
  if [ "${bad}" = 0 ]; then
    say "everything is up"
  else
    say "something is down (see above)"
  fi
  return "${bad}"
}

cmd_logs() {
  need_docker
  [ -e .env ] || die "no .env yet: run bash devops/demo/demo.sh"
  contexts
  dc logs --no-color --tail="${TAIL:-200}" "$@"
}

cmd_stop() {
  need_docker
  contexts
  dcm stop
  say "stopped (monitoring too); the data and the model cache are kept. Remember: set port 3000 back to Private."
}

cmd_reset() {
  need_docker
  contexts
  local answer
  read -r -p "demo: delete the demo containers AND volumes (database, redis, model cache, monitoring data)? Type 'reset': " answer
  [ "${answer}" = reset ] || die "not reset"
  dcm down --volumes --remove-orphans
  say "reset. The next 'demo.sh' downloads the model again (about 66 MB) and re-seeds."
}

cmd_check() {
  ensure_env
  no_key
  bash devops/demo/fetch-sources.sh
  contexts
  need_sources
  dc config --quiet
  dcm config --quiet
  say "the compose files are valid, monitoring's too (api from ${DEMO_BACKEND_CONTEXT}, web from ${DEMO_FRONTEND_CONTEXT})"
}

case "${1:-up}" in
  up) cmd_up ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  stop) cmd_stop ;;
  reset) cmd_reset ;;
  prepare) cmd_prepare ;;
  check) cmd_check ;;
  -h | --help | help) sed -n '2,21p' "$0" ;;
  *) die "unknown command '$1' (up, status, logs, stop, reset, prepare, check)" ;;
esac
