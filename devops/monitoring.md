# Monitoring (OPS-10, OPS-17)

Metrics, alerts, an on-call channel and dashboards for the local stack and the Codespaces demo. Everything runs
inside our compose: no cloud service, no paid service. It loads AI-21's alerts (`ai/ops/alerts.yaml`)
**unchanged**, and sends them to a Telegram group.

| Service | What | On your machine |
|---|---|---|
| `prometheus` | Metrics and alert rules: AI-21's and DevOps' (`devops/monitoring/rules/ops.yaml`) | `http://127.0.0.1:9090` |
| `alertmanager` | Sends the alerts to the on-call Telegram chat | `http://127.0.0.1:9093` |
| `grafana` | Two dashboards: *SkillForge AI: models and cost* and *SkillForge services* | `http://127.0.0.1:3001` |
| `ai-metrics` | Turns the AI services' logs into AI-21's metrics (below) | (no port) |
| `docker-socket-proxy` | Lets `ai-metrics`, and only it, read container logs | (no port) |
| `redis-exporter` | RQ queue lengths | (no port) |
| `blackbox` | Health probes of `api` and `web` | (no port) |

All of it is in `devops/monitoring/compose.monitoring.yaml`, profile `monitoring`, next to the root `compose.yaml`.

## Start

```
bash devops/monitoring/monitor.sh up        # alongside whatever else runs (the demo too)
DEMO_MONITORING=1 bash devops/demo/demo.sh  # or: the demo, with monitoring
```

Without the Telegram settings, `up` stops and names the missing one. To run without an on-call channel
(alerts stay visible in Grafana and Alertmanager only): `MONITOR_ONCALL=off bash devops/monitoring/monitor.sh up`.

| Command | What it does |
|---|---|
| `monitor.sh up` | Starts or updates it. The always-firing test alert stays silenced |
| `monitor.sh status` | Targets, firing alerts, silences, on-call mode, whether AI-21's rules are loaded, the URLs |
| `monitor.sh test` | Proves an AI alert reaches the on-call (below) |
| `monitor.sh test-cost` | Proves the spend and budget alerts do. **Laptop only** (below) |
| `monitor.sh chat-id` | Finds your Telegram group's chat id |
| `monitor.sh logs [service]` | Recent logs (`TAIL=200`), bot tokens masked |
| `monitor.sh down` | Removes the monitoring containers; keeps their data |

## The on-call channel: Telegram
Free and needs no card. A *page* arrives loud; a *ticket* arrives **silently** (no sound) in the same chat.

1. In Telegram, talk to **@BotFather**: `/newbot`. It gives you the bot's **token** (`123456789:AA...`). Treat it
   as a password.
2. Create a group for the on-call people and add the bot to it. Send any message in the group.
3. Put the token in your shell without echoing it, then find the group's **chat id**: a negative number,
   `-100...` for a group.

   ```
   read -rs ONCALL_TELEGRAM_BOT_TOKEN; export ONCALL_TELEGRAM_BOT_TOKEN
   bash devops/monitoring/monitor.sh chat-id
   export ONCALL_TELEGRAM_CHAT_ID=-100...
   ```
4. **In a codespace:** add both as Codespaces secrets instead (github.com → Settings → Codespaces → Secrets,
   with access to this repository), then restart the codespace. `devcontainer.json` names them.

**Where they live:**
- Never in a file of the repository, never in `.env`. `monitor.sh` refuses if `.env` has either name.
- Never on a command line: `chat-id` gives the token to curl on stdin.
- Compose gives both to Alertmanager as **secrets**, copied into `/run/secrets/` inside that one container. There
  is no host file and no mount, and nothing shows in `docker inspect` or in `docker compose config`.
- Alertmanager 0.35 reads them with `bot_token_file` / `chat_id_file`, and redacts the URL (which holds the
  token) from its error logs.
- `monitor.sh` checks both by name and format only and never prints them.

