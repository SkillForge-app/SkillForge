# AI-05 new requests, 24 Nov 2026

**Decisions:** Ziad (AI lead). **Labellers:** ChatGPT and Gemini. Their role:
- They labelled independently, each from the same packets and the same prompt.
- Neither is a Claude model, the model the analyzer runs on.
- Where they disagreed, the label was settled by a rule or decided by a person (below).

**No prompt work used these requests.** The split, the near-duplicate rule, the two new rules and every decision were made before any prompt work and before any model prediction on them.

## The requests
- **54 requests**, written by SkillForge team members and collected by Ziad on 2026-11-24, in three sources:
  - **A (25):** a PDF copy; only PDF ligature artifacts were fixed, the wording was kept.
  - **B (14):** learning requests; PDF presentation-form letters were normalised to plain Arabic.
  - **C (15):** pasted as written, typos kept.
- They are in Egyptian Arabic, English or a mix. They name no real people or companies and hold no personal data.
- They were numbered n-01 to n-54 for labelling. The tables below map them to their ids in the files.

## The split (decided before labelling)
1. **Seeded:** the 54 ids were sorted and shuffled with `random.Random(20261124)`: the first 34 went to dev, the last 20 to holdout.
2. **Near-duplicate rule:** near-duplicate pairs are always on the same side. 7 pairs were found by reading (none is an exact duplicate, of each other or of any existing set). The dev member of a split pair moves into holdout, repeated until no pair is split (two pairs share a request, so one move split another pair). **4 moved**, giving **30 dev and 24 holdout**.
3. **The holdout** (`requests-holdout.yaml`, new) is reported only: it is not part of the 90% gate, and it is never used for prompt work.

## Labelling
1. **The packets:** dev in two packets (15 and 15), holdout in one (24). Each opened with LABELLING.md word for word (with the 19 Nov rules) and the allowed values, then each request's id and text with empty labels.
2. **The labellers:** ChatGPT and Gemini, each given every packet with the same instruction: label every field from the rules and allowed values only, strictly and independently, and give a note only for a judgement call.
3. **The decision table:** a gated field (kind, domain area, risk) was **AGREED** when both gave the same valid value, otherwise **DECIDE**.

| gated field | dev: agreed / decide | holdout: agreed / decide |
|---|---|---|
| kind | 26 / 4 | 21 / 3 |
| domain area | 21 / 9 | 20 / 4 |
| risk | 29 / 1 | 20 / 4 |

4. **Invalid labeller values** were recorded and not used:
   - ChatGPT, holdout packet: all 24 domains had no sub-area (the area alone was compared), and one risk was `safe`.
   - Gemini, holdout packet: one note was 245 characters (the limit is 200).
