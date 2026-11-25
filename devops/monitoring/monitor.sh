#!/usr/bin/env bash
# Monitoring in one command (OPS-10, OPS-17; devops/monitoring.md): Prometheus with AI-21's alerts,
# Alertmanager -> the on-call Telegram chat, Grafana. On top of whatever else runs (the demo too).
#
#   bash devops/monitoring/monitor.sh up         # start (or update) it; the test alert stays silenced
#   bash devops/monitoring/monitor.sh status     # targets, alerts, silences, on-call, URLs
#   bash devops/monitoring/monitor.sh test       # proves an AI alert reaches the on-call (AI-21, OPS-10)
#   bash devops/monitoring/monitor.sh test-cost  # proves the spend and budget alerts do (OPS-17). Laptop only
#   bash devops/monitoring/monitor.sh chat-id    # finds your Telegram group's chat id
#   bash devops/monitoring/monitor.sh logs [svc] # recent logs (TAIL=200), bot tokens masked
#   bash devops/monitoring/monitor.sh down       # stop and remove the monitoring containers; keep the data
#
# Settings, from your shell (never from .env or any file):
#   ONCALL_TELEGRAM_BOT_TOKEN  the bot's token (secret)              } Codespaces secrets, or
#   ONCALL_TELEGRAM_CHAT_ID    the group's chat id, e.g. -100123...  } read -rs NAME; export NAME
#   MONITOR_ONCALL             telegram (default) or off (no channel: alerts stay in the web UIs)
#   MONITOR_ALLOW_TEST_COST=1  lets test-cost run in a codespace (don't: see devops/monitoring.md)
#
# The token and chat id are checked by NAME only: never printed, never written to a file, never
# passed on a command line. This script never runs `set -x` or `docker compose config` without --quiet.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"

FILES=(-f compose.yaml -f devops/monitoring/compose.monitoring.yaml)
SERVICES=(prometheus alertmanager ai-metrics docker-socket-proxy redis-exporter blackbox grafana)
TEST_ALERT=AIAlertPipelineTest

dc() { docker compose "${FILES[@]}" --profile monitoring "$@"; }
say() { printf 'monitor: %s\n' "$*"; }
die() { printf 'monitor: ERROR: %s\n' "$*" >&2; exit 1; }
# Bot tokens look like 123456789:AA...; mask any in text we show (Alertmanager redacts its own).
mask() { sed -E 's/[0-9]{5,}:[A-Za-z0-9_-]{20,}/<bot-token>/g'; }
# Prometheus and Alertmanager questions, asked from inside the network (devops/monitoring/monitor_query.py).
query() { MSYS_NO_PATHCONV=1 dc exec -T ai-metrics python /ops/monitor_query.py "$@"; }
amtool() { MSYS_NO_PATHCONV=1 dc exec -T alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 "$@"; }

need_docker() {
  docker info > /dev/null 2>&1 || die "Docker is not answering (start Docker Desktop; in a codespace, wait a minute)"
}

# .env holds compose's local placeholders only. The Telegram settings must never be in it.
ensure_env() {
  if [ ! -e .env ]; then
    cp .env.example .env
    say "created .env from .env.example (local placeholders only; gitignored)"
  fi
  if grep -qE '^[[:space:]]*(export[[:space:]]+)?ONCALL_TELEGRAM_(BOT_TOKEN|CHAT_ID)[[:space:]]*=' .env; then
    die ".env contains an ONCALL_TELEGRAM_ setting: remove that line. It comes only from your shell or the Codespaces secrets."
  fi
}

