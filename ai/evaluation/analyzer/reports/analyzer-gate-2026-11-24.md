**INVALID: provider failure (48 of 100 requests got no prediction). Not a measurement of the prompt.**

# Request Analyzer evaluation, 2026-11-24T23:41:09Z

Mode: LIVE. Prompt analysis/request v3, model `openrouter/anthropic/claude-sonnet-5.5`.

**Retry rule (decided before this run):** A request that fails with a provider error (no prediction at all) is retried ONCE at the end of the run, with the same prompt and settings. If it fails again, it counts as wrong.

Retried: 49; succeeded on retry: 1; still failed (counted wrong): 48.

| set | id | first error | retry |
|---|---|---|---|
| gate | t-15 | LLMUnavailable | LLMUnavailable |
| gate | t-16 | LLMUnavailable | ok |
| gate | t-18 | LLMUnavailable | LLMUnavailable |
| gate | t-19 | LLMUnavailable | LLMUnavailable |
| gate | t-20 | LLMUnavailable | LLMUnavailable |
| gate | t-21 | LLMUnavailable | LLMUnavailable |
| gate | t-22 | LLMUnavailable | LLMUnavailable |
| gate | t-23 | LLMUnavailable | LLMUnavailable |
| gate | t-24 | LLMUnavailable | LLMUnavailable |
| gate | t-25 | LLMUnavailable | LLMUnavailable |
| gate | t-26 | LLMUnavailable | LLMUnavailable |
| gate | t-27 | LLMUnavailable | LLMUnavailable |
| gate | t-29 | LLMUnavailable | LLMUnavailable |
| gate | t-30 | LLMUnavailable | LLMUnavailable |
| gate | t-31 | LLMUnavailable | LLMUnavailable |
| gate | t-32 | LLMUnavailable | LLMUnavailable |
| gate | t-33 | LLMUnavailable | LLMUnavailable |
| gate | t-34 | LLMUnavailable | LLMUnavailable |
| gate | t-35 | LLMUnavailable | LLMUnavailable |
| gate | t-37 | LLMUnavailable | LLMUnavailable |
| gate | t-38 | LLMUnavailable | LLMUnavailable |
| gate | t-39 | LLMUnavailable | LLMUnavailable |
| gate | t-40 | LLMUnavailable | LLMUnavailable |
| gate | t-42 | LLMUnavailable | LLMUnavailable |
| gate | t-43 | LLMUnavailable | LLMUnavailable |
| gate | t-44 | LLMUnavailable | LLMUnavailable |
| gate | t-45 | LLMUnavailable | LLMUnavailable |
| gate | t-46 | LLMUnavailable | LLMUnavailable |
| gate | t-48 | LLMUnavailable | LLMUnavailable |
| gate | t-49 | LLMUnavailable | LLMUnavailable |
| gate | t-50 | LLMUnavailable | LLMUnavailable |
| gate | t-51 | LLMUnavailable | LLMUnavailable |
| gate | t-52 | LLMUnavailable | LLMUnavailable |
| gate | t-55 | LLMUnavailable | LLMUnavailable |
| gate | t-56 | LLMUnavailable | LLMUnavailable |
| gate | t-57 | LLMUnavailable | LLMUnavailable |
| gate | t-58 | LLMUnavailable | LLMUnavailable |
| gate | t-59 | LLMUnavailable | LLMUnavailable |
| gate | t-60 | LLMUnavailable | LLMUnavailable |
| gate | t-61 | LLMUnavailable | LLMUnavailable |
| gate | t-62 | LLMUnavailable | LLMUnavailable |
| gate | t-63 | LLMUnavailable | LLMUnavailable |
| gate | t-64 | LLMUnavailable | LLMUnavailable |
| gate | t-65 | LLMUnavailable | LLMUnavailable |
| gate | t-66 | LLMUnavailable | LLMUnavailable |
| gate | t-67 | LLMUnavailable | LLMUnavailable |
| gate | t-68 | LLMUnavailable | LLMUnavailable |
| gate | t-69 | LLMUnavailable | LLMUnavailable |
| gate | t-70 | LLMUnavailable | LLMUnavailable |

**Gate (each field >= 90% on 100 requests): FAILED**
- kind accuracy 0.41 < 0.90
- domain_area accuracy 0.49 < 0.90
- risk accuracy 0.51 < 0.90

| Set | n | kind | domain area | risk | joint | clarify acc. | errors |
|---|---|---|---|---|---|---|---|
| gate | 100 | 41% | 49% | 51% | 38% | 86% | 48 |

Usage: 355 calls, 213048 input / 13917 output tokens, $0.5742 (budget $1.3).

Data: skillforge-seed-benchmark 0.1.0 (f0a92ff2f445), analyzer-requests-test 0.3.0 (2a96507e736e), analyzer-requests-dev 0.3.0 (44f94ce3f577), analyzer-requests-arabic 0.2.0 (6d4d6fb52f4a), analyzer-requests-holdout 0.1.0 (c849f354948f)
