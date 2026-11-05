# LLM gateway, prompts and models

Owner: Track A (AI Lead). This page is Track A's part of AI-22.
It covers contracts **A1** (LLM gateway call) and **A2** (prompt file format and loader).

Every LLM call and every embedding in SkillForge goes through `core.llm`.
Do not call a provider SDK or LiteLLM directly. If you do, the call is not logged, has no cost tracking and cannot be faked in tests.

## Status

| Part | State |
|------|-------|
| `complete()` / `embed()` contract and `FakeGateway` | Ready (PR 1) |
| Prompt file format, loader, version lock | Ready (PR 1) |
| Real LiteLLM backend: retries, fallbacks, JSON repair, cost per call (AI-02) | Ready (PR 2). It is the default backend. Live check is pending an API key |

## Setup

All AI code (Track A and Track B) lives in `ai/`, which is its own project root. Run every command from there.

```bash
cd ai
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows; on macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest -q                   # never calls a real provider
```

`uv.lock` pins every dependency with file hashes. With [uv](https://docs.astral.sh/uv/) installed, `uv sync --extra dev` installs exactly those versions.

For real calls, copy `.env.example` to `.env` (gitignored) and fill in your keys. Real environment variables win over `.env`.

## Calling the model: `complete`

```python
from pydantic import BaseModel
from core.llm import complete

class Plan(BaseModel):
    title: str
    steps: list[str]

plan = await complete("architect/plan", {"request": text}, Plan)   # returns a Plan
```

- `prompt_id` names a prompt file: `"architect/plan"` is `prompts/architect/plan.md`.
- `inputs` must match the prompt's declared `inputs` exactly. A missing or extra key raises `PromptInputError`.
- `output_model` is a Pydantic model. You always get back a validated instance of it.
- `model_role="..."` (optional) overrides the prompt's `model_role` for this one call.
- In scripts, use `complete_sync(...)`. In notebooks and async code, use `await complete(...)`.

## Embeddings: `embed`

```python
from core.llm import embed

vectors = await embed(["first passage", "second passage"])   # list[list[float]]
```

- You get one vector per text, in the same order.
- Each vector has the `dimensions` of the `embedding` role, currently **384**. pgvector columns (DE-02) are sized from this number, so changing it is a contract change.
- **Vectors are unit length.** The `embedding` role is a local model (`local/BAAI/bge-small-en-v1.5`, chosen in AI-11). It needs no key and costs nothing per call. A search query should get the role's `query_prefix` in front; `RealRetriever` does this.
- `embed([])` returns `[]`. An empty or blank text raises `LLMInputError`.
- In scripts, use `embed_sync(...)`.

## Errors

Every error is a subclass of `LLMError`. Catch the most specific one you can handle.

| Error | When |
|-------|------|
| `PromptNotFound` | No prompt file for that id, or the id is malformed |
| `PromptFormatError` | The prompt file itself is broken. Tests catch this |
| `PromptInputError` | `inputs` do not match the prompt's declared inputs |
| `LLMInputError` | Other bad caller input, e.g. a blank text to embed, or a prompt longer than the environment's `max_input_chars` (AI-21) |
| `ConfigError` | Unknown model role, bad `models.yaml`, unknown backend |
| `LLMOutputInvalid` | The output did not validate against `output_model`, even after one repair attempt. Also raised when the reply was cut off at `max_tokens` |
| `LLMRefused` | The model, and every fallback, declined the request (e.g. a safety refusal). It is a subclass of `LLMOutputInvalid`, so existing handlers still catch it |
| `LLMUnavailable` | Every model failed: timeout, rate limit, outage, bad key. It comes after retries and fallbacks. The message names the last error type; the original provider exception is chained as `__cause__`. Also raised when the local rate limit gives no slot within `max_wait_s` (AI-21) |
| `BudgetExceeded` | The skill run's cost budget is used up (AI-21): no further model call is made. The pipeline returns `failed` with `error_code="budget_exceeded"` |

Error messages never contain prompt text, inputs or model output.
A chained provider exception (`__cause__`) can. If you log tracebacks of `LLMUnavailable`, treat them as sensitive.

## How the real gateway handles a call

`LiteLLMGateway` (`core/llm/litellm_gateway.py`) handles each `complete` call like this:

1. It tries the role's `model`, then each of its `fallbacks`, in order.
   - **Before every attempt (AI-21):** it checks the skill's cost budget, which raises `BudgetExceeded`, and takes a slot from the role's rate limit.
   - **`max_tokens`** is capped by the environment's `max_output_tokens`.
2. **Transient errors are retried on the same model**, `num_retries` times, with exponential backoff. These are timeouts, rate limits, connection errors and 5xx responses.
3. **Other provider errors skip straight to the next fallback.** These are a bad key, a bad request or an unknown model. Retrying them would fail the same way.
4. **A refusal** moves to the next fallback. If every model refuses, you get `LLMRefused`.
5. **A reply cut off at `max_tokens`** raises `LLMOutputInvalid` at once.
6. **A reply that does not match `output_model`** gets one repair attempt: the bad reply and the validation errors are sent back. If that also fails, you get `LLMOutputInvalid`.

LiteLLM's own retries are turned off, so every attempt is logged and its cost counted.
`embed` sends texts in batches of 128 with the same retry rules.

## Writing a prompt file

Path: `prompts/<area>/<name>.md`. Track A owns `analysis/` and `knowledge/`; Track B owns `architect/` and `writers/`.

```markdown
---
id: architect/plan              # must equal the path without .md
version: 1                      # bump on EVERY content change
model_role: default             # a role from core/llm/models.yaml
description: Turn an analysed request into a skill plan
inputs: [request, passages]     # every variable the template uses, nothing more
---
# system
You design agent skills. ...

# user
Request:
{{ request }}

{% for p in passages %}[{{ loop.index }}] {{ p }}
{% endfor %}
```

Rules:
- The lines `# system` (optional) and `# user` are reserved. They split the file into chat messages.
- Other headings (`## Example`) are plain text inside a section.
- Sections are Jinja2 templates. A variable that is used but not declared, or declared but not used, fails at load time. So does a syntax error.
- Input values are inserted as plain text. Template syntax inside a value is not executed.

### Version lock: every change needs a version bump

`prompts/prompts.lock.json` stores the version and hash of every prompt. A CI test (`tests/llm/test_prompts.py`) fails when a prompt changed but its version did not, or when the lock is out of date.

```bash
# after editing a prompt and bumping its version:
python -m core.llm.prompt_lock --update     # rewrite the lock (refuses if a version was not bumped)
python -m core.llm.prompt_lock             # check only
```

Commit the prompt and the lock file together. The PR diff then shows both the new text and the version change.

## Model roles

Code and prompts ask for a **role**, never a model name. Roles live in `core/llm/models.yaml`.

| Role | Used for | Model (via OpenRouter) |
|------|----------|---------------|
| `default` | Anything without a better role | `openrouter/anthropic/claude-sonnet-5.5` |
| `analysis` | Request Analyzer (AI-05) | `openrouter/anthropic/claude-sonnet-5.5` |
| `safety` | Safety screening (AI-06) | `openrouter/anthropic/claude-sonnet-5.5` |
| `architect` | Skill Architect (AI-07) | `openrouter/anthropic/claude-sonnet-5.5` |
| `extraction` | Cheap, high-volume work on scraped pages | `openrouter/anthropic/claude-haiku-5.5` |
| `judge` | LLM-as-judge in evaluation (AI-16) | `openrouter/anthropic/claude-sonnet-5.5` |
| `embedding` | Gap Checker, retrieval (AI-08, AI-11) | `local/BAAI/bge-small-en-v1.5`, 384 dims, local (no key) |

To switch one role without editing the file, set `SKILLFORGE_MODEL_<ROLE>=<provider>/<model>`, e.g. `SKILLFORGE_MODEL_EXTRACTION=anthropic/claude-haiku-5-5`.

### Fallback chains (AI-21)
| Roles | Chain |
|---|---|
| default, analysis, safety, architect, judge | `openrouter/anthropic/claude-sonnet-5.5` → `openrouter/anthropic/claude-opus-5.5` → `anthropic/claude-sonnet-5-5` |
| extraction | `openrouter/anthropic/claude-haiku-5.5` → `openrouter/anthropic/claude-sonnet-5.5` → `anthropic/claude-haiku-5-5` |
| embedding | none (not allowed) |

- **Never a weaker model.** Safety and spec quality don't drop during an incident. A fallback costs more: Opus is about 2x Sonnet, and `AIFallbackRateHigh` watches the rate.
- **The last hop is Anthropic's own API**, for an OpenRouter outage. It needs `ANTHROPIC_API_KEY`. Without the key it is skipped: it is logged as `MissingApiKey` and makes no request.
- **OpenRouter already fails over** between hosting providers for one model. These chains are for model-level and OpenRouter-level failures.
- **Every `CallRecord` has `fallback`:** the link that answered, where 0 is the primary.
- **Tests:** `tests/llm/test_production_limits.py` checks the chains: every link is priced, the first fallback costs at least as much as the primary, and the last hop is direct.

### Providers and keys
- **Claude goes through OpenRouter.**
  - The key is `OPENROUTER_API_KEY`, kept in `ai/.env`.
  - OpenRouter ids use dots (`anthropic/claude-sonnet-5.5`). They were checked on `openrouter.ai/api/v1/models` on 2026-10-24.
  - The same models through Anthropic's own API are listed under each role as a commented `# direct:` line (`anthropic/claude-sonnet-5-5`), with the key `ANTHROPIC_API_KEY`.
- **Embeddings run locally** (AI-11). A `local/<model>` role runs in-process on CPU with fastembed (ONNX, no torch), so it needs no API key.
  - **Pins:** its `local:` block pins the files: the Hugging Face `repo`, the `revision` (a full commit, never a branch), the model `file` and its `sha256`.
  - **Files:** they are downloaded once into `SKILLFORGE_MODEL_CACHE` (default `ai/.data/models`) and checked before every load. A mismatch raises `ConfigError`.
  - **Fetch ahead of time** (for example in a Docker build) with `python -m core.llm.local_embed download`.
  - **Hosted alternative:** `openai/text-embedding-3-small` with `OPENAI_API_KEY` (OpenRouter has no embedding models). Changing the embedding model means rebuilding the knowledge index.
- **Missing keys are caught early.** A missing key fails at once with `LLMUnavailable` ("last error MissingApiKey"), before any network call.
- **Keep keys safe.** Never commit them. Until OPS-05 sets up shared secrets, use your own key in a local `ai/.env` (see `.env.example`).

### Cost tracking
1. **First choice: OpenRouter's own figure.** OpenRouter reports what it actually billed for each call (LiteLLM asks for it). The gateway uses that figure first. It is exact, including caching and reasoning tokens.
2. **Fallback: our registered prices.** Otherwise the gateway prices the call from `model_info` in `models.yaml`. There are entries for the OpenRouter names and for the direct Anthropic names, and the provider is passed explicitly, so an OpenRouter reply is never priced as a direct one.
3. **A zero for a paid call is treated as unknown.** If LiteLLM returns $0 for a call that used tokens, `cost_usd` is null and a warning is logged.

Role fields: `model`, `fallbacks`, `num_retries`, `timeout_s`, `max_tokens`, `reasoning_effort` (low to max), `temperature`; for embedding roles only, `dimensions`, `query_prefix`, and `local` (the pins, required for a `local/` model).

- **Claude 5.5 roles have no `temperature`.** Sonnet 5.5 and Haiku 5.5 reject any non-default value with a 400 error, and LiteLLM refuses it before sending.
- **`max_tokens` is 16000.** These models think before answering, and the thinking counts toward `max_tokens`.
- **`reasoning_effort` is the cost lever.** AI-20 will tune it per role.
- **Embedding roles cannot have `fallbacks`.** Vectors from another model are not comparable, and would silently corrupt the pgvector index. `models.yaml` fails to load if you try.

### `model_info`: prices and capabilities LiteLLM does not know yet

The pinned LiteLLM version has no entry for `claude-sonnet-5-5` or `claude-haiku-5-5`. The `model_info` block in `models.yaml` registers their prices and capability flags when the gateway starts. Without it, cost cannot be computed, and LiteLLM might send parameters these models reject.

When you add a model that LiteLLM does not know, add an entry there. Copy the flags from a similar model in LiteLLM's map. `tests/llm/test_litellm_gateway.py::test_litellm_builds_a_valid_claude_request` checks the request LiteLLM builds.

### Upgrading LiteLLM

LiteLLM has had compromised PyPI releases, so `pyproject.toml` pins one exact version, and `uv.lock` pins its file hashes. To upgrade:

1. Pick a release that has been on PyPI for **at least two weeks** and is not yanked.
2. Change the pin and run `uv lock`.
3. Run the full test suite, then `pytest -m live`.
4. Check whether LiteLLM now knows our `model_info` models. If it does, compare its flags with ours.

## Testing with the fake

`FakeGateway` makes no network calls. It still loads and renders the real prompt file, so a broken prompt or wrong inputs fail your test just as they would in production.

```python
import pytest
from core.llm import FakeGateway, LLMUnavailable, use_fake

@pytest.fixture
def fake():
    with use_fake() as gateway:          # installs the fake, restores the old gateway after
        yield gateway

async def test_plan(fake):
    fake.register("architect/plan", {"title": "Data analyst", "steps": ["..."]})
    plan = await build_plan(...)                     # your code calls complete(...)
    assert fake.calls[0].inputs["request"] == "..."  # inspect what was sent

async def test_provider_down(fake):
    fake.register_error("architect/plan", LLMUnavailable("down"), times=1)  # fail once, then answer
    ...
```

The fake answers `complete` in this order:
1. A registered error, `fake.register_error(prompt_id, exc, times=n)`. Leave out `times` to raise on every call.
2. A registered output, `fake.register(prompt_id, dict_or_model)`.
3. A fixture file, `tests/fixtures/llm/<prompt_id>.json`.
4. Otherwise it raises `FakeOutputMissing`.

A canned output that does not match your `output_model` raises `LLMOutputInvalid`, like the real gateway would.

**Production behaviour in the fake (AI-21):**
- `fake.fail_model(model, times=n)` makes a model fail. `complete` then walks the role's real chain from `models.yaml`, logs an error `CallRecord` for each failing link, and answers from the first working one (`fallback=n`, one `call_id`). If every link fails, it raises `LLMUnavailable`.
- `FakeGateway(cost_usd=0.40)` makes every answer cost that much, so skill budgets can be tested.
- The skill budget and the input-size cap apply exactly as in the real gateway.

The fake's `embed` returns deterministic unit vectors computed from a hash of each text. The same text always gives the same vector on every machine, but similar texts do **not** get similar vectors. To fail embedding calls, use `fake.register_error("embed", ...)`.

You can also select the fake for the whole process with `SKILLFORGE_LLM_BACKEND=fake`.

## Logging and cost

Each attempt logs one JSON line on the `skillforge.llm` logger: a retry, a fallback, a repair round or an embedding batch. All attempts of one `complete` or `embed` call share the same `call_id`.

```json
{"call_id": "…", "kind": "complete", "prompt_id": "architect/plan", "prompt_version": 1,
 "model_role": "default", "model": "openrouter/anthropic/claude-sonnet-5.5", "input_tokens": 812,
 "output_tokens": 240, "n_texts": null, "cost_usd": 0.0040, "finish_reason": "stop",
 "latency_ms": 2140.3, "status": "ok", "error_type": null, "attempt": 1,
 "fallback": 0, "skill_run": "job-42"}
```

AI-21 added two fields:
- `fallback`: the position in the role's chain, where 0 is the primary.
- `skill_run`: the id from `skill_run(...)`, so cost per skill can be summed across steps.

Both are additive changes to contract A1, for Track B to approve.

Failed attempts that still got a reply (for example an invalid JSON reply) keep their tokens and cost. So you see, and count, everything that was paid for.

**Metadata only.** The log never contains prompt text, inputs, embedded texts, model output or error messages.
`CallRecord` rejects unknown fields, and `tests/llm/test_logging_privacy.py` fails if any content reaches the log.

To get the cost of a whole run, for example one skill generation, wrap it in `track_usage()`:

```python
from core.llm import track_usage

with track_usage() as usage:
    await generate_skill(...)
print(usage.calls, usage.input_tokens, usage.output_tokens, usage.cost_usd)
```

**A cost budget for a whole skill (AI-21):** `skill_run`. It is built on `track_usage`, and it also puts the id on every `CallRecord` in the block.

```python
from core.llm import skill_run

with skill_run(job.skill_id, spent_usd=job.cost_so_far, budget_usd=1.50) as run:
    result = await pipeline.design(analyzed)       # failed / budget_exceeded once it is used up
print(run.total_usd)
```

- **Leave out `budget_usd`** and the environment's budget applies (see [production-config.md](production-config.md)).
- **When it stops:** once spent plus this block's cost reaches the budget, the next attempt raises `BudgetExceeded` before calling. A call already running finishes and is counted, so at most one call overruns.

## Live tests

`tests/llm/test_live.py` calls the real providers and costs a few cents. These tests **never run in the normal test run**, because `pyproject.toml` sets `-m 'not live'`. Run them on purpose:

```bash
.venv/Scripts/python -m pytest -m live -v
```

Each one is also skipped when its key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) is missing. The Claude test checks AI-02's "done when": one log line with model, tokens and `cost_usd`.

## Changing these contracts

The `complete` / `embed` signatures, the prompt file format, the error classes and the `embedding` dimensions are contracts A1 and A2.
They change only by a PR that both Track A and Track B approve.
