# Experiments: the log, and how each result is reproduced (AI-25)

**Done-when: "Results reproducible from tracked runs."** Every committed report under `ai/evaluation/<area>/reports/` has an entry in [`ai/evaluation/experiments.yaml`](../../evaluation/experiments.yaml). Every **final** entry reproduces: **18 of 18** (25 Nov 2026).

```bash
cd ai
.venv/Scripts/python -m evaluation.reproduce check   # seconds: registry, reports, inputs, tracked runs (CI)
.venv/Scripts/python -m evaluation.reproduce list    # the live experiments: command, model, prompt, cost
.venv/Scripts/python -m evaluation.reproduce run [--only E3,E7] [--no-model]   # re-run / re-score, compare exactly
```

`run` needs `uv` on PATH (or `UV=<path>`). The model entries (E3, E4) need `SKILLFORGE_MODEL_CACHE` pointing at the local model files. A full run takes about 40 minutes, mostly E3 and E5.

## How reproduction works
- **Offline entries are re-run at the commit that produced them** (`recorded_at`).
  1. `git archive <recorded_at> ai` is extracted with `core.autocrlf` off, so the tree is the same on every OS. It goes into a new folder under `%TEMP%\skillforge-reproduce\`. Nothing is written inside the repository, and only folders this run created are deleted.
  2. The venv comes from that commit's `uv.lock` (`uv sync --locked`), cached by the lock's hash in `ai/.data/reproduce/`, which Git ignores.
  3. The command runs with no API keys, the Hugging Face hub offline, and the **entry's own backend**:
     - `llm_backend: fake` means the fake LLM backend, with no model at all;
     - `llm_backend: local-model` means the real gateway with the pinned local embedding model.
     - There is no global setting. `check` rejects `fake` for an entry whose code embeds text (looked up at `recorded_at`), because fake vectors would give a meaningless report.
- **Live entries are never re-run** (their model calls cost money and aren't deterministic).
  - Their raw predictions are **tracked id-only** (below) and **re-scored offline**, with the same formulas as `analyzer/` and `safety/evaluate.py` and the labels at `recorded_at`.
  - A rescore entry (E8) is scored the same way, against its newer labels.
- **The comparison is exact.** Only the **global ignore list** is dropped: `date, created, run, latency_ms, mean_ms, index_seconds, query_ms, usage, cost_usd, human_review` (dates, run ids, timing, usage, cost, human review).
  - **Never ignored:** a metric, a count or a label.
  - **Extra ignores:** any per-entry addition needs `ignore_extra` with a written reason. None exist.
  - **No tolerances:** no entry has a numeric tolerance.
- **The series rule.** Before re-running, the target report and every **later** report of its series are removed from the extracted reports folder. The series is the name before the date; later means a later date, or the same date with a higher `-N`.
  - This leaves the folder as it was when the report was written. A tool that reads earlier reports (for example the sources review's history) then sees what it saw.
  - Only reports of that series are removed, never inputs or data files.
- **Metrics a tracked run can't support** are listed per entry in `not_recomputable`, with the reason. Any other metric left out of a comparison makes the entry fail.
- **What `check` re-verifies on every PR** (no model, no network):
  - **Offline reports are pinned.** Once `reproduces` is set, the entry also records `report_sha256`: the sha256-lf of the report that run compared (`run` prints it). `check` fails if the report changes later.
  - **Live and rescore entries are re-scored** from their tracked runs, exactly as `run` does. A report edited after its run fails.
  - **A live report's `.md` must be what its `.json` renders to** (`evaluation/reproduce/twins.py`). Today's renderer is tried first, then the one at `recorded_at`. A section added by hand after the generated part must be declared in `md_addendum`, with its reason; only `safety-all-2026-11-17` has one (its 18 Nov "Completion"). Not covered: E8, written by a one-off script, and the offline reports, whose `.md` `run` regenerates but doesn't compare.

## Hashes: the same on Windows and Linux
- Data-file hashes in reports are `sha256` of the content with **CRLF turned into LF** (`evaluation.common.text_sha256`). New report entries say so: `"hash": "sha256-lf"`.
- **Old entries have no `hash` field ("legacy")** and are never rewritten. They were hashed on the raw bytes of whatever checkout ran them, usually a Windows CRLF one. A legacy entry verifies when its hash matches the LF, the CRLF or the raw form, and the check says which.
- Seed releases keep byte hashes: they're `-text` in `ai/.gitattributes`.

## Tracked runs (live results)
- **Where:** `ai/evaluation/<area>/reports/runs/<run>/predictions.jsonl`, written by `evaluation/reproduce/track.py`. It **reads** the local `runs/` folder and never moves, renames or deletes it.
- **What each line holds:** exactly `id`, `expected`, `predicted`, `error`.
  - `error` is a class: `provider_error`, `parse_error`, `timeout`, `budget` or `other`.
  - **Never stored:** request text, rationale or summary, raw error messages.
  - **Checked:** every label against its closed vocabulary, and **every id** in two ways:
    - it's well-formed (`<set>:<id>`, or `normal:<set>:<id>`; lowercase letters, digits and `._/-` only);
    - it's one of the ids in the tracked label files at `recorded_at` (the seed release, `analyzer/requests-*.yaml`, and safety `redteam`, `benign-tricky` and `safety-dev`).
    - So no text can ride in on an id. The converter refuses such a line, and `check` fails on one.
    - **Messages never show the refused text:** not the id, a label value, an unknown field name or an error value. They name the known field only.
  - **No duplicate keys, at any depth.** A plain JSON or YAML parser keeps the last of two equal keys, so text could hide under a first `id`. Every file `reproduce` reads (tracked runs, source runs, reports, the registry, label files) is parsed by `evaluation/reproduce/strict.py`, which refuses duplicates.
  - The SimpleSafetyTests items (`r-31`…`r-36`, used by reference) are id and labels only.
  - **From 25 Nov on,** analyzer lines also keep the predicted and expected `mentioned_targets` (platform labels) and `question_rule_kept` (a boolean computed at run time, never question text).
- **Two hashes per tracked run:**
  - `source_sha256`: the original local file. For E8 it equals the report's `predictions_sha256`.
  - `sha256`: the tracked file, LF-normalised.
- **What `check` verifies:** both hashes, the line count (equal to the report's n), the allowlist, unique ids, and that each id is in the label files at `recorded_at`. Without git history, it checks the id format only.

## Roles
- **final:** a decision rests on it. **The done-when: every final entry reproduces.** `check` fails on a final entry recorded as `reproduces: false`.
- **superseded:** an earlier round, replaced by a later report. It may stay `reproduces: false`, with the reason recorded.
- **invalid:** a run that measured nothing. Like superseded, it never counts toward the done-when. Listed on its own below.
- **pending-merge (a status, not a role):** the report is on another branch. `check` skips the entry while the report is absent and checks it fully once it's present, so merging in any order is safe. When an open branch adds a new report, its PR adds the entry.

## The experiments

### E1, AI-10 extraction: are the chunks clean?
- **Final:** `extraction-2026-11-25`, offline, `llm_backend: fake`. Reproduces exactly.
  - Automatic gates PASS: verdicts, titles, languages, valid passages 100% (gate 100%); facts 100% (95%); chunk size 100% (90%); clean ends 99.6% (95%); leaks 0. They're identical to 25 Oct.
- **Superseded:** `extraction-2026-10-25`. It doesn't reproduce: its code predates `ai/` in Git, and the import commit `da5241c` adds the injection screen to extraction, so the sample differs.
- **Limitation (human review):** PASS 20/20 by Ziad on 25 Oct, on the sample in `extraction-2026-10-25` (kept in the repo). The current code samples different chunks; that sample was not re-reviewed. The automatic gates reproduce exactly.
- **Reproduce:** `run --only E1`.

### E2, AI-09 sources: do the top 10 sources per domain pass review?
- **Final:** `sources-2026-10-26-5`. Human review: all 10 domains pass. Reproduces exactly, with the series rule.
- **Superseded:** `-1`…`-4`, review rounds that passed 3, 7 and 8 domains. They don't reproduce at `da5241c`, which renamed checks and moved the registry to 1.4.0.
- **Limitation:** the human verdicts can't be re-run. Only the automatic part is compared.

### E3, AI-11 retrieval: which embedding model and chunk size?
- **Final:** `recall-2026-11-01`, offline, `llm_backend: local-model`.
  - Decision: **bge-small with 180-word chunks, recall@5 80% (32/40)**, chosen by Ziad over the rule's pick (minilm-l6, 120 words).
- **Superseded:** `recall-2026-10-26`, before canonical URLs. It also reproduces.
- **Limitations:**
  - All 9 combinations are within noise of each other (30–35 of 40).
  - Timing (`index_seconds`, `query_ms`) varies by machine and is ignored.
- **Reproduce:** `run --only E3`, about 8 minutes per report.

### E4, AI-08 gap checker: thresholds on dev, precision on test
- **Final:** `gap-dev-2026-10-28` and `gap-test-2026-10-28`, offline, `llm_backend: local-model` (bge-small). Both reproduce exactly.
- **Results:**
  - `exists` precision **92.3%** (24 of 26, 95% CI 76–98%), recall 70.6%;
  - related precision 79.2%.

### E5, AI-19 injection rules: tuning rounds
- **Final:** `injection-test-2026-10-28-3`. Layer gates 5 of 6. Visible injections caught by the rules: **16 of 28** (gate ≥ 90%, not met). Reproduces exactly.
- **Superseded:** dev ×3 and test `-1`/`-2`, earlier tuning rounds with fewer injections and an older gate list. They don't reproduce at `da5241c`.

### E6, AI-19 full system (c)
- **Final:** `injection-test-2026-11-02`, offline from the saved LLM verdicts (`llm-verdicts-test-2026-11-02.json`, Haiku, 2 Nov). Reproduces exactly, in about 3 minutes.
- **Result:** (c) **54 of 54** stopped: the done-when passes.
- **Limitation:** the LLM-screen verdicts are frozen from 2 Nov. Changed chunks would need a new `--llm --live` run.

### E7, AI-05 request analyzer (live)
- **Final:** `analyzer-dev-2026-11-02` (v1), `-2` (the v2 trial, reverted) and `analyzer-gate-2026-11-02` (v1).
  - Gate: **PASSED**, kind 92%, domain 95%, risk 96%.
  - Sonnet 5.5; cost $0.17, $0.17 and $0.97.
- **Re-scored** from tracked runs; every metric and the gate verdict match.
- **`not_recomputable`:** `mentioned_targets.exact_match` and `needs_clarification.question_rule_kept`, because the 2 Nov raw runs never saved predicted targets or questions.

### E8, AI-05 label review rescore
- **Final:** `analyzer-gate-2026-11-02-rescored-labels-v0.3.0`: the 2 Nov predictions against reviewed labels v0.3.0.
  - Gate **FAILED**, kind 0.88. No model calls.
- **Re-scored:** from the tracked gate run (`source_sha256` = the report's `predictions_sha256`, `5405bf…`) against the labels at its commit. Matches.
- **`not_recomputable`:** the same two metrics as E7, for the same reason.

### E9, AI-06 safety screen (live)
- **Final:** `safety-dev-2026-11-17` (v1), `-2` (the v2 trial, reverted), `-3` (v1), `safety-all-2026-11-17` and `safety-normal-ids-2026-11-17`.
  - Gate **FAILED**: 57 of 60 blocked; misses r-19, r-27, r-51.
  - False blocks: 0 of 60 benign, 0 of 130 normal.
  - Sonnet 5.5; the final run (`safety-all`) cost $1.14.
- **Re-scored:** every metric, the gate verdict and the false-block targets match.

### E10, AI-04 seed benchmark
- **Final:** releases 0.1.0 and 1.0.0. `validate seed` passes: every file has its byte hash.

## Invalid
- **E12, `analyzer-gate-2026-11-24`** (prompt v3; on `AI-05-prompt-v3`, pending merge). Provider failure: 48% of requests got no prediction. The 95% validity rule was added after it. Never used for any decision; replaced by the 28 Nov rerun.

## Pending merge
These are checked once their branch merges:
- **E6 `injection-test-2026-11-18`** (#40): F9, (c) recomputed offline, 54 of 54.
- **E11 `support-calibration-2026-11-21`** (AI-12): the AI-13 support threshold, `local-model`.
- **E12 `analyzer-dev-2026-11-24`** (AI-05-prompt-v3): the v3 dev run.

## Adding an experiment
1. **Run it.** Live runs need `--budget-usd`; for analyzer runs, `--retry-errors` and the 95% validity rule apply. Commit the report (`.md` and `.json`).
2. **Live runs:** write the tracked run with `track.convert(source, target, rescore.known_ids(repo, recorded_at))` from your local `runs/<id>/predictions.jsonl`, and commit it.
3. **Add the entry to `experiments.yaml`:**
   - required: `id`, `experiment`, `task`, `question`, `kind`, `role`, `report`, `recorded_at` (the code commit), `command`;
   - offline entries also need `llm_backend`; live entries also need `tracked_run` (its two hashes and lines), plus `not_recomputable` if anything applies.
4. **Run** `reproduce run --only <id>`, record `reproduces` and `reproduces_note`, then run `reproduce check`.
