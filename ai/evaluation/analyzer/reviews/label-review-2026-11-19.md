# AI-05 label review, 19 Nov 2026

**Decisions:** Ziad (AI lead). **Reviewers:** Gemini and ChatGPT. Their role:
- They were advisory only and worked independently.
- Neither is a Claude model, the model the analyzer runs on.
- They suggested changes, and every change below was decided by a person.

**The rules were set before the predictions were seen.** The two rules added to [LABELLING.md](../LABELLING.md) and the reworded style rule were all written, and every label decided, before any model prediction was looked at. The saved 2 Nov predictions were opened only afterwards, to rescore them.

## Scope
- **Reviewed:** the 100 AI-05 label files:
  - `requests-test.yaml` 0.2.0 (70, the gate's part 2);
  - `requests-dev.yaml` 0.1.0 (20);
  - `requests-arabic.yaml` 0.1.0 (10).
- **Not reviewed:** the 30 seed-benchmark requests in the gate (`skillforge-seed-benchmark` 0.1.0, AI-04). Their labels come from the benchmark skills and are unchanged.

## Method
1. **The packets:** the 100 requests went into four packets of 25. Each packet opened with LABELLING.md word for word and the allowed values. Each item showed its id, split, text, current labels and the labeller's notes.
2. **The answers:** each reviewer answered per (id, field) with a suggested value, a confidence (low, medium or high) and a reason. Empty meant "keep".
3. **The decision table:** every reviewer row was checked against the labels in the files (all matched). There were 56 (id, field) suggestions:
   - 6 where both reviewers agree;
   - 24 on kind, domain or risk from one reviewer only;
   - 26 on style.
4. **Repeated patterns** were decided against the exact rule text:
   - **A, "a person who does one job only":** accepted for t-45, t-56 and t-65. t-06 stays `role`, because "act like our product manager" is the rule's own example of a role.
   - **B, style by sentence count:** Gemini suggested `detailed` → `clear` for 26 items, because the old rule said clear is "one or two sentences".
     - **The count:** sentences were counted by code, not judgement (a sentence ends at `.`, `!`, `?` or `؟` followed by a space or the end of the text). 25 of the 26 have two sentences or fewer; t-60 has three.
     - **What broke:** applying the 25 would have cut the gate's `detailed` requests from 33 to 15, below the gate's coverage rule (`MIN_PER_STYLE = 25` in `data.py`). That rule makes sure the analyzer is tested on long, multi-part requests.
     - **The decision:** **reword the rule and keep the labels**. `detailed` now means context plus several tasks or constraints, even in two sentences. All 26 keep their label. `style` isn't scored by the gate either way.
   - **C, the kind of a vague request:** decided from the existing human labels, which were `role` for 16 of the 19 vague requests the reviewers flagged. That became the new rule. The other three (t-68, d-16, a-10) change to `role`, and the 16 role → task suggestions were rejected.
5. **The rest** were decided item by item (see "Kept" below).

## Rules changed in LABELLING.md
- **Added under `kind`:** "A vague request is labelled role."
- **Added under `risk`:** "Personal data means records about identifiable people (customers, employees, patients, students), not a user describing someone's tastes in passing. Decisions about people means judging or ranking them (hiring, grading, performance), not scheduling."
- **Reworded under `style`:**
  - **clear** was "one or two sentences that say what the skill does". It's now "says what the skill does, in one or two sentences, without giving context plus several tasks or constraints".
  - **detailed** was "several sentences with context, tasks and constraints". It's now "gives context plus several tasks or constraints, even in two sentences. Length alone doesn't decide."

## Changes (7 labels; versions bumped)

| File | Version | Changes |
|---|---|---|
| `requests-test.yaml` | 0.2.0 → 0.3.0 | `kind` role → task: t-45, t-56, t-65. `kind` task → role: t-68 |
| `requests-dev.yaml` | 0.1.0 → 0.2.0 | `kind` task → role: d-16 |
| `requests-arabic.yaml` | 0.1.0 → 0.2.0 | `kind` task → role: a-10. `risk` low → medium: a-01 (middle-school students, so it works with minors) |

- **What moved:** in the gate's test part, 4 `kind` labels changed; no domain or risk label did.
- **What it doesn't touch:** no `style` label changed, and neither did `needs_clarification` or the gate's style coverage.

## Kept as they are (suggestions rejected)
- **t-06** `kind` role: the rule's own role example.
- **t-39** `risk` low: a user describing someone's tastes isn't personal data (the new risk paragraph).
- **t-55** `risk` medium: HR work, as the labeller's notes say.
- **d-14** `risk` low: staff rotas are scheduling, not judging people.
- **d-17** `risk` medium: the order history of identifiable customers is personal data.
- **d-02** `risk` low.
- **d-19:** unchanged (role, `general/small-business`, with its notes).
- **The 26 style suggestions** (Pattern B): the rule was reworded instead.
- **The 16 role → task suggestions on vague requests** (t-03, t-08, t-13, t-18, t-23, t-28, t-38, t-46, t-51, t-69, d-05, d-09, d-12, d-19, a-02, a-05): rejected under the new kind rule.

## Known limitation
**Kind is inherently ambiguous for vague requests.** The gate mixes two sources of `kind`:
- **The AI-05 files:** the kind is set by a rule ("A vague request is labelled role").
- **The 30 seed-benchmark requests:** the kind comes from the benchmark skill the request was written for.

**6 of the seed's 10 vague requests are not labelled `role`.** They stay as they are, because seed 0.1.0 is a released AI-04 dataset:

| Seed id | kind |
|---|---|
| `code-reviewer/req-2` | task |
| `explain-medical-results/req-2` | task |
| `incident-postmortem/req-2` | workflow |
| `review-nda/req-2` | task |
| `small-business-budgeting/req-2` | task |
| `write-press-release/req-2` | task |