# Picks the Alertmanager config and checks the two settings, by name only.
oncall_mode() {
  local mode="${MONITOR_ONCALL:-telegram}"
  case "${mode}" in
    telegram)
      [ -n "${ONCALL_TELEGRAM_BOT_TOKEN:-}" ] \
        || die "ONCALL_TELEGRAM_BOT_TOKEN is not set in this shell (Codespaces secret, or: read -rs ONCALL_TELEGRAM_BOT_TOKEN; export ONCALL_TELEGRAM_BOT_TOKEN). Without a channel: MONITOR_ONCALL=off"
      [[ "${ONCALL_TELEGRAM_BOT_TOKEN}" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] \
        || die "ONCALL_TELEGRAM_BOT_TOKEN does not look like a bot token (digits:letters, from @BotFather)"
      [ -n "${ONCALL_TELEGRAM_CHAT_ID:-}" ] \
        || die "ONCALL_TELEGRAM_CHAT_ID is not set in this shell (find it with: monitor.sh chat-id)"
      [[ "${ONCALL_TELEGRAM_CHAT_ID}" =~ ^-?[0-9]+$ ]] \
        || die "ONCALL_TELEGRAM_CHAT_ID must be an integer; a group's id is negative, like -100... (monitor.sh chat-id)"
      export ALERTMANAGER_CONFIG=alertmanager.yml
      ;;
    off)
      # Empty, not unset: compose needs the secrets' variables; an empty value creates no file.
      export ONCALL_TELEGRAM_BOT_TOKEN= ONCALL_TELEGRAM_CHAT_ID= ALERTMANAGER_CONFIG=alertmanager.off.yml
      ;;
    *) die "MONITOR_ONCALL must be telegram or off (got '${mode}')" ;;
  esac
  ONCALL="${mode}"
}

# The commands that only talk to a running stack still need the secrets' variables to exist.
placeholders() {
  export ONCALL_TELEGRAM_BOT_TOKEN="${ONCALL_TELEGRAM_BOT_TOKEN-}" ONCALL_TELEGRAM_CHAT_ID="${ONCALL_TELEGRAM_CHAT_ID-}"
}

need_running() {
  [ "$(dc ps alertmanager --format '{{.State}}' 2> /dev/null)" = running ] \
    && [ "$(dc ps ai-metrics --format '{{.State}}' 2> /dev/null)" = running ] \
    || die "monitoring is not running: bash devops/monitoring/monitor.sh up"
}

# The always-firing test alert stays silenced except during `test`.
test_silences() { amtool silence query --quiet "alertname=${TEST_ALERT}" | tr -d '\r'; }
silence_test_alert() {
  if [ -z "$(test_silences)" ]; then
    amtool silence add "alertname=${TEST_ALERT}" --duration=8760h --author=monitor.sh \
      --comment="Always firing: lifted only by monitor.sh test (devops/monitoring.md)" > /dev/null
  fi
}
unsilence_test_alert() {
  local ids
  ids="$(test_silences)"
  if [ -n "${ids}" ]; then
    # shellcheck disable=SC2086 # one id per word
    amtool silence expire ${ids}
  fi
}

# wait_notified <seconds> <since> <alertname>...: waits until Alertmanager delivered each alert's
# group to Telegram after <since> (its debug log's `Notify success` line names the group, so
# another alert sent at the same moment can't pass for it). Stops after 3 failed attempts.
wait_notified() {
  local seconds="$1" since="$2" end name log missing failures
  shift 2
  end=$((SECONDS + seconds))
  while :; do
    log="$(dc logs --no-color --no-log-prefix --since "${since}" alertmanager 2>&1 | tr -d '\r')"
    missing=()
    for name in "$@"; do
      printf '%s\n' "${log}" | grep 'msg="Notify success"' | grep -qF "alertname=\\\"${name}\\\"" \
        || missing+=("${name}")
    done
    if [ "${#missing[@]}" = 0 ]; then
      for name in "$@"; do echo "  ${name}: delivered to Telegram"; done
      return 0
    fi
    failures="$(printf '%s\n' "${log}" | grep -cE 'msg="Notify (attempt )?failed' || true)"
    if [ "${failures}" -ge 3 ] || [ "${SECONDS}" -ge "${end}" ]; then
      echo "  not delivered: ${missing[*]} (${failures} failed attempts). Alertmanager's errors:"
      printf '%s\n' "${log}" | grep -E 'level=(WARN|ERROR)' | tail -n 5 | cut -c1-400 | mask
      return 1
    fi
    sleep 5
  done
}

