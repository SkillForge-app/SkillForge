# Evaluation harness (AI-16)

The harness uses an immutable AI-04 release. For each `test` prompt it generates one answer
with the compiler-generated skill instructions and one without them, then grades both answers
against the skill's rubric. The `should_not_trigger` set is evaluated separately by AI-17.

## Run a benchmark

Compile the SkillSpec with BE-09 and save the target's instruction artifact (for example
`CLAUDE.md` or `AGENTS.md`). Then run:

```powershell
cd ai
.\.venv\Scripts\python.exe -m evaluation.harness run `
  --release .\evaluation\benchmarks\seed\releases\1.0.0 `
  --skill ai-engineer `
  --instructions C:\path\to\compiled\CLAUDE.md `
  --live
```

`--live` is required for real provider calls. The command reports its planned answer/judge call
count before making calls. Live runs require a reviewed skill record in the release, a configured
provider key, and a new output directory. Reports record the dataset name, version and
`dataset_sha256`, the compiled-instruction SHA-256, prompt versions, model roles, per-arm rubric
scores and LLM usage. Do not edit or replace an existing report directory.

For code-level smoke tests, inject a fake gateway in tests. Fake model output is not evaluation
evidence and cannot satisfy AI-16.

## Calibrate the judge

Human labels are stored separately from the immutable benchmark because adding them is a later
minor dataset release. The harness accepts JSONL records with this shape:

```json
{
  "prompt_id": "ai-engineer/test-1",
  "prompt": "The exact benchmark prompt",
  "condition": "with_skill",
  "answer": "The exact answer reviewed by a person",
  "rubric_scores": {"ai-engineer/rubric-1": true},
  "reviewer": "reviewer-id"
}
```

Each record ties a review to an exact answer and includes one or more rubric decisions. The
prompt must match the pinned release, and rubric IDs must exist in that release. Run:

```powershell
.\.venv\Scripts\python.exe -m evaluation.harness calibrate `
  --release .\evaluation\benchmarks\seed\releases\1.0.0 `
  --skill ai-engineer `
  --labels .\human-labels.jsonl `
  --live
```

Calibration passes only when at least 80% of labeled rubric decisions match the judge. Missing
labels, failed judge calls, or an agreement below 80% do not pass. Calibration calls the judge on
the exact human-reviewed answers; it does not regenerate them.

## Current limitation

The checked-in workspace contains only seed release `0.1.0`, whose skills are marked `draft`, and
does not yet contain the later human-label release. It can support loader/unit tests only; it is
not valid evidence for an AI-16 live run or judge-calibration gate.
