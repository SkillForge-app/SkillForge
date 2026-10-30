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
.venv/Scripts/python -m evaluation.analyzer run --set all --live   # REAL model: about US$1, needs ANTHROPIC_API_KEY
```

- **The `--live` guard:** without `--live` the tool refuses to call a real model. For a quick end-to-end check without a key, use `SKILLFORGE_LLM_BACKEND=fake ... run --limit 5`. Its numbers are meaningless, because the fake gives every request the same answer.
- **What a run writes:** `ai/evaluation/analyzer/runs/<UTC time>/` (ignored by Git), containing `report.md`, `report.json` (accuracy per field with confusion tables, joint accuracy, clarification precision and recall, targets match, errors, tokens and cost, prompt version, data versions) and `predictions.jsonl`.
- **The gate:** exactly 100 gate requests, with kind, domain area and risk each at or above 0.90. An analysis that fails with an error counts as wrong. The exit code is 0 when it passes, 1 when it fails.
- **Before the first measured run:** tune the prompt on the dev set only (`run --set dev --live`). Then run the gate once, and keep the report.

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