# Now, as Docker's --since reads it, a few seconds early for clock drift between host and engine.
now_utc() { date -u -d '-5 seconds' +%Y-%m-%dT%H:%M:%SZ 2> /dev/null || date -u +%Y-%m-%dT%H:%M:%SZ; }

url() { # url <port variable> <default port> <path>
  local port
  port="$(grep -E "^$1=" .env 2> /dev/null | tail -n 1 | cut -d= -f2 | tr -d '\r')"
  port="${port:-$2}"
  if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
    printf 'https://%s-%s.%s%s' "${CODESPACE_NAME}" "${port}" "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}" "$3"
  else
    printf 'http://127.0.0.1:%s%s' "${port}" "$3"
  fi
}

# ---------------------------------------------------------------- commands

cmd_up() {
  need_docker
  ensure_env
  oncall_mode
  say "starting monitoring (on-call: ${ONCALL})"
  dc up --detach --wait --wait-timeout 300 "${SERVICES[@]}"
  # Alertmanager reads the secrets and its config only when created: recreate it, so a new token,
  # chat id or MONITOR_ONCALL always applies. Silences live in its volume and survive.
  dc up --detach --wait --wait-timeout 120 --force-recreate --no-deps alertmanager
  silence_test_alert
  say "${TEST_ALERT} is silenced (it always fires; 'monitor.sh test' lifts the silence for the test)"
  cmd_status
}

cmd_status() {
  need_docker
  placeholders
  need_running
  echo
  query status || true
  echo
  echo "  Grafana:      $(url GRAFANA_PORT 3001 /) (dashboards: SkillForge folder)"
  echo "  Prometheus:   $(url PROMETHEUS_PORT 9090 /alerts)"
  echo "  Alertmanager: $(url ALERTMANAGER_PORT 9093 /)"
  [ -n "${CODESPACE_NAME:-}" ] && echo "  Keep these three ports Private."
  echo
}

cmd_test() {
  need_docker
  placeholders
  need_running
  say "1/3 AI-21's rules (ai/ops/alerts.yaml) are loaded"
  query rules
  say "2/3 ${TEST_ALERT} fires and reaches Alertmanager"
  query wait-firing 120 "${TEST_ALERT}" || die "${TEST_ALERT} is not firing in Prometheus and Alertmanager"
  if [ "$(query oncall | tr -d '\r')" != telegram ]; then
    say "3/3 SKIPPED: Alertmanager runs with MONITOR_ONCALL=off, so nothing is sent. With the bot: monitor.sh up, then monitor.sh test"
    return 0
  fi
  local since
  since="$(now_utc)"
  say "3/3 lifting the silence: Telegram should get a [TEST] message within about 2 minutes"
  trap 'silence_test_alert; say "${TEST_ALERT} is silenced again"' EXIT
  unsilence_test_alert
  wait_notified 420 "${since}" "${TEST_ALERT}" || die "the test alert did not reach Telegram (see above)"
  say "DELIVERED: ${TEST_ALERT} -> Telegram. Check the chat for the [TEST] message (AI-21 / OPS-10 done-when)."
}

