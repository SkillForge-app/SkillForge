# Skill Architect v1 (AI-07, AI-12)

Owner: the AI Lead (AI-07 to AI-14).

## Done-when, and where each stands

| Task | Done-when (plan) | Status |
|---|---|---|
| AI-07 | At least 90% of the 103 test requests produce a valid SkillSpec | **Not measured yet.** It needs one live run (`--set all --live`, about $10–20) |
| AI-12 | "Seed skills generated with sources" | **Not met yet.** For 15 Dec it is met **on fixture passages with a live model**: the 10 seed requests (`--set seed --live`, with `SKILLFORGE_RETRIEVER=fake`) all get a valid spec that cites retrieved pages. DE's knowledge store does not hold the seed domains yet, so the real-retriever run comes later |

Offline everything already runs: a fake run of the seed set gives 10 of 10 specs with sources. A fake run never counts: the fake model gives every request the same canned spec.

## What it does
The Skill Architect turns a **screened** `AnalyzedRequest` (contract A3) into a valid `SkillSpec` (contract B1). It retrieves web knowledge first (contract A4) and cites it.

```python
from core.agents import build_spec

result = await build_spec(analyzed, existing_names=registry_names, on_progress=callback)
if result.ok:
    spec = result.spec            # passed validate_spec, check_spec and copied_text
    result.passages               # what the Architect was given
    result.evidence               # {reference id: [chunk ids]}: for AI-13
else:
    result.issues                 # the last attempt's errors
```

- **`build_spec(..., knowledge=False)`** skips retrieval. The spec then has no references and no sources.
- **The pipeline interface is unchanged:** the design step still returns `StepResult[SkillSpec]`.

## It refuses before any model call
| Situation | Error |
|---|---|
| `analyzed.safety is None` (not safety-screened) | `NotScreened`. Use `core.analysis.screen_and_analyze` first |
| `analyzed.needs_clarification` (open questions) | `NotReady`. Call `answer_questions_safely` first |
| The knowledge store fails (not an empty index) | `ArchitectUnavailable`, before any model call: retry the job later |

## The flow (LangGraph)
```
START → research → write → enforce → check ─(valid)─────────────────→ END  ok
                     ↑                       ├(errors, attempt < 3)──→ write  (repair)
                     └───────────────────────┘(errors, attempt = 3)──→ END  failed
```

### `research`: no model call
- **Queries:** up to 3, from the request alone. They are its summary, its domain as words, and its expected outputs.
- **Retrieval:** each query is `retrieve(query, domain, k=5)`. The first 8 distinct chunks are kept, in order.
- **Numbering:** each page the chunks come from becomes one source, numbered `src-1`, `src-2`, and so on.
- **Licence (interim):** each source's `licence` comes from the AI-09 registry's host rule (`core.knowledge.licence_for_url`), as the SPDX id DE stores. A licence the page declares itself should win, but it can't reach a passage yet: review finding **F14**, an A4 change to agree with DE.
- **No passages** (a domain with nothing in the store), or an **empty index** (`EmptyIndexError`): the Architect designs without web knowledge. An empty index adds a `knowledge_unavailable` warning.

### `write`
- **Prompts:** attempt 1 uses `architect/generate`. Attempts 2 and 3 use `architect/repair`, with the previous draft and the issues as `path  code  message`.
- **How the model gets the passages:** through `wrap_passages` and `UNTRUSTED_DATA_RULE` (AI-19 layer 3), plus a list of source ids with their chunk ids.
  - The model may **cite source ids only**. It never writes a URL or a `sources[]` entry.
  - Page titles stay inside the wrapped block.
- **What the prompts ask for:**
  - 1–4 `knowledge.references` (`references/<id>.md`, a title, and the source ids they draw on);
  - procedures list in `uses` the references their steps rely on;
  - facts must agree with the passages, written in the model's own words.
- **Without passages,** both prompts render exactly as v1 did.
- **Two levels of repair.** The gateway already makes one repair attempt itself for replies that don't fit the SkillSpec field rules. If that fails, the attempt counts as failed, and the loop goes on.

### `enforce`
These rules never depend on the model. They are deterministic and idempotent.
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
- **Sources:**
  - **With passages:** `sources[]` becomes the numbered sources the references cite, and the others are dropped. An id the model makes up stays, so validation reports `unknown_source` and the spec is repaired.
  - **Without passages:** references, sources and `uses` are emptied, so no invented source can survive.

### `check`
1. **`validate_spec`.** Its errors fail the attempt.
2. **On a valid spec:**
   - **`check_spec`** (AI-19 layer 4) catches `injection-url`, `injection-secret` and `injection-override` errors, for example a URL that isn't one of the passages' pages.
   - **`copied_text` ("summarise, never paste", review F15)** is an error when a free-text field shares 12 or more consecutive words with a passage (case and punctuation ignored).
   - Both send the spec to repair.
