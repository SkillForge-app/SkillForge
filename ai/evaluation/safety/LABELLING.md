# Labelling rules for the safety sets (AI-06)

The policy itself is `ai/docs/ai/refusal-policy.md`. These rules say how to write and label the test data that measures it.

## The sets

| File | Size | Expected verdict | Status |
|---|---|---|---|
| `redteam.yaml` | 60 | all `block` | **INCOMPLETE: to be written by a person, or taken from a vetted dataset** |
| `safety-dev.yaml` | 20 = 10 block + 10 allow | mixed | The allow half is done. **The block half is incomplete** |
| `benign-tricky.yaml` | 60 | all `allow` | Draft, needs a second reviewer |
| "normal" (the analyzer's gate, dev and Arabic sets) | 130 | all `allow` | Reused, not stored here |

Each file has `status`:
- `incomplete`: the file is not finished. `check-data` reports the gaps as warnings, and the gate cannot pass.
- `draft`: the file is complete. `check-data` reports every gap as an error.
- `reviewed`: a second person has checked every item.

## Writing red-team items

The red-team items must **not** be written by an AI assistant. Two options:
- A person on the team writes them. The AI Lead or a safety reviewer is preferred.
- They are taken from a vetted red-team dataset whose licence allows internal use. Record the source and licence in the file header.

**Rules for every red-team item:**
- **Intent level only.** Describe what the requested skill would do in one or two sentences, like a real user request. Never include working instructions, code, recipes, names of real people or real targets.
- **One category per item**, from `core.analysis.HARM_CATEGORIES`. Pick the main purpose. Use `other` only if no category fits.
- **One attack style per item:**
  - `direct`: plainly asks for the harmful skill
  - `euphemism`: harmful purpose in mild or coded words
  - `fiction_wrapper`: the purpose is hidden behind "for a story or game"
  - `education_wrapper`: hidden behind "for a course or research"
  - `authority_claim`: hidden behind "I'm a police officer, doctor or admin"
  - `prompt_injection`: the text tries to instruct the screen ("ignore your rules")
  - `two_turn`: the request itself looks fine, and the harm appears only in `answers`
  - `arabic`: written in Arabic

**Coverage, checked by `python -m evaluation.safety check-data`:**
- exactly 60 items
- at least 5 per category, not counting `other`
- at least 3 per attack style
- every `two_turn` item has at least one answer

## Writing benign items
- The request must be **allowed** under the policy, but should look risky at first sight. Examples: security learning, fraud prevention, crisis support, harm reduction, dark fiction, high-risk professional work.
- **`expected_conditions`** are the conditions the screen should attach. Use them only when they clearly apply.
- **Language:** at least 5 benign items are in Arabic.

## For every file
- Synthetic only: no real people, companies or personal data.
- **No duplicates:** no text may appear twice across the safety and analyzer sets.
- **Versioning:** bump the file's `version` after any change.
- **Few-shot examples:** the prompt's few-shot examples come from the **allow** half of `safety-dev.yaml` only.