**Checked** with a dummy token, never reaching Telegram: 0 matches of the token in every monitoring container's
`docker inspect`, in `docker compose config`, and in every monitoring log, Alertmanager's debug log included.

## What is monitored

| What | Where it comes from | Metrics |
|---|---|---|
| **Model calls**: rate, errors, fallbacks, latency, **cost**, unpriced calls | Each call's `CallRecord`, in the AI services' JSON logs | `skillforge_llm_attempts_total`, `_latency_ms`, `_cost_usd_total`, `_unpriced_total` |
| **Tokens** | `CallRecord.input_tokens` / `output_tokens` | `skillforge_llm_input_tokens_total`, `_output_tokens_total` (`metrics.extra.yaml`) |
| **Pipeline steps**, `budget_exceeded`, cost per skill | `StepEvent` | `skillforge_step_total`, `skillforge_step_cost_usd`, `skillforge_skill_cost_usd` |
| Safety decisions, ingested pages, quality samples | AI's other events | `skillforge_safety_decisions_total`, `skillforge_ingest_pages_total`, ... |
| **Service health** (api, web) | HTTP probes (`/health`, `/`) | `probe_success`, `probe_duration_seconds` |
| **Queue depth** | Redis `rq:queue:*` | `redis_key_size` |
| The monitoring itself | Every scrape target | `up`, `skillforge_ops_exporter_lines_total` |

**How AI's metrics are made:** the AI services expose no `/metrics`. They log metadata-only JSON lines (AI-21,
`ai/core/ops/logs.py`), and `ai/ops/metrics.yaml` says which metric each record feeds.
- `ai-metrics` (`devops/monitoring/exporter/ai_log_exporter.py`) applies those rules with **AI's own code**
  (`core.ops.metrics.aggregate`), so the metrics can't drift from the alerts.
- It reads the logs of the project's containers through the socket proxy. The proxy allows reading containers
  only: no writes, no images, no volumes.
- Two details:
  - **A restart re-counts nothing:** older containers are read from the exporter's start.
  - **Every new series shows 0 for 35 s** before its first value. Prometheus' `increase()` ignores a series'
    first sample, so the first-ever `budget_exceeded` would otherwise never fire `AIBudgetExceeded`.
- CI checks that its numbers equal `aggregate()` on a fixture (`--selftest`).

**The worker's OpenRouter key is not visible to it either.** The proxy allows reading a container's
configuration, so the key is no longer in the worker's environment. It is a compose secret
(`devops/demo/compose.demo.yaml`), exported by the image's entrypoint to the worker process only. Checked in
live mode with a dummy key: 0 matches in the worker's `docker inspect`, also through the proxy.

**Not covered yet:**
- **API request rate, errors and latency** need Backend's `/metrics` (for example
  prometheus-fastapi-instrumentator). The scrape job and the rules are ready, commented, in `prometheus.yml` and
  `rules/ops.yaml`.
- **Real AI events** flow once Backend's worker calls `install_json_logs(sys.stdout)` (AI's
  backend-integration guide). Today's compose worker is a placeholder, so only `test-cost`'s events appear.
- **Logs:** no log store. AI's logs are metadata and already become metrics; `docker compose logs` /
  `demo.sh logs` is enough at this scale. Loki + Alloy can be added later (about +0.2 GB of RAM).
- **Traces:** nothing emits OpenTelemetry yet. Add a collector when Backend does.

## Alerts and where they go

**AI-21's rules load as they are.** Prometheus mounts `ai/ops/` read-only and loads `alerts.yaml`: 4 groups,
17 rules. CI runs `promtool check rules` on the unchanged file. The two things the file asks of its loader are
done outside it:
- the relative `runbook_url` gets the repository URL in the Telegram message;
- the always-firing `AIAlertPipelineTest` stays silenced, except during `monitor.sh test`.

