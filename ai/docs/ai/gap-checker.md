# Gap Checker (AI-08)

It answers one question before anything is generated: does a good skill for this request already exist? It lives in `ai/core/analysis/gap_checker.py`.
- **Where it sits:** Request Analyzer → **Gap Checker** → Knowledge Collector → Skill Architect.
- **Input:** an `AnalyzedRequest` (contract A3), after clarification.
- **What it searches:** the SkillForge registry (BE-11) and the public SKILL.md corpus (DE-08). Each one is a `SkillIndex`.

```python
from core.analysis import check_gap

result = await check_gap(analyzed, indexes=[registry_index, corpus_index], k=5)
result.verdict       # "exists" | "similar" | "new"
result.matches       # best first: GapMatch(skill=SkillCard, score=cosine)
result.exists_threshold, result.similar_threshold, result.model, result.settings_version
```

| Verdict | When | FE-09 offers |
|---|---|---|
| `exists` | top score ≥ the `exists` threshold | Use the existing skill |
| `similar` | top score ≥ the `similar` threshold | Customize it |
| `new` | below both, or no skills at all | Generate a new skill |

- **The verdict comes from the top match only.** The other matches are listed for the UI.
- **An index built with a different embedding model** (or dimension) raises `ConfigError`, the same rule as the knowledge index (AI-11).

## What gets embedded, and why
Both sides become one short text, embedded with the `embedding` role (the local `BAAI/bge-small-en-v1.5`, 384 dimensions; no key, no network once downloaded).

- **The request:** `request_text(analyzed)`, e.g. "A task skill for legal contracts. A skill that reviews NDAs before signing. Outputs: clause risk list."
  - It holds the analyzer's English `summary`, the `kind`, the domain words and the `expected_outputs`.
  - **The summary, not the raw request:** it is one English sentence, already normalised, and it includes the clarification answers. The raw text can be Arabic, chatty or 4000 characters.
  - **Left out:** audience, targets and the raw text, which say nothing about what the skill does.
- **A skill:** `skill_text(card)`: title, kind, domain words, description and the `use_when` triggers. That is what the skill does and when to load it, the same facts as the request side.
  - **`avoid_when` is never embedded.** It describes exactly the near-misses ("drafting other contract types"), so including it would make those requests look *more* similar.
- **Variants compared on dev:** at most four, so tuning cannot fit the dev set.
  - summary only, versus the structured text
  - BGE's query prefix on the request side, or not
  - an "area gate", where `exists` also needs the same domain area
  - The choice is in `core/analysis/gap_checker.yaml`.

## Thresholds
`core/analysis/gap_checker.yaml` holds the request-text variant, the query-prefix and area-gate switches, `exists`, `similar`, and `tuned_on` (the report that set them).
- **`exists`:** the best **F0.5** on dev pairs labelled `match`. Precision counts double, because a wrong "this already exists" sends the user away from generating.
- **`similar`:** the best F1 on dev pairs labelled `match` or `near_miss`, below `exists`.
- **Re-tuning:** run `python -m evaluation.gap tune`. It writes a new dev report and the YAML; the change goes in by pull request with that report.
- **Current settings** (`evaluation/gap/reports/gap-dev-2026-10-28.md`): `structured` request text, no query prefix, no area gate, `exists` ≥ 0.8584, `similar` ≥ 0.7664.
  - On dev, `exists` scored P 100%, R 87%.
  - The area gate tied with plain `structured`, so the simpler variant was kept.

## The labelled set and the done-when number
- **Cards:** `tests/fixtures/gap/skills.yaml`, 48 of them, all in our own words:
  - the 10 seed skills (3 built from their example specs with `SkillCard.from_spec`)
  - 38 distractors, many of them deliberate near-misses (`draft-nda-template` next to `review-nda`, `sql-query-helper` next to `data-analyst`, ...)
- **Labels:** `evaluation/gap/pairs-dev.yaml` (41 requests) and `pairs-test.yaml` (61 requests), with each request labelled against every card: `match`, `near_miss` or (unlisted) `no_match`. The rules are in `evaluation/gap/LABELLING.md`.
- **Commands:**
  - `python -m evaluation.gap check-data`
  - `python -m evaluation.gap tune`: dev only.
  - `python -m evaluation.gap report`: test, run once. It refuses draft test labels and untuned settings.
- **Done when:** the pair-level precision of `exists` on test, with its 95% Wilson interval, in `evaluation/gap/reports/gap-test-<date>.md`.
- **Result** (`gap-test-2026-10-28.md`, labels reviewed by Ziad Abdullah on 2026-10-27, run once):
  - `exists`: precision **92.3%** (24 of 26, 95% CI 76–98%), recall 70.6%.
  - `related`: precision 79.2%, recall 70.9%.
  - 43 of 61 request verdicts are correct, and the top skill is a match for 33 of 34.
  - The interval is wide because only 26 pairs scored above `exists`.

## For BE-11 (registry) and DE-08 (corpus): implementing `SkillIndex`
```python
class SkillIndex(Protocol):
    def info(self) -> IndexInfo: ...                     # count, embedding model, dimensions
    async def search(self, vector, k) -> list[tuple[SkillCard, float]]: ...   # cosine, best first
```
- **Card fields:**
  - `id`, unique across indexes (`registry:<name>`, `corpus:<name>`)
  - `name`, `title`, `description` (at most 300 chars), `kind`, `domain`, `use_when` (at most 10), `source`
  - `url` and `licence` for corpus cards. Only permissively licensed SKILL.md files go in (DE-08).
- **From a SkillSpec:** `SkillCard.from_spec(spec)` builds the card, which suits BE-11's published skills.
- **Vectors:** embed `skill_text(card)` with `core.llm.embed(..., model_role="embedding")`, keep them unit length, and rank by cosine (`1 - (embedding <=> query)` in pgvector).
  - Store the model string `local/BAAI/bge-small-en-v1.5` with them, so `info().model` can be checked.
  - The pinned model files are in `docs/ai/retrieval.md` (for `embedding_version`).
- **Re-embed** a card when its title, description, kind, domain or `use_when` changes.

## Pipeline: a proposed step (not wired yet)
Wiring the gap check into `core/pipeline/interface.py` changes the BE contract, so it waits for AI and BE to agree. The proposal:
- **The step:** `StepName` gains `"gap_check"`, and `AIPipeline` gains `async def check_gap(analyzed) -> StepResult[GapCheck]`.
  - `ok` with a `GapCheck` value
  - `retry_later` if an index is unavailable
- **Where BE's worker calls it:** after `clarify` (or after `analyze` when no questions were asked) and before `design`.
  - On `exists` or `similar`, FE-09 shows the choices.
  - `design` runs only when the user chooses "generate new".
- **`FakePipeline`** gains the same method, with a settable verdict.

Until then, BE can call `core.analysis.check_gap` directly.

## Known limits
- **The fixture cards are ours.** Real corpus descriptions are longer and noisier, so re-tune when DE-08's corpus exists.
- **Vague requests score low.** Run the check after clarification.
- **One embedding per side.** A skill whose description says little will be missed; better card text is the main lever.
