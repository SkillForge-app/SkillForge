# Request Analyzer (AI-05) and AnalyzedRequest (contract A3)

Owner: Track A. The A3 draft is due **6 Nov 2026**, and it is **frozen on 13 Nov 2026**. AI-05 is done when kind, domain area and risk are **each at least 90% correct** on the 100-request gate set.

The Request Analyzer turns what a user types ("I need a recruiter skill") into an **AnalyzedRequest**:
- **Who uses it:** the Skill Architect reads it (AI-07, Track B), the backend stores it, and the frontend's clarify step shows its questions (FE-08).
- **Shared vocabularies:** kind, domain area, risk and targets come from `core.spec`, so requests, benchmark labels and SkillSpecs always agree.

## Using it

```python
from core.analysis import analyze_request, answer_questions, Answer

analyzed = await analyze_request(text, selected_targets=["claude"])    # first pass
if analyzed.needs_clarification:
    # FE shows analyzed.questions (3 to 5); the user may skip any of them
    analyzed = await answer_questions(analyzed, [Answer(question_id="q1", text="...")])
architect_input = analyzed                                               # A3, never asks twice
```

- **No API key needed:** with `SKILLFORGE_LLM_BACKEND=fake`, the FakeGateway answers with `tests/fixtures/llm/analysis/request.json`.
- **Samples for AI-07:** three hand-written AnalyzedRequests are in `ai/examples/analyzed-request/`. One of them shows a full question-and-answer round.

