# Seed benchmark (AI-04)

Owner: AI department (Track B, contract **B2**). Test prompts: 3 Nov 2026 (release `0.1.0`). Final: 6 Nov 2026 (release `1.0.0`, handed to Data Engineering for DE-10).

The seed benchmark is the fixed test set every SkillForge skill version is measured against:
- **AI-16 (evaluation harness):** each test prompt is run with and without the skill, and the answer is graded with the skill's rubric.
- **AI-17 (trigger accuracy):** test prompts must load the skill, and should-not-trigger prompts must not.
- **AI-23 (optimizer):** a new version of a skill must beat the old one on the same benchmark version.

## Contents

| Skill | Kind | Domain | Risk | Technical | SkillSpec |
|-------|------|--------|------|-----------|-----------|
| ai-engineer | role | technology/ai | low | yes | `examples/skillspec/ai-engineer.yaml` |
| marketing-strategist | role | marketing/strategy | low | no | `examples/skillspec/marketing-strategist.yaml` |
| review-nda | task | legal/contracts | high | no | `examples/skillspec/review-nda.yaml` |
| data-analyst | role | data/analytics | low | yes | none yet (AI-07/AI-12) |
| code-reviewer | task | technology/software-engineering | low | yes | none yet |
| incident-postmortem | workflow | technology/incident-response | low | yes | none yet |
| write-press-release | task | writing/public-relations | low | no | none yet |
| hr-recruiter | role | hr/recruiting | medium | no | none yet |
| explain-medical-results | task | medical/patient-education | high | no | none yet |
| small-business-budgeting | task | finance/small-business | high | no | none yet |

**Every skill has:**
- 8 test prompts. They mix short and detailed prompts and include edge cases.
- 6 should-not-trigger prompts, at least 3 of them tagged `near-miss`. A near-miss looks like this skill but isn't. `closer_skill` names the seed skill that should answer it, when there is one.
- 5 to 8 rubric items, each of type `quality`, `procedure`, `guardrail` or `format`. A `critical` item fails the answer if it is missed.
- 3 labelled skill requests, one each of the styles `clear`, `vague` and `detailed`.

**Totals:** 80 test prompts, 60 should-not-trigger prompts (41 near-misses), 62 rubric items and 30 labelled requests. All of it is synthetic, with no real people, companies or personal data.

## Editing

The files people edit are `ai/evaluation/benchmarks/seed/skills/<name>.yaml`; the format is in that folder. Validate your changes:

```bash
cd ai
.venv/Scripts/python -m evaluation.benchmarks validate
```

The validator reports issues in the SkillSpec format, e.g. `skills/review-nda.yaml#/requests/2/labels/kind  label_mismatch`. It checks:
- the exact sizes above
- unique ids within a file, and unique texts across the whole dataset (case and spacing ignored)
- **risk:** `high` exactly for the legal, medical and finance areas, and a high-risk skill needs a critical `guardrail` rubric item
- **labels:** each request's kind, domain and risk equal the skill's
- **existing SkillSpecs:** for the 3 skills that have one, every `evaluation` prompt in the spec must also be in the benchmark, word for word. So the spec and the benchmark never disagree.
- **coverage:** 10 skills, at least 4 technical and at least 4 non-technical, all 3 kinds, and all 3 high-risk areas

## Review and release

1. **Review.** A person reads every prompt and rubric item of a skill, edits what is wrong, then sets `review: {status: reviewed, reviewer: <name>}`.
2. **Release.** Run `python -m evaluation.benchmarks release seed --version X.Y.Z`. This validates the sources and writes `releases/X.Y.Z/`:

   | File | Content |
   |------|---------|
   | `skills.jsonl`, `prompts.jsonl`, `rubrics.jsonl`, `requests.jsonl` | One JSON record per line. Ids are `<skill>/<id>` and stay stable across versions |
   | `schemas/*.schema.json` | The JSON Schema for each record type |
   | `README.md` | The data card |
   | `manifest.json` | Counts, review status, the sha256 of every file, and `dataset_sha256` |

3. **Version rules:**
   - MAJOR: the record schema changes
   - MINOR: any prompt, rubric item or label changes; scores are not comparable across minor versions
   - PATCH: metadata or the data card only
4. **Releases are immutable.**
   - The command refuses to overwrite an existing version.
   - The command refuses `1.0.0` or later while any skill is still `draft`.
   - `python -m evaluation.benchmarks verify` and a test check every committed release against its manifest.
   - `ai/.gitattributes` stops Git from converting line endings in releases, because Windows `core.autocrlf` would break the hashes.

## Hand-off to Data Engineering (DE-10)

Give DE the release folder `ai/evaluation/benchmarks/seed/releases/1.0.0/` once it exists. Until then, `0.1.0` is a draft they can use to build their storage.
- **Each evaluation run must record** `dataset` (`skillforge-seed-benchmark`), `version` and `dataset_sha256` from `manifest.json`.
- **Human labels** (AI-16 judge calibration) will come as a later MINOR release, with a new file. The existing files don't change.

## Reuse for AI-05 (Request Analyzer)

AI-05 must reach at least 90% correct on 100 labelled **skill requests**: what a user types to *create* a skill. Benchmark test prompts are something else: tasks given to an agent that already *has* the skill. So:

| Data | Usable for AI-05? |
|------|-------------------|
| `requests.jsonl` (30 records) | **Yes, fully labelled.** Each record has `text`, `style` (clear, vague, detailed), `kind`, `domain`, `domain_area`, `risk` (low, medium, high) and `targets`. It covers all 3 kinds, 8 domain areas and all 3 risk levels (18 low, 3 medium, 9 high). |
| `prompts.jsonl`, `kind: test` (80) | **Domain label only.** Each record carries its skill's `domain`, which is useful as extra domain-classification data. There is no kind or risk label, because those belong to the skill, not the task. |
| `prompts.jsonl`, `kind: should_not_trigger` (60) | **No.** They are hard negatives for trigger tests. `closer_skill` may help the Gap Checker (AI-08) later. |

**Still to do for AI-05:**
- About 70 more labelled skill requests are needed to reach 100. They should include domain areas the seed set doesn't cover (sales, design, product, operations, education, research, customer-support, general) and harmful requests for AI-06.
- **Labels use one shared vocabulary.** Kind, domain area, risk level (`RiskLevel`: low, medium, high) and targets all come from `core.spec`, and AnalyzedRequest (A3) imports them from the same place. A test checks that the benchmark uses the shared `RiskLevel` rather than a copy.
