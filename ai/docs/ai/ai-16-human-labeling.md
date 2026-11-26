# AI-16 human-labeling instructions

## Status and prerequisite

These are instructions only; no human labels or live answers are included. The immutable seed
release `1.0.0` is available, but answer-level labels cannot be created until real benchmark
answers exist. Generate answers only after the compiled skill instructions are ready and the
live-call cost is approved. Fake-run output is not labeling material.

Do not edit the immutable benchmark release. Keep answer labels in a separate JSONL file for a
later minor dataset release.

## Label each answer

Use the exact prompt and answer recorded in the harness `predictions.jsonl`. Label each answer
independently against every rubric item in the matching seed release:

- Record `true` only when the answer clearly satisfies the item's wording; otherwise record
  `false`. Do not infer missing content or reward unsupported claims.
- Score every rubric item for every answer. A `critical` item is scored by its rubric wording too;
  its critical status does not change the pass/fail definition.
- Judge answers separately. Do not select a preferred answer or compare the with-skill answer
  against the without-skill answer.
- When practical, hide the condition while scoring. Add the exact `condition` from the saved
  prediction only after scoring.
- Preserve the prompt, answer, condition, rubric IDs and answer text exactly. Use a stable reviewer
  identifier.

The required JSONL record shape is shown below. The angle-bracketed values are placeholders, not
labels; replace them only with exact release and answer data.

```json
{
  "prompt_id": "<skill>/<prompt-id>",
  "prompt": "<exact prompt from release 1.0.0>",
  "condition": "with_skill",
  "answer": "<exact answer from predictions.jsonl>",
  "rubric_scores": {
    "<skill>/<rubric-id-1>": true,
    "<skill>/<rubric-id-2>": false
  },
  "reviewer": "<reviewer-id>"
}
```

Write one JSON object per line. The allowed `condition` values are `with_skill` and
`without_skill`; rubric keys must match the release exactly. Do not copy these placeholders into a
calibration file.

## Independent review and model restrictions

The primary reviewer prepares the labels used for judge calibration. A second human reviewer
independently labels about 20% of the same answers to measure human-human agreement. Keep that
reviewer's records separate from the primary calibration file so the same answer is not counted
twice in judge calibration. Compare the reviewers' decisions per rubric item.

Do not use an LLM to draft, score, validate, revise, or fill in any label. Labels must represent
the reviewers' own decisions. Do not ask the judge to create the reference labels.

The harness's 80% acceptance gate is raw agreement per rubric decision, not per answer. Cohen's
kappa is reported for information only; it is not part of the gate. See
[the evaluation-harness documentation](evaluation-harness.md) for the calibration procedure.
