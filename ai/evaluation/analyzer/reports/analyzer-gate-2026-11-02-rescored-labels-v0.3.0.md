# Request Analyzer gate, rescored against labels v0.3.0, same 2 Nov predictions, no model calls

**This is a rescore, not a new run.** The 100 predictions are the ones the live gate run of 2026-11-02T18:27:10Z saved (run `20261102T182823Z`, prompt analysis/request v1, model `openrouter/anthropic/claude-sonnet-5.5`). They were scored again against the labels after the 19 Nov label review ([record](../reviews/label-review-2026-11-19.md)). No model was called and nothing cost money. The original report, [analyzer-gate-2026-11-02.md](analyzer-gate-2026-11-02.md), is unchanged.

**Gate (each field >= 90% on 100 requests): FAILED** (2 Nov: PASSED)
- kind accuracy 0.88 < 0.90

| Field | 2 Nov labels | Labels after the review | Change |
|---|---|---|---|
| kind | 92% (92/100) | 88% (88/100) | -4 |
| domain area | 95% (95/100) | 95% (95/100) | +0 |
| risk | 96% (96/100) | 96% (96/100) | +0 |
| joint (all three; not gated) | 84% | 81% | |
| needs_clarification accuracy (not gated) | 100% | 100% | |

## Labels that changed in the gate, against the saved prediction

| id | field | 2 Nov label | new label | predicted | before | after |
|---|---|---|---|---|---|---|
| t-45 | kind | `role` | `task` | `role` | right | wrong |
| t-56 | kind | `role` | `task` | `role` | right | wrong |
| t-65 | kind | `role` | `task` | `role` | right | wrong |
| t-68 | kind | `task` | `role` | `task` | right | wrong |

## How it was computed

1. **Check:** the saved predictions' `expected` values equal the old labels (`origin/AI` `cd4423b`), and scoring them again reproduces the 2 Nov report exactly (accuracy, correct counts, confusion, joint, needs_clarification).
2. **Rescore:** the same predictions against the new labels (`2d351b6`), with the same rules as `evaluate.py` (`GATED_FIELDS`, the 90% threshold).
3. **Carried over unchanged:** mentioned_targets, latency_ms and needs_clarification.question_rule_kept come from the 2 Nov report: they need fields the saved predictions do not keep, and no label they depend on changed.

Data: skillforge-seed-benchmark 0.1.0 (f0a92ff2f445), analyzer-requests-test 0.3.0 (2a96507e736e); predictions sha256 5405bfcb502b (run folder, not tracked).
