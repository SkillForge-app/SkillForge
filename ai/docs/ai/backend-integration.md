# Backend integration: running the AI pipeline in the worker (BE-06, BE-07)

For Backend, building the RQ worker that runs a skill's design. It covers how to install `ai/`, the three pipeline calls, what each result means for the worker, and a complete job function. The contract itself is [pipeline-interface.md](pipeline-interface.md) (`ai/core/pipeline/interface.py`, frozen: changes need AI and BE approval).

## 1. Install `ai/` from `backend/`

`ai/` is the Python project `skillforge`. It installs two top-level packages, `core` and `evaluation`, so Backend must not have packages with those names.

```toml
# backend/pyproject.toml
[project]
requires-python = ">=3.11.5"          # ai/ needs 3.11.5 (soupsieve 3); >=3.11 does not resolve
dependencies = [
    # ...Backend's own dependencies...
    "skillforge[pgvector]",           # pgvector: the production knowledge store
]

[tool.uv.sources]
skillforge = { path = "../ai", editable = true }
```

Or let uv write those lines, from `backend/`:

```bash
uv add --editable ../ai --extra pgvector
uv sync --locked
```

- **`backend/uv.lock` resolves `ai/`'s dependencies.** `ai/uv.lock` isn't used. The exact pins carry over: `litellm==1.104.2`, `langgraph==1.2.14` and `fastembed==0.9.1`.
- **If Backend sets `[tool.uv] exclude-newer`**, it must be 2026-10-25 or later: fastembed 0.9.1 was uploaded on 2026-10-24.
- **In the worker image,** keep `ai/` next to `backend/`, because the path is `../ai`.

## 2. The pipeline calls

```python
from core.pipeline import RealPipeline, FakePipeline, StepResult, ProgressEvent  # FakePipeline: BE tests
from core.analysis import AnalyzedRequest, Answer
from core.spec import SkillSpec

pipeline = RealPipeline()

await pipeline.analyze(text: str, *, selected_targets: Sequence[Target] = ()) -> StepResult[AnalyzedRequest]
await pipeline.clarify(analyzed: AnalyzedRequest, answers: Sequence[Answer]) -> StepResult[AnalyzedRequest]
await pipeline.design(analyzed: AnalyzedRequest, *, existing_names: Collection[str] = (),
                      on_progress: Callable[[ProgressEvent], None] | None = None) -> StepResult[SkillSpec]
```

- **`Target`** is `"claude" | "codex" | "chatgpt" | "generic"`.
- **`existing_names`** are the skill names already in the registry, so the Architect doesn't reuse one.
- **`on_progress`** is a plain (sync) function. It is called during `design` with `ProgressEvent(step, stage, attempt, message)`; `message` is safe to show.
- **Each step never raises for expected outcomes.** It returns a `StepResult`: `step`, `status`, `value`, `user_message` (safe to show), `error_code`, `issues`, `usage` (`calls`, tokens, `cost_usd`) and `pipeline_version`.
- **Store it** with `result.model_dump_json()`.

| `status` | `error_code` | What the worker does |
|---|---|---|
| `ok` | none | `analyze`/`clarify`: store `value` (an `AnalyzedRequest`) and enqueue `design`. `design`: `value` is the `SkillSpec`; hand it to the compilers (section 5) |
| `needs_input` | none (`analyze`, `clarify`) | Store `value` and show `value.questions` (3 to 5). When the user answers, enqueue `clarify` |
| `needs_input` | `open_questions` (`design`) | `value` is `None`: the request still has open questions. Run `clarify` first |
| `blocked` | `blocked.<category>`, e.g. `blocked.fraud_scams`; `blocked.other` from `design` | Show `user_message`. **No retry, no package** (BE-14) |
| `retry_later` | `provider_unavailable` | Re-enqueue the same step later, on purpose (section 3). Show `user_message` if it keeps happening |
| `failed` | `budget_exceeded` | The skill used up its model budget. Show `user_message`; don't retry |
| `failed` | `invalid_spec` (`design`) | No valid spec after 3 attempts; `issues` say why. Show `user_message` |
| `failed` | `not_screened` (`design`) | The `AnalyzedRequest` has no safety clearance: always pass the one `analyze`/`clarify` returned, from your own database |
| `failed` | `invalid_request` (`analyze`, `clarify`) | The input broke a rule (see "Input rules" below). No model was called. Show `user_message`; don't retry the same input |
| `failed` | `analysis_failed.<ErrorType>` | The analysis could not be used. Show `user_message` |

