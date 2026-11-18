# Gap Checker labels (AI-08)

The labelled set measures whether the Gap Checker finds an existing skill that already does what a request asks for.
- **Files:**
  - `pairs-dev.yaml` is for tuning only.
  - `pairs-test.yaml` is run once, after tuning, for the reported numbers.
- **The skills** are the cards in `tests/fixtures/gap/skills.yaml`:
  - the 10 seed skills
  - hand-written distractors, many of them deliberate near-misses of a seed skill

## A labelled request
```yaml
- id: gd-01
  text: Build a skill that reviews NDAs before I sign them and flags risky clauses.
  style: clear            # clear | vague | detailed
  language: en            # en | ar
  analysis: {kind: task, domain: legal/contracts, skill_name: review-nda,
             summary: A skill that reviews NDAs before signing and flags risky clauses.,
             expected_outputs: [clause risk list]}
  match: [registry:review-nda]
  near_miss: [registry:supplier-contract-reviewer, corpus:draft-nda-template]
```
- **`analysis`:** the fields the Request Analyzer would produce. The gap checker reads `summary`, `kind`, `domain` and `expected_outputs`; `risk` follows from the domain area.
  - **The summary** is written in English, as the analyzer writes it, even for Arabic requests.
  - **For a vague request,** the summary holds only what the text says. Nothing is added.
- **`match` and `near_miss`** are lists of card ids. **Every pair not listed is `no_match`.** That is part of the review: check that no unlisted card should have been listed.

## The three labels for a (request, skill) pair
| Label | When | What FE-09 would offer |
|---|---|---|
| `match` | The skill does what the request asks, so the user could use it as it is. A general skill covers a specific use inside its scope (a data analyst covers "analyse our sales CSV") | Use the existing skill |
| `near_miss` | The same family of work, worth starting from, but different in a key way (see below) | Customize it |
| `no_match` | Unrelated, or only the same broad area (legal, medical, hr, ...) | Generate a new skill |

**A key way** means one of these:
- **Artefact:** drafting an NDA versus reviewing one.
- **Direction:** a recruiter versus a candidate's interview coach.
- **Jurisdiction:** US versus UK law.
- **Scope:** NDAs versus all contracts; lab results versus imaging reports; a small business versus a corporate group.
- **Stage:** a postmortem after an outage versus coordination during one.
- **Method transplanted to another field:** a blameless review of a marketing campaign.

**Same area is not enough.** A will, a visa checklist and an NDA review are all `legal` and all `no_match` to each other.

## Hard cases, decided
- **Vague requests** ("something that reads contracts for me"):
  - **`match`** only when every reasonable reading is the skill's job, e.g. "help us learn from outages" is a postmortem.
  - **`near_miss`** when the text could mean several skills.
  - The gap check is meant to run after clarification; vague items show how it behaves before.
- **A request for exactly what a distractor does** is `match` to that distractor, even when a seed skill is near: "write an NDA template" matches `draft-nda-template` and is `near_miss` to `review-nda`.
- **Several matches:** a request can match more than one skill when both would do the job as they are. That is rare here.

## Metrics
1. **Pair level (the done-when number):**
   - A pair is predicted `exists` when its score is at or above the `exists` threshold.
   - We report its precision and recall against `match`.
   - `related` (`match` or `near_miss`) is reported the same way against the `similar` threshold.
2. **Request level:**
   - The verdict from the top-scored skill (`exists` / `similar` / `new`) is compared with the request's best label (`match` > `near_miss` > `no_match`).
   - A correct `exists` also needs the top skill to be one of the request's `match` skills.

## Review
Each file has `review: {status, reviewer, date}`. A file starts as `draft`. The test numbers count only after a person sets it to `reviewed`, having:
- checked every label
- checked that each `analysis` reads like the analyzer's output
- added or removed `near_miss` entries where needed

The tuning step works on a draft dev file; the report refuses a draft test file.
