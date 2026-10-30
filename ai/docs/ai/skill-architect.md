# Skill Architect v0 (AI-07)

Owner: Track B, covered by the AI Lead. It is done when **at least 90% of the 103 test requests produce a valid SkillSpec**. That is measured live; there is no API key yet.

The Skill Architect turns a **screened** `AnalyzedRequest` (contract A3) into a valid `SkillSpec` (contract B1). v0 has no web knowledge yet, so `knowledge.references` and `sources` stay empty; AI-12 adds them.

```python
from core.agents import build_spec

result = await build_spec(analyzed, existing_names=registry_names, on_progress=callback)
if result.ok:
    spec = result.spec            # passed core.spec.validate_spec
else:
    result.issues                 # the last attempt's validation errors
```

## It refuses before any model call
| Situation | Error |
|---|---|
| `analyzed.safety is None` (not safety-screened) | `NotScreened`. Use `core.analysis.screen_and_analyze` first |
| `analyzed.needs_clarification` (open questions) | `NotReady`. Call `answer_questions_safely` first |

## The flow (LangGraph)
```
START → write → enforce → check ─(valid)─────────────────→ END  ok
          ↑                     ├(errors, attempt < 3)──→ write  (repair)
          └─────────────────────┘(errors, attempt = 3)──→ END  failed
```
- **`write`.**
  - **Attempt 1** uses the prompt `architect/generate`.
  - **Attempts 2 and 3** use `architect/repair`, with the previous draft and the validation issues as `path  code  message`.
  - The model is told to change only what the issues require.
  - **Two levels of repair.** The gateway already makes one repair attempt itself for replies that don't fit the SkillSpec field rules. If it still fails, the attempt counts as failed, and the loop goes on.
- **`enforce`.** These rules must never depend on the model. They are deterministic and idempotent:
  - **Identity:** `kind`, `domain` and `targets` come from the analysis; targets default to `[claude, codex]` when empty. `skill.name` comes from the analysis unless that name is already taken.
  - **One `must` guardrail per safety condition**, with a fixed id `safety-<condition>`, fixed wording, and this category:

    | Condition | Category |
    |---|---|
    | `authorized_use_only` | `scope` |
    | `no_operational_harm` | `safety` |
    | `professional_disclaimer` | `disclaimer` |
    | `crisis_resources` | `safety` |
    | `privacy_protection` | `privacy` |
    | `age_appropriate` | `safety` |

  - **High-risk domains** (legal, medical, finance) always get `safety-professional-disclaimer` and `safety-human-review`.
  - A model guardrail with one of these ids is replaced by ours.
- **`check`.** Runs `validate_spec(spec, existing_names=…)`. Errors fail the attempt; warnings are allowed.

**When it stops:**
- **Provider errors** raise `ArchitectUnavailable` (retry the job later).
- **A model refusal** raises `ArchitectRefused`.
- **Progress events** (`attempt`, `repairing`, `done` or `failed`, plus the attempt number) go to `on_progress`.

**Prompts and model.** The prompts are in `ai/prompts/architect/` (version 1). Their example spec is a synthetic `meeting-minutes` skill, not one of the test requests, and a test checks that it is valid. The model role is `architect`: Claude Sonnet 5.5, `max_tokens` 24000, timeout 300 s.

**Tracing is off.** LangGraph comes with LangSmith tracing, which the Architect switches off by default (`LANGSMITH_TRACING=false`), because traces would contain users' requests.

## Measuring it
```bash
cd ai
.venv/Scripts/python -m evaluation.architect check-data              # the 103 test requests
.venv/Scripts/python -m evaluation.architect run --set all --live    # REAL calls: about $10–20
```
- **The test requests:** the 3 example AnalyzedRequests, plus the 100 analyzer gate requests built **from their labels**. So the score measures the Architect alone. Vague requests count as "questions skipped".
- **End to end:** `--end-to-end` runs the real safety screen and analyzer first.
- **What a run writes:** `ai/evaluation/architect/runs/<UTC>/` (ignored by Git). It holds `report.md`, `report.json`, `predictions.jsonl` and **every generated spec** in `specs/`, for review by hand.
- **The report:** valid rate, first-try rate, the attempts histogram, the most common failure codes, safety-guardrail compliance and identity fidelity.
- **The gate:** exactly 103 requests, at least 90% valid. A fake run prints "does NOT count for AI-07", because the fake gives every request the same canned spec.

## Dependency note
LangGraph is pinned at `1.2.14`, published on 6 Oct 2026. `pyproject.toml` sets `[tool.uv] exclude-newer = "2026-10-10T00:00:00Z"`, so `uv lock` only picks releases at least two weeks old, for every package, including LangGraph's own dependencies. When you upgrade:
1. Move the date forward, keeping it at least two weeks behind today.
2. Run `uv lock`.
3. Run the full test suite, then the live tests.
