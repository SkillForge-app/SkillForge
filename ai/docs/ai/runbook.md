# AI services runbook (AI-21)

What each AI alert means and what to do. The rules are in `ai/ops/alerts.yaml` and the metrics they read in `ai/ops/metrics.yaml`. Both come from the metadata-only JSON logs (`core/ops/logs.py`), which never hold request or page text.
- **Severity:** `page` wakes the on-call (OPS-18); `ticket` goes to the AI team's queue; `test` only proves routing.
- **Escalation:** the AI lead. For provider accounts, keys and credits, DevOps (OPS-05, OPS-17).

## First checks for any AI alert
1. **Which role and model?** The labels on the alert. In the logs, look at `logger=skillforge.llm` records:
   - `model_role`, `model`
   - `fallback` (0 = the primary model)
   - `status`, `error_type`
   - `finish_reason`, `latency_ms`, `cost_usd`
2. **Is it the provider?** Check OpenRouter's status page and the account's credits. Then check Anthropic's status page.
3. **Did something change?** A deploy, a prompt version (`prompt_version` in the records), `ai/core/llm/models.yaml`, or `ai/core/ops/environments.yaml`.
4. **The startup check:** `python -m core.ops check --env production` on the host. It lists missing keys or a wrong backend without printing secrets.

## The levers
| Lever | How | Effect |
|---|---|---|
| Switch a role's model | `SKILLFORGE_MODEL_<ROLE>=<provider>/<model>` (e.g. `SKILLFORGE_MODEL_ARCHITECT=anthropic/claude-sonnet-5-5`), then restart | Bypasses a failing model or OpenRouter. Use only models with a `model_info` price in `models.yaml` |
| Direct-API hop | Set `ANTHROPIC_API_KEY` (secret manager) | Enables the last link of every chain, for an OpenRouter outage |
| Change a budget or rate limit | Edit `ai/core/ops/environments.yaml` (by PR), redeploy | Budgets are in USD per skill and per step; rate limits are per process |
| Pause ingest | Stop the DE-05 job | No new chunks enter the index |

---

### AILLMErrorRateHigh
- **Means:** more than 10% of one role's model attempts failed for 10 minutes. Retries and fallbacks usually hide this from users, but each failure costs latency, and fallbacks cost more.
- **Likely causes:** provider trouble (rate limits, 5xx); `MissingApiKey` (a key was removed); `LLMOutputInvalid` (a model or prompt change makes replies fail validation).
- **Do:**
  1. Group the errors by `error_type`.
  2. `RateLimitError`: lower the role's `requests_per_minute`, or ask DevOps to raise the provider limit.
  3. `LLMOutputInvalid`: compare `prompt_version` and the model with the last good period, and roll back.
  4. Missing key: restore the secret.

### AILLMErrorRateCritical
- **Means:** more than 25% of a role's attempts are failing. The chain may soon be exhausted.
- **Do:**
  1. Follow AILLMErrorRateHigh, but act now.
  2. If the primary model is the problem, switch the role to its first fallback with `SKILLFORGE_MODEL_<ROLE>`.

### AILLMAllModelsFailing
- **Means:** more than 5% of pipeline steps return `retry_later` / `provider_unavailable`: every model in a role's chain failed, so users' jobs are being retried.
- **Likely causes:** an OpenRouter outage with no `ANTHROPIC_API_KEY` for the direct hop; exhausted credits; a revoked key.
- **Do:**
  1. Check OpenRouter's status and credits.
  2. Set `ANTHROPIC_API_KEY` to enable the direct hop.
  3. If Anthropic is down too, post on the status page (OPS-18). Jobs are retried by BE.

### AIFallbackRateHigh
- **Means:** more than 5% of a role's attempts use a fallback model. Users are fine, but Opus costs about 2x Sonnet, so spend rises.
- **Do:**
  1. Find why the primary fails (AILLMErrorRateHigh).
  2. If it will last hours, decide with the AI lead: accept the cost, or temporarily switch the role.
  3. Watch AILLMSpendRateHigh.

### AILatencyHigh
- **Means:** p95 latency of a role (other than the architect) is above 30 s.
- **Likely causes:** provider slowness; retries with backoff; local rate limiting queueing calls (`max_wait_s`).
- **Do:**
  1. Check whether attempts per call rose (retries).
  2. Check whether the role's `max_concurrency` is saturated. If it is, raise it, or add workers.