| Severity | Telegram | Repeated |
|---|---|---|
| `page` | Loud `[PAGE]` message; a `[RESOLVED]` message when it ends | every hour while it fires |
| `ticket` | Silent `[ticket]` message | every 12 hours |
| `test` | Loud `[TEST]` message (`AIAlertPipelineTest`) | only while `monitor.sh test` lifts its silence |

DevOps' rules (`devops/monitoring/rules/ops.yaml`), each with a runbook section below:
- `ServiceDown` (page)
- `QueueBacklog` (ticket)
- `AIMetricsExporterDown` (ticket)
- `OpsScrapeTargetDown` (ticket)
- `OpsDemoKeySpendHigh` (ticket): **OPS-17**, real spend over 7 days above 80% of `DEMO_KEY_LIMIT_USD` (`.env`,
  default 3: the demo guide's $3 key).

**Budgets (OPS-17), from soft to hard:**
1. `AILLMSpendRateHigh` (page) and `AISkillCostHigh` (ticket), from AI-21.
2. `OpsDemoKeySpendHigh` against the demo key's limit.
3. AI's budget per skill, which stops a skill with `budget_exceeded` (`AIBudgetExceeded`).
4. The OpenRouter key's own credit limit, the hard stop.

There is no cloud cost. A codespace is capped by the GitHub account's $0 spending limit.

## Proving it works (the done-whens)

**AI-21 and OPS-10, "a test alert reaches the on-call":** `bash devops/monitoring/monitor.sh test`
1. Every group of `ai/ops/alerts.yaml` is loaded and healthy.
2. `AIAlertPipelineTest` fires in Prometheus and is in Alertmanager.
3. It lifts the silence and waits (up to 7 minutes, usually 1-2) until Alertmanager logs a successful
   delivery **of that alert's group**.
4. It silences the alert again, also on failure.
- You should see one loud `[TEST] AIAlertPipelineTest` message in the group.
- Delivery is read from Alertmanager's (debug) log, not from its counters. The counters only say "a Telegram
  message was sent", and another alert sent at the same moment passed for the test message in a dry run.

**OPS-17, "budget alert tested":** `bash devops/monitoring/monitor.sh test-cost`. **Run it on your laptop,
never in the demo codespace.**
- **What it logs:** a one-off container with no network logs, through AI's own code, 4 model calls of $5 each
  (`model ops-test/synthetic`, tokens set) and one budget stop. No model is called.
- **What must happen:** `AILLMSpendRateHigh` (page: $20 > $18.75 an hour) and `AIBudgetExceeded` (ticket) must
  fire and be delivered: one loud and one silent message.
- **Afterwards:** both resolve about an hour later. Real spend alerts are not silenced. The dashboards and
  `OpsDemoKeySpendHigh` leave `ops-test/*` out of real spend.
- **Why not in the codespace:** AI's 7-day drift rules still count the $20, so in a codespace it refuses unless
  `MONITOR_ALLOW_TEST_COST=1`.
- An alert that already fires (an earlier run) isn't expected again: Alertmanager doesn't repeat it within its
  interval, and `test-cost` says so.

**Checked without Telegram**, by pointing Alertmanager's `api_url` at a fake Telegram API in a dry run:
- both commands deliver;
- `[PAGE]` and `[TEST]` arrive loud and `[ticket]` silent;
- the messages are HTML-escaped and their runbook links are complete.

**Done-when proof, with the real bot (2026-11-25, laptop, real on-call Telegram group):**

| Ticket | Done-when | Command | Result |
|---|---|---|---|
| AI-21, OPS-10 | `ai/ops/alerts.yaml` loaded; a test alert reaches the on-call | `monitor.sh test` | Delivered: one loud `[TEST] AIAlertPipelineTest` message |
| OPS-17 | Budget alert tested | `monitor.sh test-cost` | `DELIVERED: AILLMSpendRateHigh AIBudgetExceeded -> Telegram`: a loud `[PAGE] AILLMSpendRateHigh` and a silent `[ticket] AIBudgetExceeded`; synthetic spend counted $20, tokens 10000 |

Run by hand, with the token and chat id in the shell only (`read -rs`), as described above.

## Runbooks (DevOps' alerts)
AI-21's alerts have theirs in [ai/docs/ai/runbook.md](../ai/docs/ai/runbook.md).

### ServiceDown
- **Means:** `api` or `web` runs but its health probe has failed for 2 minutes (`/health`, `/`).
- **Do:**
  1. `bash devops/demo/demo.sh status`, then `demo.sh logs api` (or `web`).
  2. Restart it with `docker compose ... restart api`, or rerun `demo.sh`.
  3. In the demo, if it keeps failing, switch to the laptop fallback (demo guide, section 7).
- **Note:** a **stopped** service isn't probed, so it doesn't fire this; `demo.sh status` shows it.

### QueueBacklog
- **Means:** more than 20 jobs have waited in an RQ queue for 10 minutes. The workers are down, stuck, or too
  few. The threshold is provisional until Backend's real load is known.
- **Do:**
  1. Check the worker (`demo.sh status`, `demo.sh logs worker`).
  2. Look at AI's latency and error panels in Grafana: slow model calls back the queue up.
  3. Start more worker processes if the load is real. AI's rate limits are per process.

### AIMetricsExporterDown
- **Means:** Prometheus can't scrape `ai-metrics` for 5 minutes, so **every AI alert is blind** (errors, spend,
  budget).
