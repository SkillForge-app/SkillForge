# Production configuration of the AI services (AI-21, for BE, DevOps and Track B)

This covers how the AI services run in dev, staging and production: environments and the startup check, model fallbacks, cost and rate limits, and the logs, metrics and alerts that OPS-10 loads. The code is in `ai/core/ops/` and `ai/core/llm/`; the alert artifacts are in `ai/ops/`. What each alert means: [runbook.md](runbook.md).
- **Task (AI tasks plan, P4):** "Production model config: fallbacks, rate limits, sampled quality monitoring, drift alerts".
- **Done-when:** "Alerts reach on-call". That needs OPS-10 to load `ai/ops/alerts.yaml` and route it. The always-firing `AIAlertPipelineTest` rule is there to prove it.

## Environments
**One variable picks the profile:** `SKILLFORGE_ENV=dev|staging|production`. Unset means `dev`; an unknown value is a `ConfigError`. The profiles are in `ai/core/ops/environments.yaml`.

| | dev | staging | production |
|---|---|---|---|
| LLM backend | litellm | litellm | litellm |
| Retriever | real | real | real |
| Vector store | local file index | pgvector | pgvector |
| Search | fake (recorded results) | brave | brave |
| Budget per skill | $5.00 | $3.00 | $1.50 |
| Budget per step without a `skill_run` (analyze / clarify / design) | $1 / $1 / $4 | $0.50 / $0.50 / $2 | $0.25 / $0.25 / $1 |
| `max_output_tokens` cap / `max_input_chars` | 32,000 / 400,000 | 32,000 / 200,000 | 32,000 / 200,000 |
| Concurrency / requests per minute, per role and process | 4 / 30 | 8 / 60 (architect 4 / 30) | 8 / 60 (architect 4 / 60) |
| Quality sample rate | 0 | 1.0 | 0.05 |
| Daily spend for the alert | $20 | $30 | $150 |

The budgets and limits are **provisional** until AI-20 measures the real cost per skill and the traffic. Change them in `environments.yaml` by PR, with the reason.

**At startup (BE worker, API process):**
```python
from core.ops.settings import startup
startup()     # applies SKILLFORGE_ENV's profile; raises StartupError in staging/production on errors
```
- **Defaults, not overrides.** `apply_environment()` sets the profile's backend variables as defaults (`SKILLFORGE_LLM_BACKEND`, `SKILLFORGE_RETRIEVER`, `SKILLFORGE_VECTOR_STORE`, `SKILLFORGE_SEARCH`), so a variable that is set explicitly wins. It then installs the limits and the sample rate.
- **From a shell or a deploy step:** `python -m core.ops check [--env production]`. It exits 1 on errors and reads `ai/.env` like the gateway does.

**What the check refuses** (production; staging treats fakes and the direct key as warnings; dev only warns):
- **Fake backends:** a fake LLM, retriever or search backend, or the local vector store.
- **Missing settings:** `SKILLFORGE_PGVECTOR_DSN`, `BRAVE_SEARCH_API_KEY`, or the primary models' key (`OPENROUTER_API_KEY`).
- **A chat role without fallbacks.**
- **The local embedding model:** missing, or not matching its pinned sha256 (`python -m core.llm.local_embed download`).
- **The prompt lock** is not current.

**Warning only:** a missing `ANTHROPIC_API_KEY`, because then there is no direct-API hop for an OpenRouter outage.

**Problems name variables, never their values.**

