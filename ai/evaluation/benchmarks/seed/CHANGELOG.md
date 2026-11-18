# skillforge-seed-benchmark changelog

Version rules:
- **MAJOR**: the record schema changes.
- **MINOR**: any prompt, rubric item or label is added, changed or removed. Scores can't be compared across minor versions.
- **PATCH**: metadata or the data card only.

Releases are immutable. Record `dataset`, `version` and `dataset_sha256` from `manifest.json` with every evaluation run.

## 0.1.0 (2026-10-23, draft)
First complete draft, for B2's "test prompts" milestone (3 Nov).
- 10 seed skills: 4 technical and 6 non-technical. They cover all 3 kinds and all 3 high-risk areas (legal, medical, finance).
- 80 test prompts, 60 should-not-trigger prompts (40 tagged near-miss), 62 rubric items and 30 labelled skill requests.
- No skill has been reviewed by a person yet; every `review_status` is `draft`.

## 1.0.0 (2026-11-16)
Final reviewed release for DE-10.
- All 10 seed skills are human-reviewed; 0 remain draft.
- 80 test prompts, 60 should-not-trigger prompts (41 near-misses), 62 rubric items and 30 labelled requests.
- `dataset_sha256`: `67bb9b8cb14183181ce8a80a260626e3006a5508a22e5a7523cb464b46b8b605`.
- `releases/0.1.0/` remains unchanged.