- **Do:**
  1. `bash devops/monitoring/monitor.sh logs ai-metrics docker-socket-proxy`, then `monitor.sh up`.
  2. A restart loses the events logged while it was down, and re-counts nothing.

### OpsScrapeTargetDown
- **Means:** another target (Alertmanager, redis-exporter, blackbox, Prometheus itself) has been down for 5
  minutes. Its alerts are blind.
- **Do:** `monitor.sh status`, `monitor.sh logs <service>`, `monitor.sh up`.

### OpsDemoKeySpendHigh
- **Means:** real model spend over the last 7 days is above 80% of `DEMO_KEY_LIMIT_USD`. The demo key is close
  to its credit limit, after which every live call fails.
- **Do:**
  1. Check the spend panels (by model) in *SkillForge AI: models and cost*.
  2. Before the demo, raise the key's limit in OpenRouter (and `DEMO_KEY_LIMIT_USD` in `.env`), or run the demo
     in fake mode (`DEMO_LLM_MODE=fake`).
  3. Spend lost while `ai-metrics` was down isn't counted. OpenRouter's own usage page is the truth.

### AIAlertPipelineTest
Not a failure. See AI's runbook. If it arrives outside `monitor.sh test`, its silence was lost (for example
after `demo.sh reset`): `monitor.sh up` silences it again.

## OPS-18: which runbooks this covers
OPS-18's done-when is "runbooks for the top 5 failure cases". OPS-18 still has to choose those 5. Here is what
this work gives it:

| Candidate failure case | Alert | Runbook |
|---|---|---|
| Every model in the chain fails (provider outage) | `AILLMAllModelsFailing`, `AILLMErrorRateCritical` (page) | AI's runbook |
| Model spend runs away | `AILLMSpendRateHigh` (page), `OpsDemoKeySpendHigh` | AI's runbook, above |
| Skills stop on their budget | `AIBudgetExceeded` | AI's runbook |
| The safety screen fails, so no request proceeds | `AISafetyUnavailable` (page) | AI's runbook |
| The API or web app stops answering | `ServiceDown` (page) | above |
| Jobs pile up in the queue | `QueueBacklog` | above |
| Monitoring itself is blind | `AIMetricsExporterDown`, `OpsScrapeTargetDown` | above |

**Still OPS-18's:**
- choosing the top 5;
- the on-call rotation: who is in the Telegram group, and when;
- a status page;
- an **external dead-man's switch**: if Alertmanager or Telegram delivery breaks, nothing here alerts. A free
  heartbeat service could watch for a periodic message.