- **A step deadline shows as `retry_later` / `provider_unavailable`** for now.
  - **The deadlines:** each profile sets one per step (analyze and clarify 120 s, design 600 s). The step's calls are cut off at the deadline.
  - **Why the same code:** a separate code would need a change to the frozen interface. In the logs the cut-off calls have `error_type: "CancelledError"`.
- **`not_screened` is a safety rule.** Only an `AnalyzedRequest` that the pipeline returned to you carries a valid clearance. Never take one back from the browser.

## 3. The RQ job

- **Run the worker with the scheduler** (needed for `enqueue_in`): `rq worker --with-scheduler --url "$REDIS_URL" skills`.
- **One job per step:** `needs_input` waits for the user, so each step is its own job. The design job:

```python
# backend/app/worker/ai_jobs.py
import asyncio
from datetime import timedelta

from core.ops.settings import startup  # import core before anything imports litellm (section 4)
from core.llm import skill_run
from core.analysis import AnalyzedRequest
from core.pipeline import ProgressEvent, RealPipeline, StepResult
from core.spec import SkillSpec
from rq import Queue, get_current_job

startup()  # once per process: applies SKILLFORGE_ENV's profile (budgets, deadlines, limits)

DESIGN_JOB_TIMEOUT_S = 900          # above the 600 s design deadline; analyze/clarify jobs: 300
RETRY_DELAYS_S = (60, 300, 900)     # retry_later: three tries, then give up


def enqueue_design(queue: Queue, skill_id: str, attempt: int = 0, delay_s: int = 0) -> None:
    kwargs = {"job_timeout": DESIGN_JOB_TIMEOUT_S}  # no `retry=`: RQ never retries on its own
    if delay_s:
        queue.enqueue_in(timedelta(seconds=delay_s), design_job, skill_id, attempt, **kwargs)
    else:
        queue.enqueue(design_job, skill_id, attempt, **kwargs)


def design_job(skill_id: str, attempt: int = 0) -> None:
    rq_job = get_current_job()
    skill = load_skill(skill_id)  # Backend: your job row, with what AI returned earlier

    def on_progress(event: ProgressEvent) -> None:  # sync; called while design runs
        rq_job.meta["progress"] = event.model_dump()
        rq_job.save_meta()

    async def run() -> StepResult[SkillSpec]:
        # The budget covers the whole skill: pass what earlier steps cost. Since review fix F1
        # the profile's budget per skill ($1.50 in production) applies without `budget_usd`.
        with skill_run(skill_id, spent_usd=skill.cost_usd):
            return await RealPipeline().design(
                AnalyzedRequest.model_validate_json(skill.analyzed_json),
                existing_names=registry_names(),
                on_progress=on_progress,
            )

    result = asyncio.run(run())
    save_step(skill_id, result.model_dump_json(), cost_usd=result.usage.cost_usd)

    match result.status:
        case "ok":
            compile_packages(skill_id, result.value)  # BE-09
        case "retry_later" if attempt < len(RETRY_DELAYS_S):
            queue = Queue(rq_job.origin, connection=rq_job.connection)
            enqueue_design(queue, skill_id, attempt + 1, delay_s=RETRY_DELAYS_S[attempt])
        case "needs_input":  # design: error_code "open_questions", value None
            mark_waiting_for_answers(skill_id)
        case _:  # blocked, failed, or retry_later after the last try
            mark_finished(skill_id, result.status, result.error_code, result.user_message)
```

