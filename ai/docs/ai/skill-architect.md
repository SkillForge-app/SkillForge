# Skill Architect v1 and the writers (AI-07, AI-12, AI-13, AI-14)

Owner: the AI Lead (AI-07 to AI-14). The writers are in [Writers (AI-13, AI-14)](#writers-ai-13-ai-14).

## Done-when, and where each stands

| Task | Done-when (plan) | Status |
|---|---|---|
| AI-07 | At least 90% of the 103 test requests produce a valid SkillSpec | **Not measured yet.** It needs one live run (`--set all --live`, about $10–20) |
| AI-12 | "Seed skills generated with sources" | **Not met yet.** For 15 Dec it is met **on fixture passages with a live model**: the 10 seed requests (`--set seed --live`, with `SKILLFORGE_RETRIEVER=fake`) all get a valid spec that cites retrieved pages. DE's knowledge store does not hold the seed domains yet, so the real-retriever run comes later |
| AI-13 | "No uncited claims in reference files" | **Not met yet.** Built and tested offline. It needs the live seed run with `--writers`: all 10 specs valid, a file for every reference, 0 uncited claims. The weakly-supported rate is reported, with no gate yet |
| AI-14 | "Trigger accuracy measured in AI-17" | **Built and tested offline.** Done when AI-17 (Yousef) measures the descriptions against the seed benchmark's trigger prompts |

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

## Writers (AI-13, AI-14)
```python
from core.agents.writers import write_references, describe

files = await write_references(result.spec, result.passages, result.evidence)
for f in files:
    f.path, f.markdown, f.claims, f.dropped     # references/<id>.md; claims with support scores
descriptions = (await describe(result.spec)).by_target   # {target: description}
```

### AI-13: the reference writer (`core/agents/writers/references.py`)
- **One model call per reference** (prompt `writers/references` v1, role `architect`).
  - **Its input:** only the passages behind that reference (the Architect's `evidence`), wrapped as untrusted data.
  - **Its output:** sections of claims, each citing chunk ids. The model never writes Markdown, URLs or citation markers.
- **Every claim is checked:**
  - it cites at least one chunk, and only chunks of its reference's evidence;
  - it doesn't copy 12+ words of a passage (`copied_fields`);
  - it contains no URL or domain;
  - AI-19's `screen_text` finds no override, role-marker, secret or exfiltration text.
  - A failing claim gets **one repair call**. If it still fails, it is **dropped** and counted by reason.
- **The code renders the file:** each claim gets `[n]` markers, and a numbered Sources list (title, URL, retrieval date) comes from `spec.sources`. So **a file can't contain an uncited claim**.
- **No evidence:** no call and no file. **Two invalid replies:** no file. **Provider down:** `WriterUnavailable` (retry later).

### The support check: "cited" isn't "supported"
- **How it scores:** each kept claim and the chunks it cites are embedded with the local model (bge-small, no API cost). The claim's `support` is its best cosine similarity to those chunks.
- **What it flags:** below `SUPPORT_THRESHOLD` (**0.67**) the claim is `weak`. It is kept and counted, never dropped, and nothing gates on it yet.
- **How the threshold was chosen:** `python -m evaluation.architect calibrate-support`, once, on the **fixture passages only**, never on seed results ([report](../../evaluation/architect/reports/support-calibration-2026-11-21.md)).
  - **Positive pairs:** each passage sentence (6+ words) against its own passage.
  - **Negative pairs:** the same sentence against the most similar passage of **another page in the same domain**, the near miss.
  - **The pick:** best F1, ties going to the lower threshold.
  - **The result:** passages.yaml 1.1.0, 141 + 141 pairs: **0.67**, precision 85.8%, recall 94.3%, F1 0.899.
  - **The known limit:** a sentence taken from the passage scores higher than a fair paraphrase, so some paraphrased claims may be flagged. The 10-claim human spot-check in each seed report covers that.
  - **To recalibrate:** run the command again (it needs the local model files: `SKILLFORGE_MODEL_CACHE`, offline), then update the constant. A test checks that it matches the latest committed report.

### AI-14: the trigger writer (`core/agents/writers/triggers.py`)
- **One call** (prompt `writers/triggers` v1) writes the description from the spec's summary, `use_when` and `avoid_when`.
- **Checks, per target:** not empty, no XML-like tag, at most `PLATFORM_LIMITS[target].description` characters (1024 today; only Claude's limit is verified).
- **On failure:** one repair call. If it still fails, that target falls back to `draft_description` (which a valid spec always fits), and `Descriptions.fallback` lists it.
- **The hand-off to AI-17 (Yousef):** these descriptions, plus the seed benchmark 1.0.0's 80 test prompts and 60 should-not-trigger prompts.

### For Backend: the `SkillDraft` proposal
**Not implemented. To be proposed after this work merges.**
- **What changes:** the design step's `StepResult` gains an optional `draft: SkillDraft(spec, reference_files[{path, markdown}], descriptions{target: str})`. `value` stays the SkillSpec, so the change is additive.
- **What the compiler (BE-09) does with it:** writes the `references/*.md` files, and uses the description. With no draft it uses `draft_description`, as today.
- **When:** it touches `core/pipeline/interface.py`, so it comes after review batch `-c1` is merged, and needs Backend's approval. Neither done-when depends on it.

**Prompts and model.** The Architect's prompts are in `ai/prompts/architect/` (version 2); the writers' are in `ai/prompts/writers/` (version 1). Their example spec is a synthetic `meeting-minutes` skill, not one of the test requests, and a test checks that it is valid. The model role is `architect`: Claude Sonnet 5.5, `max_tokens` 24000, timeout 300 s.

**Tracing is off.** LangGraph comes with LangSmith tracing, which the Architect switches off by default (`LANGSMITH_TRACING=false`), because traces would contain users' requests.

## Measuring it
```bash
cd ai
.venv/Scripts/python -m evaluation.architect check-data              # the 103 + 10 test requests
.venv/Scripts/python -m evaluation.architect run --set all --live    # AI-07, REAL calls: about $10–20
SKILLFORGE_RETRIEVER=fake .venv/Scripts/python -m evaluation.architect run --set seed --live
                                                                     # AI-12 on fixture passages: about $1–3
SKILLFORGE_RETRIEVER=fake .venv/Scripts/python -m evaluation.architect run --set seed --writers --live
                                                                     # AI-12 + AI-13 + AI-14: about $3–6
```

**The sets:**
- **`all` (AI-07):** the 3 example AnalyzedRequests, plus the 100 analyzer gate requests built **from their labels**. So the score measures the Architect alone. Vague requests count as "questions skipped".
- **`seed` (AI-12):** the clear request (`req-1`) of each of the 10 seed-benchmark skills, built from labels the same way. They come from the reviewed seed release 1.0.0 (`SEED_SET_RELEASE`). The analyzer gate keeps release 0.1.0, which it was measured on.
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
- **AI-13** (with `--writers`): all 10 valid, a file for every reference, 0 uncited claims.
  - The report also shows dropped and weakly supported claims, the descriptions and their fallbacks.
  - It lists **10 random claims** (seed 20261119), each with its cited chunk text, for a human check.
  - The files and descriptions go to the run folder (`references/`, `descriptions.json`).
- A fake run prints "does NOT count" for each of them.

## Dependency note
LangGraph is pinned at `1.2.14`, published on 6 Oct 2026. `pyproject.toml` sets `[tool.uv] exclude-newer = "2026-10-10T00:00:00Z"`, so `uv lock` only picks releases at least two weeks old, for every package, including LangGraph's own dependencies. When you upgrade:
1. Move the date forward, keeping it at least two weeks behind today.
2. Run `uv lock`.
3. Run the full test suite, then the live tests.
