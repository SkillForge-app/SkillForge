# Frontend integration contract (AI side)

For Frontend (FE-08 questions, FE-09 gap check, FE-10 progress, FE-11 spec form, FE-25/FE-26 later). This page states what the AI code returns, field by field, with the source `file:line` of each fact, and what the UI should do with it. Sections marked **Backend owns** are Backend's to confirm (Abdo). The AI-16 and AI-23 sections are Yousef's.

- **Written 26 Nov 2026** against `origin/AI` 672be98, which includes **#39** (merged 26 Nov: the pipeline input rules and the closing progress event, marked *(#39)* below), plus the still-open **#40** (2a00a70, the extraction contract). Lines marked *(#40)* exist only on #40's branch until it merges.
- **Every example is generated, never hand-written.** `python -m evaluation.contract export` (and `export --gap`, which uses the local embedding model) writes them to [frontend-contract/](frontend-contract/), and CI fails when one is out of date (`tests/evaluation/test_frontend_contract.py`).
  - **How they're made:** the pipeline examples run `RealPipeline` with a fake model gateway, whose answers are the fixture files in `ai/tests/fixtures/llm/` and the examples in `ai/examples/`. The AI-16 examples run the harness with a fake answer and judge model. The gap examples run `check_gap` with the real local model over `ai/tests/fixtures/gap/skills.yaml`.
  - **So the text inside them is fixture text** ("Fake answer with the skill."), but every field, status, code and message comes from the code.
- **Generated tables:** [frontend-contract/tables.json](frontend-contract/tables.json) lists every enum, message and error code read from the code, each with its `file:line`. If this page and `tables.json` ever disagree, `tables.json` is right.
- **Schemas:** [frontend-contract/schemas/](frontend-contract/schemas/) (from the Pydantic models). The canonical A3 and SkillSpec schemas stay where they are: `ai/core/analysis/analyzed_request.schema.json` and `ai/core/spec/schema.json`.

**Frontend never calls `ai/` directly.** The browser talks to Backend's design-run API (origin/Backend a1caf3b, **Backend owns**):

| Route | Use |
|---|---|
| `POST /design-runs` | Start a run: `{project_id, request, targets}` (`backend/app/api/routes/design_runs.py:87`) |
| `GET /design-runs/{run_id}` | The run, including progress so far (`design_runs.py:141`) |
| `GET /projects/{project_id}/design-runs` | A project's runs (`design_runs.py:155`) |
| `POST /design-runs/{run_id}/answers` | `{answers: [{question_id, text \| null}]}`; 409 unless the run is `needs_input` (`design_runs.py:179`) |

`DesignRunResponse` (`backend/app/schemas/design_runs.py`) carries the AI fields below: `status`, `step`, `questions`, `progress`, `user_message`, `error_code`, `issues`, `usage` and `spec_version_id`.

## Where each item stands

