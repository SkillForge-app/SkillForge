#!/usr/bin/env bash
# The monitoring checks (OPS-10): .github/workflows/monitoring.yml runs this, and so can you.
#   bash devops/monitoring/ci-checks.sh
# Needs Docker (promtool and amtool run from the pinned images) and a Python with AI's
# dependencies for the exporter's self-test:
#   PYTHON="uv run --project ai --frozen python"   (CI)     or the path of ai/.venv's python.
# No network beyond pulling the pinned images; no secret is needed or read.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep /paths as they are for docker

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"
# The repo as Docker sees it (C:/... under Git Bash, the path itself elsewhere).
MOUNT="$(pwd -W 2> /dev/null || pwd)"
FILES=(-f compose.yaml -f devops/monitoring/compose.monitoring.yaml)
ENV_FILE=.env
[ -f "${ENV_FILE}" ] || ENV_FILE=.env.example
dc() { docker compose --env-file "${ENV_FILE}" "${FILES[@]}" --profile monitoring "$@"; }

step() { printf '\n== %s\n' "$*"; }
fail() { printf 'monitoring-ci: ERROR: %s\n' "$*" >&2; exit 1; }

step "compose files are valid"
dc config --quiet

step "every image is pinned by digest"
images="$(dc config --images)"
printf '%s\n' "${images}"
if printf '%s\n' "${images}" | grep -v '@sha256:' | grep -v '^skillforge-'; then
  fail "the images above are not pinned by digest"
fi
image_of() { printf '%s\n' "${images}" | grep -m1 "^$1:" || fail "no $1 image in the compose files"; }
PROMETHEUS="$(image_of prom/prometheus)"

promtool() {
  docker run --rm --network none --entrypoint promtool -v "${MOUNT}:/w:ro" -w /w "${PROMETHEUS}" "$@"
}

step "AI-21's rules load unchanged, and DevOps' rules are valid"
promtool check rules ai/ops/alerts.yaml devops/monitoring/rules/*.yaml

step "Prometheus config is valid (rule paths as mounted in the container)"
docker run --rm --network none --entrypoint promtool \
  -v "${MOUNT}/devops/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "${MOUNT}/devops/monitoring/rules:/etc/prometheus/rules/ops:ro" \
  -v "${MOUNT}/ai/ops:/etc/prometheus/rules/ai:ro" \
  "${PROMETHEUS}" check config /etc/prometheus/prometheus.yml

step "alert unit tests"
promtool test rules devops/monitoring/tests/alerts_test.yaml

ALERTMANAGER="$(image_of prom/alertmanager)"
amtool() {
  docker run --rm --network none --entrypoint amtool \
    -v "${MOUNT}/devops/monitoring/alertmanager:/etc/alertmanager:ro" "${ALERTMANAGER}" "$@"
}

step "Alertmanager configs are valid (Telegram, and MONITOR_ONCALL=off)"
amtool check-config /etc/alertmanager/alertmanager.yml /etc/alertmanager/alertmanager.off.yml

step "the Telegram message template renders"
amtool template render --template.glob=/etc/alertmanager/telegram.tmpl \
  --template.text='{{ template "skillforge.telegram.message" . }}'

step "the exporter applies AI's metric rules exactly (self-test)"
read -r -a python <<< "${PYTHON:-python3}"
PYTHONPATH="${ROOT}/ai" "${python[@]}" devops/monitoring/exporter/ai_log_exporter.py \
  --selftest devops/monitoring/tests/fixture.jsonl

printf '\nmonitoring-ci: all checks passed\n'