## Model fallbacks
- **The chains:** in `core/llm/models.yaml`; the table is in [models-and-gateway.md](models-and-gateway.md#fallback-chains-ai-21).
  - Sonnet roles → Opus (OpenRouter) → Sonnet via Anthropic's API.
  - Haiku → Sonnet → Haiku via Anthropic's API.
  - Never a weaker model.
- **Retries:** the gateway retries transient errors on the same model with backoff, then moves down the chain. A refusal or a non-transient error moves on at once.
- **Logging:** every attempt is a `CallRecord` with `fallback` (0 = primary), so the fallback rate is a metric.

## Cost and rate limits
**Per call:**
- `max_tokens` is the smaller of the role's value and `max_output_tokens`.
- A rendered prompt over `max_input_chars` raises `LLMInputError` before any call.

**Per skill: for BE.** Wrap **each step of one job** in `skill_run`. Pass what the earlier steps cost; it is in each `StepResult.usage.cost_usd`.

```python
from core.llm import skill_run

with skill_run(job.id, spent_usd=job.cost_so_far):          # budget: the environment's
    result = await pipeline.design(analyzed, existing_names=names)
job.cost_so_far += result.usage.cost_usd
```

- **Without `skill_run`,** each step gets the environment's per-step budget.
- **When the budget is used up,** the next model attempt raises `BudgetExceeded`. The step returns status `failed`, `error_code="budget_exceeded"` and a user message.
- **Overrun:** a call already running finishes, so at most one call overruns.
- **Retrying won't help.** It is not `retry_later`, and the safety screen passes it through instead of reporting "safety unavailable".

**Rate limits** apply per role, per process: `max_concurrency` at once and `requests_per_minute` in a rolling minute.
- **Waiting:** a call waits for a slot up to `max_wait_s` (30 s). After that it raises `LLMUnavailable`, which the pipeline turns into `retry_later`.
- **Workers multiply them:** N workers allow N times the limit, so size the numbers to the deployment.
- **Provider 429s** are retried with backoff anyway.

## Logs, metrics and alerts (for OPS-10)
**Logs.** Every log is metadata-only JSON, never text. To ship them, install the JSON-lines formatter once:
```python
import sys
from core.ops.logs import install_json_logs
install_json_logs(sys.stdout)
# {"ts": "...", "level": "INFO", "logger": "skillforge.pipeline", "record": {...}}
```

| Logger | Record | One per |
|---|---|---|
| `skillforge.llm` | `CallRecord`: role, model, `fallback`, status, `error_type`, tokens, `cost_usd`, `latency_ms`, `skill_run` | model attempt |
| `skillforge.safety` | verdict, category, conditions, prompt version | safety decision |
| `skillforge.pipeline` | `StepEvent`: step, status, `error_code`, calls, `cost_usd`, `latency_ms`, `skill_run`, `skill_cost_usd` | pipeline step |
| `skillforge.knowledge` | `IngestPageEvent`: host, verdict reasons (e.g. `injection`), chunks, quarantined; `LLMScreenEvent`: screened, flagged | ingested page; LLM-screen batch |
| `skillforge.quality` | `QualitySampleEvent`: `skill_run`, sample rate | sampled published spec |

**Metrics.** `ai/ops/metrics.yaml` defines each metric:
- the logger and filter it reads
- the field that gives its value, and the fields that become labels
- the buckets, for histograms

`python -m core.ops.metrics <log.jsonl>` applies exactly those rules to a log file, so the collector's mapping can be checked against it.

**Alerts.** `ai/ops/alerts.yaml` holds the Prometheus rule groups.
- **Labels:** `severity` is `page`, `ticket` or `test`, and `team` is `ai`.
- **Annotations:** `summary`, `threshold`, and `runbook_url`, an anchor in [runbook.md](runbook.md). Prefix `runbook_url` with the repository URL when loading.
- **Checking:** `promtool check rules ai/ops/alerts.yaml`.

| Alert | Severity | Fires when |
|---|---|---|
| AILLMErrorRateHigh / AILLMErrorRateCritical | ticket / page | a role's attempt error rate is above 10% for 10 min / above 25% for 5 min |
| AILLMAllModelsFailing | page | more than 5% of steps are `retry_later` / `provider_unavailable` |
| AIFallbackRateHigh | ticket | more than 5% of a role's attempts use a fallback |
| AILatencyHigh / AIArchitectLatencyHigh | ticket | p95 latency is above 30 s / above 180 s |
| AIUnpricedModel | ticket | a call has an unknown cost |
| AILLMSpendRateHigh | page | spend in 1 h is more than $18.75 (3 × $150 / 24) |
| AISkillCostHigh | ticket | p95 cost per skill is above $1.20 (80% of the budget) |
| AIBudgetExceeded | ticket | any `budget_exceeded` in 1 h |
| AISkillCostDrift | ticket | the median cost per skill is 1.5x its 7-day level |
| AISafetyUnavailable | page | the safety role's error rate is above 25% |
| AISafetyBlockRateDrift | ticket | the block rate is 2x its 7-day level (and at least 5 blocks) |
| AIInjectionRejectionsSpike | ticket | `injection` page rejections are 3x their 7-day rate (and at least 3) |
| AIDesignFailureDrift | ticket | `invalid_spec` designs are 2x their 7-day rate (and at least 3) |
| AIQualitySamplingStopped | ticket | no quality sample in 24 h despite 100+ designs |
| AIAlertPipelineTest | test | always: it proves routing to on-call |

**The drift alerts** compare the last hour with a 7-day baseline, so they only become meaningful after a week of production data. The tests (`tests/ops/test_ops.py`) check that:
- the rules are well formed
- every metric they use is defined and reads fields that exist
- every runbook link exists
- the cost thresholds match the production profile
- simulated incidents (a primary-model outage, a used-up budget, costly skills) cross the matching thresholds

## Quality sampling
- **Sampling:** a published spec (design `ok`) is sampled at the profile's `quality_sample_rate`, deterministically from its `skill_run` id (or the skill name). A sampled spec gets a `QualitySampleEvent`.
- **Judging:** the AI-16 judge (Track B) picks the samples up later; until then they are only counted.
- **Rates:** production samples 5%, staging everything.

## Contract notes (not committed; for the PRs)
- **`core/pipeline/interface.py` (AI + BE):**
  - It now catches `BudgetExceeded` and returns `failed` / `budget_exceeded`.
  - It applies the per-step budget when BE opened no `skill_run`.
  - It logs one `StepEvent` per step, and samples published specs.
  - The signatures and the statuses are unchanged. `budget_exceeded` is a new `error_code` value.
- **`CallRecord` (contract A1, Track A + B):** two new optional fields, `fallback` and `skill_run`.
- **`core/analysis/safety.py`:** a `BudgetExceeded` passes through the screen unchanged, instead of becoming `SafetyUnavailable`.
