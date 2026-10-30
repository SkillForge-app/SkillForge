# AI pipeline interface (contract for BE-07 and BE-08)

These are the functions the backend worker calls. They live in `ai/core/pipeline/`, at version `0.1`.
- **Due:** Week 4 (about 20 Nov 2026).
- **Changes:** need a pull request that both the AI and BE leads approve.
- **Testing without a key:** use `FakePipeline`.

```python
from core.pipeline import RealPipeline, FakePipeline, StepResult

pipeline = RealPipeline()             # FakePipeline() in backend tests

r = await pipeline.analyze(text, selected_targets=["claude"])
# r.status == "needs_input": show r.value.questions; when the user answers:
r = await pipeline.clarify(r.value, answers)            # answers: list[core.analysis.Answer]
# r.status == "ok": start the design job
d = await pipeline.design(r.value, existing_names=registry_names, on_progress=send_sse_event)
# d.status == "ok": d.value is a valid SkillSpec, ready for the compilers (BE-09)
```

## The three steps
| Step | Input | Output `value` | What it does |
|---|---|---|---|
| `analyze` | request text, the platforms picked in the UI | `AnalyzedRequest` (A3) | The safety screen and the analysis run at the same time |
| `clarify` | the AnalyzedRequest, the answers (skipped is allowed) | `AnalyzedRequest` | Screens the request together with the answers, then re-analyzes. It never asks a second round |
| `design` | the AnalyzedRequest, the names already in the registry | `SkillSpec` (B1) | The Skill Architect: generate, validate, repair, at most 3 attempts |

## StepResult
Every step **returns** a `StepResult`; it never raises for an expected outcome. Store it as JSON with `result.model_dump_json()`, and read it back with `StepResult[SkillSpec].model_validate_json(...)`, or with `StepResult[AnalyzedRequest]` for `analyze` and `clarify`.

| Field | Meaning |
|---|---|
| `step` | `analyze`, `clarify` or `design` |
| `status` | See below |
| `value` | The result when `ok`, and also for `needs_input` (the AnalyzedRequest with its questions) |
| `user_message` | Safe to show the user. Set for `blocked`, `retry_later` and `failed` |
| `error_code` | For logs and metrics, e.g. `blocked.fraud_scams`, `provider_unavailable`, `invalid_spec`, `not_screened` |
| `issues` | Validation issues (`path`, `code`, `message`, `severity`). For a failed design they say why; for an ok design they are warnings |
| `usage` | `calls`, `input_tokens`, `output_tokens`, `cost_usd` for this step |
| `pipeline_version` | `"0.1"` |

| Status | What the worker does |
|---|---|
| `ok` | Continue with `value` |
| `needs_input` | Show `value.questions` (3 to 5). Then call `clarify` |
| `blocked` | Show `user_message`. **Start no job, store no skill** (BE-14) |
| `retry_later` | A provider or the safety screen was down. Retry the job later, and show `user_message` if it keeps failing |
| `failed` | No usable result, for example no valid spec after 3 attempts. Show `user_message`; `issues` say why |

## Progress events (BE-08)
`design(on_progress=…)` calls your function with a `ProgressEvent` (`step`, `stage`, `attempt`, `message`), in order:

```
started → attempt 1 → (repairing 2 → repairing 3) → done | failed
```

The `message` is short and safe to show, for example "Fixing problems in the design (attempt 2)".

## FakePipeline (for backend tests)
```python
fake = FakePipeline()                                   # every step returns "ok" with example data
fake.set("analyze", "needs_input")                      # value: an AnalyzedRequest with 4 questions
fake.set("analyze", "blocked", user_message="...", error_code="blocked.fraud_scams")
fake.set("design", "failed", error_code="invalid_spec")
fake.calls                                              # every call, in order
```
- **Data:** it returns the example AnalyzedRequests and SkillSpecs from `ai/examples/`.
- **Events:** it sends the same progress events as the real pipeline.
- **Pairing:** use it together with `SKILLFORGE_LLM_BACKEND=fake` when you also want the real pipeline code to run without a key.