5. **The DECIDE rows** fell into patterns: learning requests (area `education` vs the subject's area, and role vs task), fitness and nutrition (`general` vs `medical`), vague vs clear/detailed (which pulled the kind to role), and a few single items. Ziad settled them with two new rules and item decisions.

## Rules added to LABELLING.md
- **Under `kind` (the tutor rule):** "A request to learn a subject is a tutor: kind role, area education, sub-area = the subject."
- **Under `risk` (the fitness rule):** "Fitness and nutrition for healthy people (calories, protein, workouts) is area general, risk low. It is medical only when the request names a condition, a medication or a treatment."
- **Data hygiene:** the no-duplicates rule now names the holdout set too.

The tutor rule also overrides one agreement: both labellers gave `general` for "learn time management" (holdout); the rule makes it `education/time-management`, for consistency.

## Item decisions (Ziad)
- **kind:** n-04 task (one job: the day's protein); n-53 role; n-40 role (both labellers said `vague`, and "A vague request is labelled role" applies); n-42 role; n-47 role; n-41 task.
- **area:** n-41 writing; n-14 data; n-49 technology.
- **risk:** n-22 low; n-01 low.

## Style and the sub-area (mechanical, not judgement)
- **Style tie-break:** where the two labellers disagreed on style, the label is `clear`. `needs_clarification` follows style (true exactly when vague). Style isn't scored by the gate.
- **Sub-area** (not scored; approved by Ziad):
  - learning (tutor) requests: Gemini's `education/<subject>`, because Gemini named the subject on every learning request;
  - all others: ChatGPT's domain when it is valid and has the final area, otherwise Gemini's.

## Result
| | dev (d-21 to d-50) | holdout (h-01 to h-24) |
|---|---|---|
| requests | 30 | 24 |
| sources | A 14, B 6, C 10 | A 11, B 8, C 5 |
| kind | role 10, task 20 | role 9, task 13, workflow 2 |
| risk | high 1, low 28, medium 1 | high 1, low 23 |
| style | clear 25, vague 5 | clear 22, vague 2 |
| areas | education 8, design 4, technology 4, writing 4, data 2, marketing 2, customer-support 1, general 1, hr 1, legal 1, operations 1, product 1 | education 11, writing 5, general 4, design 1, finance 1, marketing 1, technology 1 |
| mentioned_targets | all `[]` | all `[]` |

**Versions:** `requests-dev.yaml` 0.2.0 → 0.3.0 (20 → 50); `requests-holdout.yaml` 0.1.0 (new, 24). The gate set (seed + `requests-test.yaml`) and `requests-arabic.yaml` are unchanged.

## Id mapping and the source of each label
The "label source" column says where each label came from. **AGREED** means both labellers agreed on every gated field and on style. Otherwise it names, with the fields in brackets, the **RULE** (tutor, fitness or style-tie-break) or the **DECIDED-BY-ZIAD** decision that set them.

### Dev
| new id | from | source | label source |
|---|---|---|---|
| d-21 | n-02 | A | RULE style-tie-break (style) |
| d-22 | n-06 | A | RULE style-tie-break (style) |
| d-23 | n-07 | A | RULE style-tie-break (style) |
| d-24 | n-10 | A | RULE style-tie-break (style) |
| d-25 | n-14 | A | DECIDED-BY-ZIAD (domain) |
| d-26 | n-15 | A | AGREED |
| d-27 | n-18 | A | RULE style-tie-break (style) |
| d-28 | n-19 | A | RULE style-tie-break (style) |
| d-29 | n-20 | A | RULE style-tie-break (style) |
| d-30 | n-21 | A | RULE style-tie-break (style) |
| d-31 | n-22 | A | DECIDED-BY-ZIAD (risk); RULE style-tie-break (style) |
| d-32 | n-23 | A | AGREED |
| d-33 | n-24 | A | RULE style-tie-break (style) |
| d-34 | n-25 | A | RULE style-tie-break (style) |
| d-35 | n-27 | B | RULE tutor (domain) |
| d-36 | n-31 | B | RULE tutor (domain) |
| d-37 | n-33 | B | RULE tutor (domain) |
| d-38 | n-34 | B | RULE tutor (domain); RULE style-tie-break (style) |
| d-39 | n-35 | B | RULE tutor (domain); RULE style-tie-break (style) |
| d-40 | n-38 | B | RULE style-tie-break (style) |
| d-41 | n-40 | C | DECIDED-BY-ZIAD (kind), AGREED (style) |
| d-42 | n-41 | C | DECIDED-BY-ZIAD (kind, domain); RULE style-tie-break (style) |
| d-43 | n-42 | C | DECIDED-BY-ZIAD (kind); RULE style-tie-break (style) |
| d-44 | n-43 | C | RULE style-tie-break (style) |
| d-45 | n-46 | C | RULE style-tie-break (style) |
| d-46 | n-47 | C | DECIDED-BY-ZIAD (kind); RULE style-tie-break (style) |
| d-47 | n-48 | C | AGREED |
| d-48 | n-49 | C | DECIDED-BY-ZIAD (domain) |
| d-49 | n-50 | C | AGREED |
| d-50 | n-54 | C | RULE tutor (domain) |

### Holdout (never for prompt work)
| new id | from | source | label source |
|---|---|---|---|
| h-01 | n-01 | A | DECIDED-BY-ZIAD (risk) |
| h-02 | n-03 | A | AGREED |
| h-03 | n-04 | A | DECIDED-BY-ZIAD (kind); RULE fitness (domain, risk); RULE style-tie-break (style) |
| h-04 | n-05 | A | RULE style-tie-break (style) |
| h-05 | n-08 | A | AGREED |
| h-06 | n-09 | A | AGREED |
| h-07 | n-11 | A | AGREED |
| h-08 | n-12 | A | AGREED |
| h-09 | n-13 | A | RULE fitness (domain, risk) |
| h-10 | n-16 | A | AGREED |
| h-11 | n-17 | A | AGREED |
| h-12 | n-26 | B | AGREED |
| h-13 | n-28 | B | AGREED |
| h-14 | n-29 | B | RULE style-tie-break (style) |
| h-15 | n-30 | B | RULE tutor (kind); RULE style-tie-break (style) |
| h-16 | n-32 | B | RULE tutor (kind); RULE style-tie-break (style) |
| h-17 | n-36 | B | RULE style-tie-break (style) |
| h-18 | n-37 | B | RULE tutor (domain); RULE style-tie-break (style) |
| h-19 | n-39 | B | RULE tutor (overrides the labellers' agreement for consistency); RULE style-tie-break (style) |
| h-20 | n-44 | C | RULE style-tie-break (style) |
| h-21 | n-45 | C | RULE style-tie-break (style) |
| h-22 | n-51 | C | RULE style-tie-break (style) |
| h-23 | n-52 | C | RULE style-tie-break (style) |
| h-24 | n-53 | C | RULE fitness (domain, risk) |