| # | Item | Built? | Owner |
|---|---|---|---|
| 1 | AI-05 clarification questions | Yes (rules tightened in #39) | AI |
| 2 | AI-08 gap checker | The function, yes. **Not a pipeline step**; Backend doesn't call it yet | AI (function), Backend (the call, the registry) |
| 3 | Job progress | Events, yes (#39). **Live push (BE-08 SSE): not built**; Backend saves events on the run, so poll `GET /design-runs/{id}` | AI (events), Backend (delivery, job state) |
| 4 | Validation states, generation errors | Yes (#39) | AI; Backend's own validator is Backend's |
| 5 | Extraction / injection (#40) | Yes; **nothing reaches the user** | AI, DE |
| 6 | AI-16 evaluation reports | Harness, yes. **No calibrated report exists** (no human labels yet) | Yousef |
| 7 | AI-23 optimizer | **No** | Yousef |
| 8 | SkillSpec v0.2 | Yes, unchanged | AI |

---

## 1. AI-05: clarification questions (A3)

**Shape** (`ai/core/analysis/types.py`):

| Field | Type | Meaning | Source |
|---|---|---|---|
| `questions[].id` | `"q1"` … `"q5"` | Stable within one request | `types.py:24`, `:59` |
| `questions[].text` | string, 1–200 chars | The question, **in the request's language** (Arabic stays Arabic) | `types.py:60` |
| `questions[].about` | `audience` \| `outputs` \| `platforms` \| `scope` \| `tone` \| `constraints` \| `domain` | Which part of the analysis the answer fills in. Not for display; useful for an icon or grouping | `types.py:17` |
| `needs_clarification` | bool | `true`: open questions, no answers yet | `types.py:103` |
| `answers[].question_id` | `"q1"` … `"q5"` | Must be one of the asked ids | `types.py:65` |
| `answers[].text` | string 1–500 chars, or `null` | `null` = the user skipped it | `types.py:66` |

**When questions are asked**
- Only by `analyze`, and only when the analyzer judges the request too vague to design from. Then `needs_clarification` is `true` and there are **3 to 5** questions. Otherwise there are none.
  - The rule is enforced in code, not left to the model: `ai/core/analysis/request.py:41-47` and `types.py:135-151`.
- **One round at most.** After `clarify`, `needs_clarification` is always `false` and the questions are kept for display (`request.py:117`). A second round never happens.
  - Backend treats a second `needs_input` as a failure (`backend/app/pipeline/runner.py:118`).

**Answer and skip rules** *(#39)*. These are checked before any model call (`ai/core/pipeline/interface.py:172` `check_text`, `:184` `prepare_answers`):
- **Request text:** 1 to 4000 characters after trimming spaces. Otherwise the result is `failed` / `invalid_request`, with the message "Please describe the skill you want in 1 to 4000 characters."
- **Answers:** only to the questions shown, and at most one per question. Otherwise `failed` / `invalid_request`, with "Please answer only the questions shown, at most once each."
- **Skipping:**
  - Each question can be skipped. Send `text: null` for it, or leave it out.
  - Skipping everything is fine: send `[]`. It is stored as one `null` answer per question.
- **Backend's API has the same limits:** 4000 characters, `q[1-5]`, answers 1–500 characters (`backend/app/schemas/design_runs.py:17-21`). It also rejects a second answer to the same question (`:44-52`).
- **Never send the analysis back.** The browser sends only the request text and the answers. Backend keeps the `AnalyzedRequest`, because its safety clearance isn't tied to the text (`types.py:161-167`).

**Examples**

| Case | File |
|---|---|
| Questions asked | [analyze-needs-input.result.json](frontend-contract/examples/analyze-needs-input.result.json) |
| No questions needed | [analyze-ok.result.json](frontend-contract/examples/analyze-ok.result.json) |
| Answered | [clarify-answered.result.json](frontend-contract/examples/clarify-answered.result.json) |
| Everything skipped (`[]`) | [clarify-all-skipped.result.json](frontend-contract/examples/clarify-all-skipped.result.json) |
| Blank request (failure) | [analyze-invalid-request.result.json](frontend-contract/examples/analyze-invalid-request.result.json) |
| Same question answered twice (failure) | [clarify-invalid-request.result.json](frontend-contract/examples/clarify-invalid-request.result.json) |
| Request refused by the safety screen | [analyze-blocked.result.json](frontend-contract/examples/analyze-blocked.result.json) (`blocked.fraud_scams`) |

**UI:**
- Show each question's `text`, with a skip option on every question and a "skip all" button.
- Show `user_message` as given on `blocked` and `failed`.
- Never show `error_code` or `about` to the user.

## 2. AI-08: gap checker

**Shape** (`ai/core/analysis/gap_checker.py`):

| Field | Type | Meaning | Source |
|---|---|---|---|
| `verdict` | `exists` \| `similar` \| `new` | The decision. `exists`: a skill already does this (FE-09 "use it"). `similar`: a related skill (FE-09 "customize it"). `new`: nothing close (FE-09 "generate new") | `gap_checker.py:39`, `:265` |
| `matches[]` | list, best first, at most `k` (default 5) | The skills found, for the UI | `:127`, `:132` |
| `matches[].score` | float, −1 to 1 | **Cosine similarity, not a percentage or a probability** | `:129` |
| `matches[].skill` | `SkillCard` | `id` (e.g. `registry:review-nda`, `corpus:draft-nda-template`), `name`, `title`, `description` (≤300), `kind`, `domain`, `use_when` (≤10), `source` (`registry` \| `corpus`), `url`, `licence` (corpus cards only) | `:46-59` |
| `exists_threshold`, `similar_threshold` | float | **0.8584** and **0.7664** (`gap_checker.yaml:11-12`, tuned on dev, `gap-dev-2026-10-28`) | `:135-136` |
| `model`, `settings_version` | string | Provenance: `local/BAAI/bge-small-en-v1.5`, `2026-10-28` | `:137-138` |

- **Only the top match decides** (`decide`, `gap_checker.py:265`). The other matches are for display.
- **What is user-facing:** the code defines the **verdict** as the decision. The thresholds are internal, and nothing in the code or docs says to show the score.
  - **AI's recommendation, not code:** show the verdict and the top card (title, description, source). Don't show the cosine score as a percentage: 0.81 doesn't mean "81% the same".
- **Precision of `exists` on the test set:** 92.3% (24/26, 95% CI 76–98%), recall 70.6% (`docs/ai/gap-checker.md`). So about 1 in 13 "already exists" answers is wrong: **always offer "generate new" as well**.

**Examples** (the real local model, fixture cards)

| Case | File |
|---|---|
| `exists` | [gap-review-nda.json](frontend-contract/examples/gap-review-nda.json) (top `registry:review-nda` 0.887). Also [gap-ai-engineer.json](frontend-contract/examples/gap-ai-engineer.json) and [gap-marketing-strategist.json](frontend-contract/examples/gap-marketing-strategist.json) |
| `similar` | [gap-review-nda-without-its-card.json](frontend-contract/examples/gap-review-nda-without-its-card.json): the same request with its own card left out, so the top match is `corpus:draft-nda-template` at 0.811 |
| `new` | [gap-empty-index.json](frontend-contract/examples/gap-empty-index.json): no skills at all, `matches: []` |
| Failure | [gap-index-mismatch.error.json](frontend-contract/examples/gap-index-mismatch.error.json): an index built with another embedding model raises `ConfigError`. It isn't a pipeline step, so there's no `StepResult`. Backend shows its generic error |

**Backend owns:**
- **Calling it.** `check_gap` is **not wired into the pipeline**: `StepName` has no `gap_check` (`interface.py:71`), and the proposed step is in `docs/ai/gap-checker.md:99` (not agreed). origin/Backend has no gap code yet.
- **The indexes:** BE-11's registry and DE-08's corpus.
- **What "use it" and "customize it" do**, and the API shape FE-09 reads.

Until Backend calls it, FE-09 has no data. **Not available yet: owner Backend (BE-11, with AI-08). The plan puts BE-11 in P2 (7 Dec 2026 – 1 Jan 2027).**

## 3. Job progress

**Event shape** (`ai/core/pipeline/interface.py`):

| Field | Type | Meaning | Source |
|---|---|---|---|
| `step` | `analyze` \| `clarify` \| `design` | Events are sent only during `design` today | `:71` |
| `stage` | `started` \| `attempt` \| `repairing` \| `done` \| `failed` | See the stage list below | `:73` |
| `attempt` | int or `null` | 1–3. `null` on `started`, and on a closing event sent before any attempt | `:104` |
| `message` | string | **Safe to show**, in English | `:105` |

**The stages, in order:**
- `started`: the design began.
- `attempt` (1): the first draft is being written.
- `repairing` (2, 3): fixing validation problems in the draft. There are at most 3 attempts in all.
- Then **exactly one closing event** *(#39, `interface.py:306`)*: `done` on success, `failed` otherwise.

**The closing messages** (`closing_event`, `interface.py:157`; the strings are at `:149-154`):

| Result `status` / `error_code` | Closing `stage` | `message` |
|---|---|---|
| `ok` | `done` | Design ready |
| `retry_later` (`provider_unavailable` or `deadline_exceeded`) | `failed` | Paused: we'll try again shortly |
| `blocked` | `failed` | Stopped: this request can't be built |
| `failed` / `budget_exceeded` | `failed` | Stopped: too much work for one request |
| `needs_input` / `open_questions`, or `failed` / `not_screened` | `failed` | Stopped: the request isn't ready |
| `failed` / `invalid_spec` | `failed` | Could not produce a valid design |

**Final source of truth: the job status, confirmed.**
- A `failed` *event* can mean "paused, will retry" (the first `retry_later` row). The last event never decides the outcome. That is AI's rule: the `interface.py:147-148` comment, and `docs/ai/backend-integration.md:147`.
- The outcome is the run's `status` from Backend: `queued` \| `running` \| `needs_input` \| `completed` \| `blocked` \| `retry_later` \| `failed` (`backend/app/db/models.py:255`, `backend/app/pipeline/runner.py:7-15`). **Backend owns it.**

**Delivery (Backend owns)**
- Backend appends each event to the run's `progress` list (at most 200) and saves it as it comes (`runner.py:168-171`). `GET /design-runs/{run_id}` therefore shows progress while design runs.
- **Live push to the browser (BE-08, Server-Sent Events) is not built:** origin/Backend has no event stream. **Owner Backend; the plan put BE-08 in P1 (by 4 Dec 2026).** Until then, poll the run.

**Which source data may be shown**
- **During progress: none.** The design step (Skill Architect v0) uses no web knowledge (`ai/core/agents/architect.py:1`; its prompt keeps `sources` empty, `ai/prompts/architect/generate.md:31-32`). No event carries a source.
- **"Sources being read" (FE-10): not available yet.** Owner AI (AI-12, Skill Architect v1, which uses retrieved knowledge); the plan puts it in P2 (7 Dec 2026 – 1 Jan 2027). It needs a new event field, which means a contract change (AI + BE). BE-08 must carry it.
- **After `ok`:** the `SkillSpec.sources[]` may be shown: `id`, `url`, `retrieved` (date), `title?`, `licence?` (`ai/core/spec/models.py:213`). Link to `url`.
  - Today's v0 specs have `sources: []`. [design-ok.result.json](frontend-contract/examples/design-ok.result.json) shows three, because its model answer is the hand-made `review-nda` example spec (fixture), not v0 output.

**Failure reasons:** the `design` part of the table in section 4.

**Retry and resume**
- **AI side:**
  - Only `retry_later` is worth retrying, by running the **same step again later**. Don't retry `failed`, `blocked` or `invalid_request` with the same input.
  - A re-run `design` starts again at attempt 1. **There is no mid-design resume.**
  - `analyze` and `clarify` are separate steps, so a run waiting for answers loses nothing.
- **Backend side (Backend owns, open point 1):** AI's worker guide re-enqueues `retry_later` itself, 3 times (`docs/ai/backend-integration.md:94`, `:129-131`). But origin/Backend's runner **ends the run** at `retry_later` ("start the run again later", `runner.py:13`, `:24`, `:183-184`).
  - Until Backend decides, treat `retry_later` as final for that run. Show `user_message` and a "try again" action that starts a new run.

**Examples**

| Case | Result | Events |
|---|---|---|
| ok | [design-ok.result.json](frontend-contract/examples/design-ok.result.json) | [design-ok.events.json](frontend-contract/examples/design-ok.events.json) |
| `retry_later` / `deadline_exceeded` | [design-retry-later.result.json](frontend-contract/examples/design-retry-later.result.json) | [design-retry-later.events.json](frontend-contract/examples/design-retry-later.events.json) (closes with "Paused") |
| `blocked.other` | [design-blocked.result.json](frontend-contract/examples/design-blocked.result.json) | [design-blocked.events.json](frontend-contract/examples/design-blocked.events.json) |

## 4. Validation states and generation errors (#39)

**`StepResult`** (`interface.py:108`), stored by Backend per step:

| Field | Meaning |
|---|---|
| `step` | `analyze`, `clarify` or `design` |
| `status` | `ok` \| `needs_input` \| `blocked` \| `retry_later` \| `failed` (`:72`) |
| `value` | An `AnalyzedRequest` (analyze, clarify) or a `SkillSpec` (design). `null` except on `ok` and on analyze's `needs_input` |
| `user_message` | **Safe to show.** Set on `blocked`, `retry_later` and `failed` |
| `error_code` | For logic and logs; **never show it** |
| `issues[]` | Validation problems (below) |
| `usage` | `calls`, tokens, `cost_usd`. Not for users |
| `pipeline_version` | `"0.1"` |

**Generation errors**: every `error_code` the pipeline returns. Read from the code, with lines, in `tables.json` → `pipeline.error_codes`.

| `status` | `error_code` | Step | Meaning | UI |
|---|---|---|---|---|
| `needs_input` | none | analyze | Questions to answer | Question form (section 1) |
| `needs_input` | `open_questions` | design | See below | See below |
| `blocked` | `blocked.<category>` | analyze, clarify | The safety screen refused it. Categories: `cyber_attack`, `fraud_scams`, `weapons`, `violence_harassment`, `self_harm`, `child_safety`, `hate_extremism`, `privacy_surveillance`, `illegal_drugs`, `disinformation`, `other` (`ai/core/analysis/types.py:30`) | Show `user_message` (it is category-specific, and `self_harm` includes help resources). No retry |
| `blocked` | `blocked.other` | design | The design model refused | Show `user_message`. No retry |
| `retry_later` | `provider_unavailable` | any | A model provider or the safety screen was down | Show `user_message` (section 3, retry) |
| `retry_later` | `deadline_exceeded` | any | The step passed its time limit (analyze/clarify 120 s, design 600 s) *(#39)* | Same as `provider_unavailable` |
| `failed` | `invalid_request` | analyze, clarify | The input broke a rule in section 1. No model was called *(#39)* | Show `user_message`, and let the user edit |
| `failed` | `analysis_failed.<ErrorType>` | analyze, clarify | The analysis could not be used | Show `user_message` |
| `failed` | `invalid_spec` | design | No valid spec after 3 attempts; `issues` say why | Show `user_message`. Don't show the issues (the user didn't write the spec) |
| `failed` | `budget_exceeded` | any | The skill used up its model budget | Show `user_message` ("narrow it down") |
| `failed` | `not_screened` | design | Backend passed an analysis with no safety clearance: a Backend bug | Generic error |

Backend adds its own codes on top (for example `empty_result`, `runner.py:154`, `:188`). **Backend owns those.**

**Validation issues** (`IssueRecord`, `interface.py:81`):

| Field | Type | Meaning |
|---|---|---|
| `path` | JSON Pointer, e.g. `/skill/name`, `/procedures/0/produces/1` | Where. FE-11 puts the message next to that field |
| `code` | stable string | What (list below) |
| `message` | string | Short and in English. **Never quotes free text**; some quote an id or field name, e.g. `source "src-1" is not defined in /sources` (`ai/core/spec/validator.py:10-11`) |
| `severity` | `error` \| `warning` | `error` makes the spec invalid. `warning` doesn't (for example `target_not_available_in_v1`) |

- **The codes:** read from `validator.py`; the full list, with lines, is in `tables.json` → `spec_validator.issue_codes`. They are:
  - `description_too_long`, `duplicate_file`, `duplicate_id`, `high_risk_needs_disclaimer`, `high_risk_needs_human_review`, `name_taken`, `reserved_name`, `role_needs_guardrail`;
  - `schema.missing`, `schema.unknown_field`, `schema.<pydantic error type>` (e.g. `schema.string_too_long`);
  - `target_not_available_in_v1`, `tool_listed_twice`, `unknown_output`, `unknown_reference`, `unknown_source`, `unused_output`, `unused_source`, `xml_in_text`;
  - `not_a_mapping` and `yaml_syntax`, which come only from loading a YAML file, never from the pipeline.
- **When FE-11 sees them:**
  - On a design `failed` / `invalid_spec`: internal only, see the table above.
  - When the user edits a spec: Backend validates the edit with its own validator (`backend/app/spec/validator.py`). That validator and its API response are **Backend's**.
- **Example:** [design-invalid-spec.result.json](frontend-contract/examples/design-invalid-spec.result.json) (`name_taken` at `/skill/name`, after 3 attempts) and [design-invalid-spec.events.json](frontend-contract/examples/design-invalid-spec.events.json) (`attempt` 1, `repairing` 2 and 3, then `failed`).

### `needs_input`: with questions and without

`needs_input` does **not** always come with questions. The module docstring (`interface.py:5`, `:11`: "show the clarifying questions in `value.questions`") describes only the first case below. `backend-integration.md:57-58` has both.

| Returned by | `error_code` | `value` | Questions? | When |
|---|---|---|---|---|
| `analyze` | `null` | The `AnalyzedRequest`, `needs_clarification: true`, 3–5 `questions`, `answers: []` | **Yes**, in `value.questions` | The request is too vague (`interface.py:341`: `needs_input` exactly when `needs_clarification`) |
| `clarify` | | | **Never returned** by the real pipeline | `clarify` always ends the questions (`request.py:117`). Only a test fake can script it; Backend fails the run if it happens (`runner.py:118`) |
| `design` | `"open_questions"` | **`null`** | **No**, not in this result | `design` was given an analysis whose questions are still open. It stops before any model call (`interface.py:272`; 0 calls in the example) |

**UI**
- **From `analyze`:** show `value.questions`. In Backend's API they are `questions` on the run, while `status` is `needs_input` (`runner.py:46-49`).
- **From `design`:** this result has no questions, and the closing event says "Stopped: the request isn't ready".
  - Show the questions from the **stored analysis**. Backend's `questions` field already does this: it reads them from the run's saved analysis, not from the design result (`runner.py:46-49`, `:178-179`).
  - **If that list is empty**, it's a Backend bug: show the generic error and **never an empty question form**.
- **In both cases,** answers go to `POST /design-runs/{run_id}/answers` as in section 1.

**Examples**
- With questions: [analyze-needs-input.result.json](frontend-contract/examples/analyze-needs-input.result.json).
- Without: [design-needs-input-no-value.result.json](frontend-contract/examples/design-needs-input-no-value.result.json) and its events [design-needs-input-no-value.events.json](frontend-contract/examples/design-needs-input-no-value.events.json) (`started`, then `failed` "Stopped: the request isn't ready", `attempt: null`).
- A test pins this rule: `test_needs_input_has_questions_only_from_analyze`.

## 5. Extraction and injection rules (#40)

**`extraction_error` never reaches the user**
- It is one of 7 reasons a scraped page is rejected: `empty`, `paywall_or_login`, `boilerplate`, `wrong_language`, `too_short`, `injection`, `extraction_error` (`ai/core/knowledge/extract.py:50`). `extraction_error` means the page passed every check but its chunks could not be built (`extract.py:325`).
- `extract_page` runs only in Data Engineering's offline ingest, which records rejections in its ingest report and logs (`ai/core/knowledge/ingest.py:98`, `:118`). No pipeline step extracts pages. Design v0 uses no web knowledge.

**The injection rules don't show either**
- A flagged sentence is removed, and a page with too many findings is rejected, before anything becomes a chunk (`docs/ai/injection-defence.md`). The user sees neither.
- The spec-level check (`check_spec`, layer 4) is exported, but **no pipeline step calls it** yet.
- **When AI-12 adds web knowledge,** a rejected page is simply not among the sources. **Per-page rejection reasons in the UI are not planned.**

**Pinned extraction version for Data's re-chunk:**
- `EXTRACTION_VERSION = 2` (`extract.py:108`);
- default config fingerprint `474bd237fac3dc9db4018f1f0ad2b337cd4d99c4ec33b2b61feaad59c79d79c5` (`ai/tests/knowledge/test_fingerprint.py:14`; `tables.json` → `extraction`).
- Re-chunk from `AI` after #40 merges, not from an earlier checkout of #40's branch.

## 6. AI-16 / FE-25: evaluation reports (Yousef)

**Schema:** `ai/evaluation/harness/report.schema.json` (JSON Schema 2020-12; validate each JSONL line on its own). Contract notes: `docs/ai/ai-16-report-contract.md`.

| Object | `report_type` / `record_type` | `status` | Meaning |
|---|---|---|---|
| Benchmark report (`report.json`) | `benchmark` | `completed` \| `completed_with_errors` \| `failed` | **Whether the run executed**, not whether the skill is good. `completed_with_errors`: some prompts failed. `failed`: none completed (`ai/evaluation/harness/evaluate.py:428-431`) |
| Its `calibration` block | | `not_calibrated` on every benchmark report | Calibration is a separate run against human labels |
| Calibration report (`calibration.json`) | `calibration` | `passed` \| `failed` | Judge–human agreement ≥ 80% (`passed`), or below it / judge errors (`failed`) |
| Prediction line (`predictions.jsonl`) | `prediction` | `completed` \| `failed` | One prompt. `arms.with_skill` / `arms.without_skill`: the answer and one score per rubric item |
| Calibration decision line (`comparisons.jsonl`) | `calibration_decision` | `completed` \| `failed` | One judge-vs-human decision |

- **Benchmark report fields:**
  - `report_type`, `status`, `created`, `live`;
  - `dataset`, `dataset_version`, `dataset_sha256`, `skill`, `skill_instructions_sha256`, `review_status`;
  - `prompts` (prompt id → version), `models`;
  - `metrics` (`n`, `completed`, `errors` {code: count}, `with_skill` / `without_skill` {`rubric_items`, `passed`, `pass_rate`, `critical_items`, `critical_passed`, `critical_pass_rate`}, `uplift`);
  - `calibration`, `usage`.
- **Error codes:** `budget_exceeded`, `configuration_error`, `invalid_input`, `invalid_model_output`, `model_refused`, `prompt_format_error`, `prompt_not_found`, `provider_unavailable` and `unexpected_error` (`evaluate.py:107`).

**For FE-25**
- **Headline:** `metrics.with_skill.pass_rate` against `metrics.without_skill.pass_rate`, and `uplift` (the difference).
- **While `calibration.status` is `not_calibrated`, label the scores "not yet checked against human reviewers".** Today every report is uncalibrated: no human labels exist yet (`docs/ai/ai-16-human-labeling.md`, "Status and prerequisite"). Calibrated reports are **not available yet; owner Yousef. The repo states no date**; Yousef to confirm.
- **On `completed_with_errors`,** show the scores as partial (`metrics.completed` of `metrics.n`).

**Examples** (fake answer and judge models over 2 prompts of the seed release `1.0.0`, skill `ai-engineer`; validated against the schema)

| Case | Report | Prediction lines |
|---|---|---|
| Success, uncalibrated | [ai16-benchmark-completed.report.json](frontend-contract/examples/ai16-benchmark-completed.report.json) | [ai16-benchmark-completed.predictions.jsonl](frontend-contract/examples/ai16-benchmark-completed.predictions.jsonl) |
| Failure: one prompt hit a provider outage | [ai16-benchmark-completed-with-errors.report.json](frontend-contract/examples/ai16-benchmark-completed-with-errors.report.json) | [ai16-benchmark-completed-with-errors.predictions.jsonl](frontend-contract/examples/ai16-benchmark-completed-with-errors.predictions.jsonl) (line 1: `failed` / `provider_unavailable`) |

- **No calibration example is generated.** A calibration report needs a human-labels file, and none exists. The hand-written one in `ai-16-report-contract.md` shows the shape.

**Mapping to the evaluation tables of PR #33** (Backend's PR, by Abdo, merged into `Backend` on 22 Nov; `backend/app/db/models.py:268-461`). **A proposal; Backend owns it:**

| Report | Table / column |
|---|---|
| The run | one `evaluation_runs` row: `status` (see below), `live`, `model` = `models.answer`, `prompt_id` / `prompt_version` = `evaluation/answer` and its version, `data_sources` = `[{dataset, dataset_version, dataset_sha256}]`, `report_data` = the whole `report.json`, `summary` = `metrics`, `usage` = `usage`, `gates` = `calibration` |
| Which skill and benchmark | `evaluation_tasks` (`name` = skill, `dataset_version`) |
| Each number | one `evaluation_scores` row per metric: `with_skill.pass_rate`, `without_skill.pass_rate`, `with_skill.critical_pass_rate`, `without_skill.critical_pass_rate`, `uplift` |
| The files | `evaluation_artifacts`: `report.json`, `report.md`, `predictions.jsonl` (and `calibration.json`, `comparisons.jsonl` for a calibration run) |

- **Gap:** `evaluation_runs.status` allows `queued|running|completed|failed|cancelled` (`models.py:383`). There is **no `completed_with_errors`** (open point 2).

## 7. AI-23 / FE-26: optimizer history (Yousef)

- **Exists now:** no optimizer code on any AI branch. Only AI-04's rule exists: "a new version of a skill must beat the old one on the same benchmark version" (`docs/ai/seed-benchmark.md:8`).
- **Not available yet; owner Yousef.** Yousef's estimate (26 Nov):
  - **7 Dec 2026**, if the AI-16 outputs, the B4 agreement and AI credits are in place by 1 Dec;
  - otherwise about **10 Dec**.
- **FE-26** treats the optimization history as not available until then. Its fields are to be confirmed by Yousef, and are not defined here.

## 8. SkillSpec v0.2: unchanged

- **The schema file:** `ai/core/spec/schema.json`, `$id` `urn:skillforge:skillspec:0.2`, sha256 `13e7120c68db54c7069963d9200a16b3bec363562ec2bd18e706bba991b40e36` (as Git stores it; `tables.json` → `skillspec`).
  - It's the same on `AI`, #39, #40, #44 and `main`. The last change was e56f9ed (2 Nov). **No new copy is needed.**
- **Backend's copy** (`backend/app/spec/schema.json`, origin/Backend): the same JSON, with a UTF-8 BOM added.
- **Frontend's copy** (`frontend/apps/web/lib/skillspec/schema.json`, origin/Frontend e237e04):
  - the same structure, reformatted;
  - one description string predates e56f9ed (`Source.licence`'s description: AI's says "an SPDX id preferred, e.g. CC-BY-4.0").
  - Validation is identical. A refresh is optional.
- **#44 (open)** doesn't touch the schema or `interface.py`.

## Open points for Backend (Abdo)

Listed, not decided here. All lines are origin/Backend a1caf3b unless they start with `ai/`.

1. **`retry_later` ends the run.** Backend's runner treats it as terminal (`backend/app/pipeline/runner.py:13`, `:24`, `:149-150`, `:183-184`). AI's worker guide re-enqueues the same step with delays (`ai/docs/ai/backend-integration.md:94`, `:129-131`). Decide which one FE should expect.
2. **`completed_with_errors` is missing from the DB status check:** `chk_evaluation_run_status` (`backend/app/db/models.py:383`) against AI-16's benchmark status (`ai/evaluation/harness/evaluate.py:428-431`).
3. **`targets`:** Backend defaults to `["claude"]` with at least one (`backend/app/schemas/design_runs.py:31-33`). A3 allows `[]`, meaning "not chosen yet" (`ai/core/analysis/types.py:122-126`). Both work today, but FE needs one rule for the platform picker.
4. **The gap step isn't wired:** there's no `gap_check` step (`ai/core/pipeline/interface.py:71`), the proposal is open (`ai/docs/ai/gap-checker.md:99`), and there's no gap code in `backend/app`.
5. **BE-08 Server-Sent Events aren't built:** there's no event stream in `backend/app`. Progress is only visible by polling `GET /design-runs/{run_id}` (`backend/app/api/routes/design_runs.py:141`, events saved at `backend/app/pipeline/runner.py:168-171`). FE-10's doc is still waiting on it (`frontend/docs/frontend/FE-10-job-progress.md`, origin/Frontend).

## Not available yet

| What | Owner | When |
|---|---|---|
| Gap check in the pipeline / FE-09 data | Backend (BE-11) with AI (AI-08) | Plan: P2 (7 Dec 2026 – 1 Jan 2027) |
| Live progress push (SSE) | Backend (BE-08) | Plan: P1 (by 4 Dec 2026) |
| Sources during progress, sources in generated specs | AI (AI-12) | Plan: P2 (7 Dec 2026 – 1 Jan 2027) |
| Calibrated AI-16 reports | Yousef (AI-16) | Not stated; Yousef to confirm |
| Optimizer history (FE-26) | Yousef (AI-23) | 7 Dec 2026, or about 10 Dec (see section 7) |