## AnalyzedRequest fields
| Field | Meaning |
|---|---|
| `request` | The user's text, as typed |
| `kind` | `role`, `task` or `workflow` (`core.spec.Kind`) |
| `domain` | `<area>/<sub-area>`. The area comes from `core.spec.DOMAIN_AREAS`, and the property `domain_area` returns it |
| `risk` | `low`, `medium` or `high` (`core.spec.RiskLevel`) |
| `targets` | Platforms picked in the UI plus platforms named in the text, in `TARGETS` order. `[]` means not chosen yet |
| `audience`, `expected_outputs` | Extracted from the request. They may be empty |
| `skill_name`, `summary` | A suggested kebab-case name, and a one-sentence restatement in English |
| `needs_clarification`, `questions` | If the request is vague: `true` plus 3 to 5 questions (`id` q1 to q5, `text` in the request's language, and `about`, one of audience, outputs, platforms, scope, tone, constraints or domain) |
| `answers` | After the second pass: one entry per answered question. `text: null` means the user skipped it |
| `analyzer` | The `prompt_id` and `prompt_version` that produced the analysis |

**Rules:**
- `needs_clarification: true` means open questions and no answers yet.
- Questions without answers mean `needs_clarification` is `true`.
- An answer must refer to a question that was asked.

The JSON Schema for BE and FE is `ai/core/analysis/analyzed_request.schema.json`. Update it with `python -m core.analysis export-schema`; CI checks that it is current.

## Rules applied in code, not left to the model
- **Risk:** `high` exactly for the `legal`, `medical` and `finance` areas. A `high` anywhere else becomes `medium`. These are the same rules as the labels (`evaluation/analyzer/LABELLING.md`).
- **Targets:** UI choice plus platforms the text names, with no duplicates.
- **After answers:** questions are kept, answers are stored, and `needs_clarification` becomes `false`. The analyzer never asks a second round.
- **Prompt input:** the vocabularies are passed in from `core.spec`, so the prompt can't drift from the contract. The user's text is wrapped in `<request>` tags and treated as data.

The prompt is `ai/prompts/analysis/request.md`, version 1, role `analysis` (Claude Sonnet 5.5). Its 3 few-shot examples come from the **dev set** only.

Safety screening of harmful requests is AI-06 (`safety.py`). It is not part of this analyzer.

## Labelled data (`ai/evaluation/analyzer/`)
| Set | Requests | Use |
|---|---|---|
| **gate** | 100 = 30 from the seed benchmark (release `0.1.0`, `requests.jsonl`) + 70 in `requests-test.yaml` | The 90% measurement. **Never tune the prompt on it** |
| dev | 20 in `requests-dev.yaml` | Prompt tuning and few-shot examples |
| arabic | 10 in `requests-arabic.yaml` | Reported separately. Not gated |

**Coverage of the gate set:**
- all 16 domain areas, including at least 5 for each of the 8 areas the seed set did not cover
- kinds: role 37, task 46, workflow 17
- risk: low 67, medium 13, high 20
- style: clear 40, vague 27, detailed 33
- 10 requests name a platform

**Notes on the labels:**
- **Seed requests:** their `targets` are UI choices, not text, so the analyzer's targets are only scored on the 70 new requests.
- **The rules:** `LABELLING.md` has the labelling rules and boundary examples. A second person should review the labels before the first measured run, because a label mistake directly lowers the score.
- **Changes:** bump the file's `version` after any label change. Every report records each file's version and sha256, plus the seed release's `dataset_sha256`.

## Measuring accuracy

```bash
cd ai
.venv/Scripts/python -m evaluation.analyzer check-data             # validate the labels and coverage
.venv/Scripts/python -m evaluation.analyzer run --set all --live   # REAL model: about US$1.30, needs OPENROUTER_API_KEY
```

- **The `--live` guard:** without `--live` the tool refuses to call a real model. For a quick end-to-end check without a key, use `SKILLFORGE_LLM_BACKEND=fake ... run --limit 5`. Its numbers are meaningless, because the fake gives every request the same answer.
- **What a run writes:**
  - **The report**, tracked in Git: `ai/evaluation/analyzer/reports/analyzer-<set>-<date>.md` and `.json`, with accuracy per field with confusion tables, joint accuracy, clarification precision and recall, targets match, errors, tokens and cost, prompt version and data versions. A second run on the same day gets `-2`, `-3`, …, so a reviewed report is never overwritten. Only `--live` runs go here.
  - **The raw outputs**, ignored by Git: `ai/evaluation/analyzer/runs/<UTC time>/predictions.jsonl`, one line per request. The report's `run` field names this folder. A fake smoke run keeps its report here too.
- **The gate:** exactly 100 gate requests, with kind, domain area and risk each at or above 0.90. An analysis that fails with an error counts as wrong. The exit code is 0 when it passes, 1 when it fails.
- **Before the first measured run:** tune the prompt on the dev set only (`run --set dev --live`). Then run the gate once, and keep the report.

### Results: the first measured run (2026-11-02)
Prompt `analysis/request` **v1**, model `openrouter/anthropic/claude-sonnet-5.5`. The gate was run **once**. Reports are in `ai/evaluation/analyzer/reports/`.

**Gate (100 requests, `analyzer-gate-2026-11-02.md`): PASSED.** The done-when is met.

| Field | Accuracy | 95% interval (Wilson) | Target |
|---|---|---|---|
| kind | **92%** | 85.0–95.9% | ≥ 90% ✅ |
| domain area | **95%** | 88.8–97.8% | ≥ 90% ✅ |
| risk | **96%** | 90.2–98.4% | ≥ 90% ✅ |
| joint (all three right) | 84% | 75.6–89.9% | reported |

- **Also reported:**
  - needs-clarification accuracy, precision and recall: 100%;
  - named platforms: exact match on all 70 requests that have them;
  - 0 failed analyses; latency p50 2.5 s, max 8.1 s.
- **With n = 100 the intervals are wide.** Kind's lower bound is below 90%, so a re-run could land under the target by chance. Don't re-run the gate to check: that would turn it into a tuning set.

**Confusion matrices (expected → predicted):**

| kind | → role | → task | → workflow |
|---|---|---|---|
| role (37) | **35** | 1 | 1 |
| task (45) | 2 | **39** | 4 |
| workflow (18) | 0 | 0 | **18** |

| risk | → low | → medium | → high |
|---|---|---|---|
| low (66) | **62** | 3 | 1 |
| medium (14) | 0 | **14** | 0 |
| high (20) | 0 | 0 | **20** |

- **Domain area:** 95 of 100. Every high-risk area (legal, medical, finance) is 100%. The 5 misses:

  | Id | Expected | Predicted |
  |---|---|---|
  | data-analyst/req-2 | data | finance |
  | t-43 | data | technology |
  | t-02 | design | technology |
  | t-23 | operations | general |
  | t-68 | writing | general |

- **What the misses show:**
  - The main kind error is a **task read as a workflow** (4 of 45).
  - Risk errors all go **up**, never down (low → medium 3, low → high 1). That's the safer direction.
  - The one high-risk miss follows from a domain miss: data-analyst/req-2 was read as finance, and finance is always high risk.

**Tuning on dev (20 requests), before the gate:**

| Run | Prompt | kind | domain area | risk | Report |
|---|---|---|---|---|---|
| 1 | v1 | 100% | 95% | 100% | `analyzer-dev-2026-11-02.md` |
| 2 | trial v2 | 100% | 95% | 100% | `analyzer-dev-2026-11-02-2.md` |

- **Run 1's only miss:** d-04, "a senior UX researcher": labelled research, predicted design.
- **The v2 trial** added one sentence applying the "expertise, not the subject" rule to research ("a role that studies users, markets or literature is research, even when what it studies is a product's design"). It fixed d-04, but d-18 (research papers → one-page summaries) moved from research to writing. Dev stayed at 95%.
- **Why we kept v1:**
  - The trial showed no gain on dev, and with 20 requests, one request moving is within run-to-run noise.
  - Changing the prompt further would have meant fitting single dev items.
  - So the prompt and the lock stayed at v1, and the gate measured v1. The dev-2 report is the record of the trial.

**Cost** (gateway call records):
- **Gate: $0.97** for 113 calls (361,364 input / 25,076 output tokens).
- **Dev: $0.17 per run.**
- **13 of the 113 gate calls (11.5%) returned output that failed validation (`LLMOutputInvalid`)** and were retried; every request got a valid answer on retry, with no fallback. Above 10%, `AILLMErrorRateHigh` would fire in production.
  - **Follow-up, not fixed yet:** find out which validation rules fail.
  - The gateway already sends the output schema as `response_format`.
  - The call records hold no reply text, so they don't say which rule failed.

## Safety screening (AI-06)

The backend must use the **safe entry points**. They screen every request against the refusal policy (`docs/ai/refusal-policy.md`) before an analysis is released:

```python
from core.analysis import screen_and_analyze, answer_questions_safely, RequestBlocked, SafetyUnavailable

try:
    analyzed = await screen_and_analyze(text, selected_targets=["claude"])
    # ...clarify step...
    analyzed = await answer_questions_safely(analyzed, answers)   # answers are screened too
except RequestBlocked as blocked:      # BE-14: no job starts; return 422 with blocked.user_message
    ...
except SafetyUnavailable:              # the screen could not run: 503, ask the user to retry
    ...
```

- **Two calls at the same time.** The screen (`analysis/safety`, its own `safety` role) and the analysis run in parallel, so latency is about one call. The analysis is only returned if the screen allows the request.
- **The screen is a separate prompt**, so a jailbreak in the request would have to beat two prompts. It is also evaluated and versioned on its own.
- **Fail closed.** A failing screen raises `SafetyUnavailable`. A model refusal in either call counts as blocked.
- **Clearance and conditions.** An allowed request returns `analyzed.safety = {conditions, prompt_version}`. `professional_disclaimer` is always added for the legal, medical and finance areas. **The Architect must turn every condition into a `must` guardrail, and must refuse to build from an AnalyzedRequest whose `safety` is null.**
- **Measuring it.** `python -m evaluation.safety check-data | run [--live]`. The data and rules are in `ai/evaluation/safety/`. The red-team set is still **INCOMPLETE**: it must be written by a person or taken from a vetted dataset.
