# AI-04 Seed Benchmark: Freeze and Handoff

Prepared: 30 Oct 2026  
Status: source review complete; team approval and final freeze remain pending.

## Current source snapshot

- 10 seed skills, all marked reviewed by Yousef Kamal.
- 80 test prompts, 60 should-not-trigger prompts, 41 near-misses, 62 rubric items and 30 labelled requests.
- The user confirmed that the benchmark validator passed after the review edits.
- The current source files are under evaluation/benchmarks/seed/skills/; the updated total is in docs/ai/seed-benchmark.md.

Review edits clarify safety and applicability criteria across code review, medical, HR, finance, marketing, legal and data-analysis rubrics. incident-postmortem.yaml needed no content changes in this review sequence.

## Release plan

- Keep evaluation/benchmarks/seed/releases/0.1.0/ unchanged. It is the immutable draft snapshot dated 23 Oct 2026, with 0 reviewed skills and 40 near-misses.
- Freeze the current source prompts on 3 Nov 2026 after the AI team completes its review and records approval.
- Prepare 1.0.0 as the final reviewed release by 6 Nov 2026, according to docs/ai/seed-benchmark.md and evaluation/benchmarks/seed/CHANGELOG.md.
- No new release has been generated yet.

## Team approval checklist

- [ ] AI team reviews the current ten skill files and the near-miss count change from 40 to 41.
- [ ] Reviewers approve the prompt, label and rubric changes before the 3 Nov freeze.
- [ ] From the repository ai/ directory, run the source validator:

    .\.venv\Scripts\python.exe -m evaluation.benchmarks validate

- [ ] After approval and freeze, generate the immutable final release:

    .\.venv\Scripts\python.exe -m evaluation.benchmarks release seed --version 1.0.0
    .\.venv\Scripts\python.exe -m evaluation.benchmarks verify

- [ ] Hand evaluation/benchmarks/seed/releases/1.0.0/ to Data Engineering for DE-10.
- [ ] Include dataset, version and dataset_sha256 from the release manifest in each evaluation run.

Versioning follows evaluation/benchmarks/seed/CHANGELOG.md; later prompt, rubric or label changes require a new MINOR version.