cmd_test_cost() {
  need_docker
  placeholders
  if [ "${CODESPACES:-}" = true ] && [ "${MONITOR_ALLOW_TEST_COST:-}" != 1 ]; then
    die "test-cost does not run in a codespace: its \$20 of synthetic spend stays in AI's 7-day windows (drift alerts) of the demo. Run it on your laptop (devops/monitoring.md). Override: MONITOR_ALLOW_TEST_COST=1"
  fi
  need_running
  local mode since alert new=()
  # An alert that already fires (in Prometheus, or still active in Alertmanager) was notified when
  # it started, and Alertmanager won't repeat it within its repeat interval: only the others send
  # a message now.
  for alert in AILLMSpendRateHigh AIBudgetExceeded; do
    query known "${alert}" > /dev/null || new+=("${alert}")
  done
  mode="$(query oncall | tr -d '\r')"
  since="$(now_utc)"
  say "1/3 logging synthetic events through AI's code: 4 calls x \$5 (model ops-test/synthetic) and 1 budget stop. No model is called."
  # Its JSON lines go to Docker's log, where ai-metrics reads them; the terminal gets the summary.
  MSYS_NO_PATHCONV=1 dc --profile monitoring-test run --rm --no-deps ai-test-events > /dev/null
  say "2/3 waiting for AILLMSpendRateHigh (page) and AIBudgetExceeded (ticket): about 1-2 minutes"
  query wait-firing 240 AILLMSpendRateHigh AIBudgetExceeded || die "the cost alerts did not fire (monitor.sh logs ai-metrics prometheus)"
  echo "  synthetic spend counted by ai-metrics since it started: \$$(query value 'sum(skillforge_llm_cost_usd_total{model="ops-test/synthetic"})' | tr -d '\r')"
  echo "  synthetic tokens (in + out): $(query value 'sum(skillforge_llm_input_tokens_total{model="ops-test/synthetic"}) + sum(skillforge_llm_output_tokens_total{model="ops-test/synthetic"})' | tr -d '\r')"
  if [ "${mode}" != telegram ]; then
    say "3/3 SKIPPED: Alertmanager runs with MONITOR_ONCALL=off, so nothing is sent"
  elif [ "${#new[@]}" = 0 ]; then
    say "3/3 SKIPPED: both alerts were already firing (an earlier run), so Telegram was notified then. They resolve about 1 hour after it; run test-cost again after that"
  else
    say "3/3 waiting for Telegram: ${#new[@]} message(s), for ${new[*]} ([PAGE] is loud, [ticket] silent)"
    wait_notified 300 "${since}" "${new[@]}" || die "the cost alerts did not reach Telegram (see above)"
    say "DELIVERED: ${new[*]} -> Telegram (OPS-17 done-when)."
  fi
  say "Both resolve about 1 hour from now. Real spend alerts were not silenced."
}

# Lists the chats the bot has seen (send any message in the group first). The token goes to curl
# on stdin (--config -), so it is in no command line; only ids and titles are printed.
cmd_chat_id() {
  [ -n "${ONCALL_TELEGRAM_BOT_TOKEN:-}" ] || die "set ONCALL_TELEGRAM_BOT_TOKEN first (read -rs ONCALL_TELEGRAM_BOT_TOKEN; export ONCALL_TELEGRAM_BOT_TOKEN)"
  local out
  out="$(printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "${ONCALL_TELEGRAM_BOT_TOKEN}" \
    | curl -sS --max-time 20 --fail --config - 2>&1 | mask)" || die "Telegram did not answer: ${out}"
  printf '%s\n' "${out}" | grep -oE '"chat":\{"id":-?[0-9]+,"title":"[^"]*"' \
    | sed -E 's/"chat":\{"id":(-?[0-9]+),"title":"([^"]*)"/  \1  \2/' | sort -u \
    || say "no group chat seen yet: add the bot to the group, send a message there, and run this again"
}

cmd_logs() {
  need_docker
  placeholders
  dc logs --no-color --tail="${TAIL:-200}" "$@" 2>&1 | mask
}

cmd_down() {
  need_docker
  placeholders
  dc rm --stop --force "${SERVICES[@]}"
  say "monitoring stopped and removed; its data (promdata, amdata, grafana) is kept"
}

case "${1:-}" in
  up) cmd_up ;;
  status) cmd_status ;;
  test) cmd_test ;;
  test-cost) cmd_test_cost ;;
  chat-id) cmd_chat_id ;;
  logs) shift; cmd_logs "$@" ;;
  down) cmd_down ;;
  -h | --help | help | "") sed -n '2,22p' "$0" ;;
  *) die "unknown command '$1' (up, status, test, test-cost, chat-id, logs, down)" ;;
esac
