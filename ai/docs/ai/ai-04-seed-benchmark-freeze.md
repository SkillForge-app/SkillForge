# AI-04 Seed Benchmark: Freeze and Handoff

Prepared: 30 Oct 2026  
Updated: 16 Nov 2026
Status: reviewed source frozen; immutable release 1.0.0 generated and verified; included in this change for DE-10 handoff.

## Frozen source snapshot

- 10 seed skills, all marked reviewed by Yousef Kamal.
- 80 test prompts, 60 should-not-trigger prompts (41 near-misses), 62 rubric items and 30 labelled requests.
- AI department reviewer approval for the integrated AI source was recorded on PR #4 on 10 Nov, after the AI-04 review changes landed; PR #4 merged into main on 13 Nov.
- The source validator passed: 10 skills and all expected dataset counts, with 10 reviewed.

Review edits clarify safety and applicability criteria across code review, medical, HR, finance, marketing, legal and data-analysis rubrics. incident-postmortem.yaml needed no content changes in this review sequence.

## Release 1.0.0

- Keep `evaluation/benchmarks/seed/releases/0.1.0/` unchanged. It remains the immutable draft snapshot dated 23 Oct 2026, with 0 reviewed skills and 40 near-misses.
- Generated `evaluation/benchmarks/seed/releases/1.0.0/` on 16 Nov 2026 from the reviewed source on main commit `163af0adddf2f02dfe1aed7f85be52caaaae9cfb`.
- Release verification passed for both `0.1.0` and `1.0.0`.
- The 1.0.0 manifest records 10 reviewed skills, 80 test prompts, 60 should-not-trigger prompts, 62 rubric items and 30 labelled requests.
- `dataset_sha256`: `67bb9b8cb14183181ce8a80a260626e3006a5508a22e5a7523cb464b46b8b605`.

## Handoff to Data Engineering (DE-10)

The immutable `evaluation/benchmarks/seed/releases/1.0.0/` folder is included in this change for DE-10. Once merged, Data Engineering can use that release as the fixed evaluation dataset.

Each evaluation run must record `dataset` (`skillforge-seed-benchmark`), `version` (`1.0.0`) and `dataset_sha256` from the manifest. Later prompt, rubric or label changes require a new MINOR version; no committed release is edited in place.