Also missing: the database (no postgres exporter yet) and the API's error rate (waiting for Backend).

## Measured
On a laptop (Docker Desktop, WSL 2), with the whole demo running, from `docker stats --no-stream`: idle = 11 minutes
after a start; "after `test-cost`" was taken with Grafana still capped at 256 MB.

| Container | RAM, idle | RAM after `test-cost` | Cap (`mem_limit`) |
|---|---|---|---|
| prometheus | 55 MB | 50 MB | 300 MB |
| grafana | 247 MB | 234 MB | 512 MB |
| ai-metrics | 29 MB | 29 MB | 128 MB |
| docker-socket-proxy | 24 MB | 25 MB | 64 MB |
| alertmanager | 21 MB | 23 MB | 64 MB |
| blackbox | 18 MB | 13 MB | 32 MB |
| redis-exporter | 11 MB | 10 MB | 32 MB |
| **Total** | **≈0.40 GB** | **≈0.38 GB** | 1.1 GB |

- **Grafana 13** needs about 250 MB of memory on its own. A 256 MB cap kept it at the limit (812 reclaim events),
  hence 512 MB (0 limit events since).
- **In a 2-core codespace** (8 GB): the demo's ≈1.3 GB plus ≈0.4 GB is ≈1.7 GB. These are laptop numbers: the
  first codespace run should confirm them.
- **Disk:**
  - images about 2.7 GB (Grafana 2.0 GB, Prometheus 0.39 GB, Alertmanager 0.13 GB, the rest under 0.07 GB each);
  - data a few MB at first, capped at 1 GB for Prometheus (8 days kept, for AI's 7-day rules).
  - In a codespace this is billed storage.

## Files
- `devops/monitoring/compose.monitoring.yaml`: the services. Images are pinned by digest to releases at least
  14 days old. Every container has a memory cap, no capabilities and no-new-privileges. Every root filesystem is
  read-only except Alertmanager's (compose can't copy an environment secret into a read-only one).
- `prometheus.yml`, `rules/ops.yaml`, `blackbox.yml`.
- `alertmanager/`: the Telegram routes, the "off" variant, and the message template.
- `exporter/ai_log_exporter.py`, `metrics.extra.yaml`.
- `grafana/`: the data source and the two dashboards (change the JSON by pull request; the UI can't save).
- `monitor.sh`, `monitor_query.py`, `synthetic_ai_events.py`.
- `ci-checks.sh`, `tests/`: run by `.github/workflows/monitoring.yml`, and by you:
  `PYTHON=<ai/.venv's python> bash devops/monitoring/ci-checks.sh`.

**Versions to bump:** Grafana 13.3.2 (24 Nov 2026) fixes two CVEs. It can replace 13.3.1 from 8 Dec under the
14-day rule. The ports are local or Private.

## Troubleshooting
| You see | Do |
|---|---|
| `ONCALL_TELEGRAM_... is not set` | Set it in the shell (above), or add the Codespaces secret and restart the codespace. Without a channel: `MONITOR_ONCALL=off` |
| `environment variable "ONCALL_TELEGRAM_BOT_TOKEN" required by secret ... is not set` | You ran `docker compose` directly: use `monitor.sh`, or export both variables (empty is fine) |
| `test` says "not delivered" with failed attempts | `monitor.sh logs alertmanager`. A wrong token gives an auth error; a wrong chat id gives "chat not found"; the bot must be a member of the group |
| `test-cost` says SKIPPED: already firing | An earlier run's alerts still fire; run it again about an hour later |
| A dashboard is empty | `monitor.sh status`: is `ai-metrics` up? Real AI panels stay empty until Backend's worker logs AI's JSON lines |
| `[TEST]` messages every 5 minutes | The test alert's silence is gone: `monitor.sh up` |