### AIArchitectLatencyHigh
- **Means:** p95 Skill Architect call latency is above 180 s (its timeout is 300 s).
- **Do:**
  1. As for AILatencyHigh.
  2. Check `output_tokens`: long thinking or near `max_tokens` replies. AI-20 tunes `reasoning_effort`.

### AIUnpricedModel
- **Means:** successful calls logged `cost_usd: null`, so spend, budgets and cost alerts under-count.
- **Likely cause:** a role was switched to a model without a `model_info` price, and OpenRouter didn't report a cost.
- **Do:** add the model's price to `model_info` in `models.yaml` (from the provider's pricing page), or switch back.

### AILLMSpendRateHigh
- **Means:** model spend in the last hour is over 3x the hourly share of the daily budget ($150 / 24 × 3 = $18.75).
- **Likely causes:** a traffic spike; a fallback storm (Opus); a loop of repairs; abuse.
- **Do:**
  1. Split the spend by role and model (`skillforge_llm_cost_usd_total`), and steps by `skill_run`.
  2. For a fallback storm, see AIFallbackRateHigh.
  3. For abuse, BE rate-limits the users.
  4. Coordinate with OPS-17's budget alerts.

### AISkillCostHigh
- **Means:** p95 cost per skill is above $1.20 (80% of the $1.50 production budget). More skills will soon stop with `budget_exceeded`.
- **Do:**
  1. Look at the expensive runs' steps (`skillforge.pipeline` records by `skill_run`): many design attempts (repairs) or fallback models?
  2. Raise the budget only with the AI lead, by PR to `environments.yaml`.

### AIBudgetExceeded
- **Means:** skills stopped with `failed` / `budget_exceeded` in the last hour. Users saw "please narrow it down".
- **Do:**
  1. A few a day can be normal (huge requests).
  2. A burst means the cost per skill rose (see AISkillCostHigh), or BE passes a wrong `spent_usd`.

### AISkillCostDrift
- **Means:** the median cost per skill is 1.5x its 7-day level for an hour.
- **Likely causes:** a prompt or model change; more repairs; fallbacks.
- **Do:** compare `prompt_version`, models and attempts per design with last week, and roll back the change if it isn't intended.

### AISafetyUnavailable
- **Means:** more than 25% of safety-screen calls fail. Unscreened requests never proceed, so users get `retry_later`.
- **Do:**
  1. Treat it as AILLMErrorRateCritical for the `safety` role.
  2. **Never** bypass the screen.

### AISafetyBlockRateDrift
- **Means:** the share of blocked requests is more than 2x its 7-day level (at least 5 blocks in the hour).
- **Likely causes:** an attack wave or abuse; or a model or prompt change that over-blocks.
- **Do:**
  1. Split the blocks by `category` (`skillforge_safety_decisions_total`).
  2. One category spiking with normal traffic: likely abuse, so tell BE (rate limits) and the AI lead.
  3. All categories rising after a change: likely over-blocking, so check `prompt_version` and the model, and run the AI-06 evaluation.

### AIInjectionRejectionsSpike
- **Means:** pages rejected for prompt injection (`reason="injection"`, AI-19) in the last hour are over 3x the usual rate (at least 3).
- **Likely causes:** a crawled site started serving injections; a rule false-positive after a change to `injection_guard.py`.
- **Do:**
  1. Group the `skillforge.knowledge` `ingest_page` records by `host`.
  2. One host: pause crawling it (DE-04) and review its quarantine entries (codes and hashes, no text).
  3. Many hosts at once after a deploy: suspect a rule regression, and run `python -m evaluation.injection report --split dev`.

### AIDesignFailureDrift
- **Means:** design steps failing with `invalid_spec` are over 2x their 7-day rate.
- **Do:**
  1. Check the Architect's `prompt_version` and model.
  2. Check `validate_spec` changes (SkillSpec, Track B).
  3. Roll back the change if it isn't intended.

### AIQualitySamplingStopped
- **Means:** no published spec was sampled for the AI-16 judge in 24 h, despite 100+ designs.
- **Do:** check `quality_sample_rate` in the running profile (`SKILLFORGE_ENV`) and the `skillforge.quality` logger's shipping.

### AIAlertPipelineTest
- **Means:** nothing is wrong. This rule always fires, so DevOps can prove that AI alerts reach the on-call channel (OPS-10's done-when, and AI-21's).
- **Do:** confirm it arrived, then silence it.