3. **Warnings are allowed:**
   - `knowledge_unused` (passages found, none cited);
   - `knowledge_unavailable` (an empty index);
   - `check_spec`'s `injection-instruction`.

**When it stops:**
- **Provider or store errors** raise `ArchitectUnavailable` (retry the job later).
- **A model refusal** raises `ArchitectRefused`.
- **Progress events** (`attempt`, `repairing`, `done` or `failed`, plus the attempt number) go to `on_progress`.

### Where the citations end up
- **The chain in the spec:** a procedure's `uses` points to `knowledge.references[]`, whose `sources` point to `sources[]` (URL, retrieval date, title, licence). Backend's compiler lists the references and sources in SKILL.md.
- **The reference files** (`references/*.md`, with claim-by-claim citations) are **AI-13's** job.

## AI-13 and AI-14: how they plug in
- **AI-13, reference writer:** `write_references(spec, passages, evidence)`.
  - **Its inputs:** the passages and `evidence` from `ArchitectResult`, so no second retrieval is needed. Each reference's chunks are those of the pages it cites.
  - **Its output:** one file per reference, with every claim citing a `chunk_id` from that reference's evidence.
  - **Its checks:** the same wrapping, `copied_text` and `check_spec` on the markdown.
- **AI-14, trigger writer:** `write_descriptions(spec) -> {target: description}`, each within `PLATFORM_LIMITS`. `draft_description` (the validator) stays the fallback.
- **One change to the pipeline interface (Backend's contract) for both:** the design step returns a `SkillDraft(spec, reference_files, descriptions)`. It is proposed after AI-12 merges, and needs Backend's approval.

**Prompts and model.** The prompts are in `ai/prompts/architect/` (version 2). Their example spec is a synthetic `meeting-minutes` skill, not one of the test requests, and a test checks that it is valid. The model role is `architect`: Claude Sonnet 5.5, `max_tokens` 24000, timeout 300 s.

**Tracing is off.** LangGraph comes with LangSmith tracing, which the Architect switches off by default (`LANGSMITH_TRACING=false`), because traces would contain users' requests.

## Measuring it
```bash
cd ai
.venv/Scripts/python -m evaluation.architect check-data              # the 103 + 10 test requests
.venv/Scripts/python -m evaluation.architect run --set all --live    # AI-07, REAL calls: about $10–20
SKILLFORGE_RETRIEVER=fake .venv/Scripts/python -m evaluation.architect run --set seed --live
                                                                     # AI-12 on fixture passages: about $1–3
```

**The sets:**
- **`all` (AI-07):** the 3 example AnalyzedRequests, plus the 100 analyzer gate requests built **from their labels**. So the score measures the Architect alone. Vague requests count as "questions skipped".
- **`seed` (AI-12):** the clear request (`req-1`) of each of the 10 seed-benchmark skills, built from labels the same way. They come from seed release 0.1.0, the one the analyzer gate uses on this branch.
- **Knowledge:** with `SKILLFORGE_RETRIEVER=fake`, passages come from `tests/fixtures/knowledge/passages.yaml`. Version 1.1.0 covers all 10 seed domains; its header records where each passage came from. The report names the retriever it used (and, for the fake, the fixture version and sha256).

**End to end:** `--end-to-end` runs the real safety screen and analyzer first.

**What a run writes:**
- **The report**, tracked in Git: `ai/evaluation/architect/reports/architect-<set>[-e2e]-<date>.md` and `.json`. A second run on the same day gets `-2`, `-3`, …, so a reviewed report is never overwritten. Only `--live` runs go here.
- **The raw outputs**, ignored by Git: `ai/evaluation/architect/runs/<UTC>/` holds `predictions.jsonl` and **every generated spec** in `specs/`, for review by hand. The report's `run` field names this folder. A fake smoke run keeps its report here too.

**What the report shows:**
- valid rate, first-try rate, the attempts histogram, the most common failure codes, safety-guardrail compliance and identity fidelity;
- **knowledge metrics:** requests with passages, valid specs with references and sources, and sources traced to a retrieved page.

**The verdicts:**
- **AI-07:** exactly 103 requests, at least 90% valid.
- **AI-12:** all 10 seed requests valid, all with cited sources, and every source a retrieved page.
- A fake run prints "does NOT count" for both.

## Dependency note
LangGraph is pinned at `1.2.14`, published on 6 Oct 2026. `pyproject.toml` sets `[tool.uv] exclude-newer = "2026-10-10T00:00:00Z"`, so `uv lock` only picks releases at least two weeks old, for every package, including LangGraph's own dependencies. When you upgrade:
1. Move the date forward, keeping it at least two weeks behind today.
2. Run `uv lock`.
3. Run the full test suite, then the live tests.
