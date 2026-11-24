# AI-16 report contract

The harness writes JSON reports plus JSONL detail files. Consumers should branch on the stable
`report_type`, `status`, and `error_code` fields, not exception messages.

## Files and statuses

| File | `report_type` / `record_type` | Status values |
|---|---|---|
| `report.json` | `benchmark` | `completed`, `completed_with_errors`, `failed` |
| `calibration.json` | `calibration` | `passed`, `failed` |
| `predictions.jsonl` | `prediction` | `completed`, `failed` |
| `comparisons.jsonl` | `calibration_decision` | `completed`, `failed` |

A benchmark run status describes execution, not whether the skill passed an evaluation gate.
`completed_with_errors` means at least one prompt failed; `failed` means no prompt completed.
Every benchmark report starts with `calibration.status = "not_calibrated"` because calibration
against reviewed human labels is a separate command. Calibration reports have status `passed`
when the raw agreement gate passes and `failed` when the gate fails or judge calls fail. The
calibration CLI requires a non-empty labels file; if labels are unavailable, it exits before
writing `calibration.json`.

Each error record retains `error` as the Python exception class for diagnostics and adds
`error_code` for programmatic handling. `metrics.errors` is keyed by these stable codes.

| Error code | Meaning |
|---|---|
| `budget_exceeded` | The model-call budget was exhausted. |
| `configuration_error` | LLM configuration is missing or invalid. |
| `invalid_input` | Prompt inputs were rejected. |
| `invalid_model_output` | Model output or its rubric IDs failed validation. |
| `model_refused` | The model refused the request. |
| `prompt_format_error` | A prompt template is malformed. |
| `prompt_not_found` | A configured prompt does not exist. |
| `provider_unavailable` | The provider is unavailable, rate limited, or timed out. |
| `unexpected_error` | An uncategorized per-item exception occurred. |

`error_code` is `null` on successful records. CLI argument, release-loading, and preflight errors
occur before a report is written; the CLI prints the diagnostic to stderr and exits with code 2.
Per-item failures are written to the JSONL file and produce a non-zero command exit.

The normative schema for report objects and individual JSONL records is
[report.schema.json](../../evaluation/harness/report.schema.json), using JSON Schema 2020-12.
Validate each line in a JSONL file as its own JSON object.

## Successful benchmark run (not yet calibrated)

This successful benchmark execution shows that all prompts ran; completion does not imply
calibration. Human labels are still required.

```json
{
  "report_type": "benchmark",
  "status": "completed",
  "created": "2026-11-24T20:00:00Z",
  "live": true,
  "dataset": "skillforge-seed-benchmark",
  "dataset_version": "1.0.0",
  "dataset_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "skill": "ai-engineer",
  "skill_instructions_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "review_status": "reviewed",
  "prompts": {
    "evaluation/answer": 2,
    "evaluation/judge": 1
  },
  "models": {
    "answer": "openrouter/anthropic/claude-sonnet-5.5",
    "judge": "openrouter/anthropic/claude-sonnet-5.5"
  },
  "metrics": {
    "n": 8,
    "completed": 8,
    "errors": {},
    "with_skill": {
      "rubric_items": 16,
      "passed": 15,
      "pass_rate": 0.9375,
      "critical_items": 8,
      "critical_passed": 8,
      "critical_pass_rate": 1.0
    },
    "without_skill": {
      "rubric_items": 16,
      "passed": 9,
      "pass_rate": 0.5625,
      "critical_items": 8,
      "critical_passed": 5,
      "critical_pass_rate": 0.625
    },
    "uplift": 0.375
  },
  "calibration": {
    "status": "not_calibrated",
    "n": 0,
    "matches": 0,
    "agreement": null,
    "threshold": 0.8,
    "passed": false,
    "reason": "calibrate separately against reviewed human labels",
    "cohen_kappa": null
  },
  "usage": {
    "calls": 32,
    "errors": 0,
    "input_tokens": 12000,
    "output_tokens": 4000,
    "cost_usd": 0.1234
  }
}
```

## Run with a failed prompt

The stored benchmark report uses `status = "completed_with_errors"` if some prompts completed.
The failed prompt's `predictions.jsonl` record includes a stable error code:

```json
{
  "record_type": "prediction",
  "status": "failed",
  "prompt_id": "ai-engineer/test-8",
  "error": "LLMUnavailable",
  "error_code": "provider_unavailable",
  "latency_ms": 1200.5
}
```

The report's `metrics.errors` then includes `{"provider_unavailable": 1}`. If every prompt fails,
the benchmark report status is `failed`.

## Calibration run with judge errors

Calibration decisions that could not be judged are retained and make the calibration status
`failed`, even if the remaining decisions meet the agreement threshold. The report below shows one
successful decision and one failed judge call:

```json
{
  "report_type": "calibration",
  "status": "failed",
  "created": "2026-11-24T20:05:00Z",
  "dataset": "skillforge-seed-benchmark",
  "dataset_version": "1.0.0",
  "dataset_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "skill": "ai-engineer",
  "live": true,
  "human_labels_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "judge_prompt_version": 1,
  "judge_model": "openrouter/anthropic/claude-sonnet-5.5",
  "usage": {
    "calls": 2,
    "errors": 1,
    "input_tokens": 800,
    "output_tokens": 200,
    "cost_usd": 0.0123
  },
  "result": {
    "n": 2,
    "matches": 1,
    "agreement": 0.5,
    "threshold": 0.8,
    "passed": false,
    "reason": "judge calls failed",
    "cohen_kappa": null
  }
}
```

The corresponding `comparisons.jsonl` record has `record_type = "calibration_decision"`,
`status = "failed"`, and an `error_code`. A valid calibration with agreement below 80% also has
status `failed`, with `result.reason = "agreement is below 80%"`; Cohen's kappa remains
informational and never changes the gate.
