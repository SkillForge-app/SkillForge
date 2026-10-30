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

## 1.0.0 (planned, by 6 Nov)
Every skill human-reviewed. This is the version handed to Data Engineering (DE-10).