`load_skill`, `registry_names`, `save_step`, `compile_packages`, `mark_waiting_for_answers` and `mark_finished` are Backend's own code.

- **No automatic retries.** A model call costs money, and the gateway already retries transient errors and falls back to other models. A blind retry would pay for the same calls twice. `retry_later` is the only case to re-run, on purpose, with `enqueue_in`.
- **`job_timeout` must stay above the step deadline,** so the pipeline stops first and returns `retry_later` cleanly. RQ's timeout only catches a stuck job.
- **Analyze and clarify jobs** follow the same pattern, with `job_timeout=300`.
- **Input rules** (the same in `pipeline-interface.md`; checked before any model call, by `RealPipeline` and `FakePipeline`):
  - **`analyze`:** the text is 1 to 4000 characters after trimming spaces. A blank text or a longer one returns `failed` / `invalid_request` with no model call. Checking it in the API first saves a job, but isn't required.
  - **`clarify`:** answers only to the questions that were asked, at most one each. An answer to another question, or two answers to one question, returns `failed` / `invalid_request`.
  - **Skipping:** when the user skips everything, send either an empty list or one `Answer(question_id=q.id, text=None)` per question. Both mean every question was skipped. Skipping some questions is fine too: send only the answers you have.
- **Progress (BE-08):** `design` sends no closing progress event when it ends in `retry_later`, `blocked`, `failed/budget_exceeded` or `not_screened` (review F12). Treat the saved result as the end of the stream.

## 4. Environment and keys

| Variable | Value |
|---|---|
| `SKILLFORGE_ENV` | `production` or `staging`: picks the profile in `ai/core/ops/environments.yaml` |
| `OPENROUTER_API_KEY` | Required: the primary models |
| `ANTHROPIC_API_KEY` | Optional: the direct-API fallback hop for an OpenRouter outage (warning if missing) |
| `BRAVE_SEARCH_API_KEY` | Required by the startup check in staging and production |
| `SKILLFORGE_PGVECTOR_DSN` | DE's read-only user `skillforge_ai_reader` |
| `SKILLFORGE_PGVECTOR_TABLE` | `knowledge.knowledge_chunks` |
| `SKILLFORGE_MODEL_CACHE` | A volume with the embedding model: `python -m core.llm.local_embed download` at build or deploy time |
| `LITELLM_LOCAL_MODEL_COST_MAP` | `True`, only if a process imports `litellm` before anything from `core` |

- **Keys come from `ai/.env` through `env_file:` in compose,** or the platform's secret store. Never write them in `compose.yaml`, a Dockerfile or the image.
- **Check a worker's setup** without starting it: `python -m core.ops check --env production`. It names missing variables, never their values.
- **Import order (review F17):** importing anything from `core` sets `LITELLM_LOCAL_MODEL_COST_MAP=True`. Without it, LiteLLM downloads its price map from GitHub when it is imported: a network call with retries at startup, and unpinned prices. So import `core` first, as the job module above does, or set the variable in the worker's environment.
- **The full list of limits, budgets and logs** is in [production-config.md](production-config.md).

## 5. The output: a SkillSpec

- **What `design` returns:** on `ok`, `result.value` is a validated `SkillSpec` (B1).
  - **The schema:** `ai/core/spec/schema.json`; the fields are described in [skillspec.md](skillspec.md).
  - **Storing it:** `result.value.model_dump_json()`; read it back with `SkillSpec.model_validate_json(...)`.
- **The compilers (BE-09) turn it into packages,** one per platform in `spec.targets`.
  - For Claude, that's `.claude/skills/<spec.skill.name>/`: `SKILL.md`, plus `references/` (from `spec.knowledge.references`) and `templates/` (from each `spec.outputs[].template`).
