# SkillSpec v0.2

Owner: AI department (AI-01, contract **B1**). Draft: Fri 30 Oct 2026. **Frozen: Thu 5 Nov 2026.**

A SkillSpec is the platform-neutral description of one skill. The Skill Architect writes a SkillSpec, never Markdown. The compilers (BE-09) turn a valid SkillSpec into a Claude, Codex, ChatGPT or generic package. The review form (FE-11) edits it.

| What | Where |
|------|-------|
| JSON Schema, the published contract for BE and FE | `ai/core/spec/schema.json` (draft 2020-12, `$id` `urn:skillforge:skillspec:0.2`) |
| Pydantic models | `ai/core/spec/models.py` |
| Validator: schema errors plus cross-field rules | `ai/core/spec/validator.py` |
| Example specs | `ai/examples/skillspec/`: `ai-engineer` (technical role), `marketing-strategist` (role), `review-nda` (legal task, high risk) |

## Two layers of rules

1. **Per-field rules live in `schema.json`.** They cover types, required fields, closed vocabularies, id and path patterns, lengths, and no duplicate list items. Unknown fields are rejected at every level (`additionalProperties: false`). FE can check all of these in the browser.
2. **Cross-field rules can't be expressed in JSON Schema.** Examples: a referenced id must exist, or a high-risk skill needs certain guardrails. They run in `validate_spec`, which the API calls on every save. FE shows the issues the API returns.

A test makes Pydantic and `schema.json` reject the same structural mistakes, so FE and BE never disagree on layer 1.

## Using it

```python
from core.spec import validate_spec, load_spec

result = validate_spec(payload, existing_names=registry_names)   # dict, or JSON text
if not result.ok:
    return 422, [issue.__dict__ for issue in result.errors]        # path, code, message, severity
spec = result.spec                                                # a frozen SkillSpec

spec = load_spec("examples/skillspec/review-nda.yaml")            # raises SpecValidationError
```

```bash
cd ai
.venv/Scripts/python -m core.spec validate examples/skillspec/*.yaml
.venv/Scripts/python -m core.spec export-schema            # after changing models.py
.venv/Scripts/python -m core.spec export-schema --check    # CI: is schema.json current?
```

## Issues

Every problem comes back as an **issue**:

| Field | Meaning |
|-------|---------|
| `path` | A JSON Pointer to the field, e.g. `/procedures/0/produces/1`. Use it to put the message next to the right input |
| `code` | A stable, machine-readable code (table below). Do not parse the message |
| `message` | Short and safe to show. It names the location, never the field's content |
| `severity` | `error` blocks saving and compiling. `warning` is shown but allowed |

**Schema errors** have codes starting with `schema.`. The commonest are:

| Code | Meaning |
|------|---------|
| `schema.unknown_field` | An unknown field. The message suggests the closest real name: `unknown field "titel"; did you mean "title"?` |
| `schema.missing` | A required field is missing |
| `schema.literal_error` | A value is not in a closed vocabulary |
| `schema.string_pattern_mismatch` | Bad id, name, version, domain or file path |
| `schema.string_type` | Text was expected. For YAML numbers, the message adds a hint: quote `"1.0"` |
| `schema.too_short` | An empty list where at least one item is required |
| `schema.duplicate_item` | The same value appears twice in a list |

If the schema check fails, the cross-field rules don't run.

**Cross-field rules** (all errors unless marked):

| Code | Rule |
|------|------|
| `duplicate_id` | Ids are unique within procedures, outputs, guardrails, references and sources |
| `unknown_source` | Every source id a reference cites exists in `/sources` |
| `unknown_output` / `unknown_reference` | Every output or reference a procedure points to exists |
| `duplicate_file` | Two outputs or references use the same file |
| `role_needs_guardrail` | A `role` skill has at least one guardrail. Every skill needs at least one procedure; the schema enforces that |
| `high_risk_needs_disclaimer` / `high_risk_needs_human_review` | Domain area `legal`, `medical` or `finance` needs a `must` guardrail with category `disclaimer` and one with category `human_review` |
| `tool_listed_twice` | A capability is both required and optional |
| `reserved_name` | Target `claude`: the name can't contain "claude" or "anthropic" |
| `xml_in_text` | No `<...>` tags in the summary or triggers; platforms reject them in descriptions |
| `description_too_long` | The summary plus triggers (see `draft_description()`) must fit the smallest description limit among the targets |
| `name_taken` | The name is already in the registry (`existing_names`) |
| `unused_source` *(warning)* | A source no reference cites |
| `unused_output` *(warning)* | An output no procedure produces |

## Fields

The full definition is `schema.json`; every field there has a `description` that FE can use as help text. In short:

| Section | Fields |
|---------|--------|
| `spec_version` | Always `"0.2"`, quoted |
| `skill` | `name` (kebab-case, 2–64 characters, becomes the folder name), `version` (`"1.0"`), `title`, `kind` (`role` / `task` / `workflow`), `domain` (`<area>/<sub-area>`), `summary` (up to 300 characters) |
| `triggers` | `use_when` (1–10 items), `avoid_when` |
| `expertise` | `principles` (1–20 items) |
| `procedures[]` (1–30 items) | `id`, `title`, `steps` (1–30 items), `produces` (output ids), `uses` (reference ids) |
| `outputs[]` | `id`, `template` (`templates/<name>.md`), `title`, `sections` (template headings) |
| `guardrails[]` | `id`, `rule`, `severity` (`must` / `should`), `category` (`general`, `accuracy`, `safety`, `privacy`, `scope`, `disclaimer`, `human_review`) |
| `tools` | `required`, `optional`: abstract capabilities only (`filesystem_read`, `filesystem_write`, `terminal`, `code_execution`, `web_search`, `web_fetch`, `browser`) |
| `knowledge.references[]` | `id`, `file` (`references/<name>.md`), `title`, `sources` (at least one source id) |
| `sources[]` | `id`, `url` (http or https), `retrieved` (YYYY-MM-DD), `title`, `licence` (optional) |
| `evaluation` | `test_prompts` (at least one), `rubric` (at least one), `should_not_trigger` (for trigger-accuracy tests) |
| `targets` | At least one of `claude`, `codex`, `chatgpt`, `generic`; `chatgpt` and `generic` produce the non-blocking `target_not_available_in_v1` warning |

Domain areas (a closed list): `technology`, `data`, `design`, `product`, `marketing`, `sales`, `customer-support`, `operations`, `hr`, `education`, `writing`, `research`, `finance`, `legal`, `medical`, `general`. Of these, `legal`, `medical` and `finance` are high risk.

Fields added to the §4 example (`produces`, `uses`, output `title` and `sections`, guardrail `category`, reference and source `title`, `should_not_trigger`) are all optional. The §4 example itself still passes the schema. The cross-field rules catch its one gap: its reference cites `src-2`, which is never defined (`tests/spec/fixtures/spec-section-4-example.yaml`).

## Shared vocabularies

The closed vocabularies are public, and part of contract B1. Other modules import them instead of copying them, for example Track A's `AnalyzedRequest` (AI-05):

```python
from core.spec import DomainArea, Kind, RiskLevel, Capability, Target, HIGH_RISK_AREAS

class AnalyzedRequest(BaseModel):
    kind: Kind                    # Literal types: use them as Pydantic field types
    domain_area: DomainArea
    risk: RiskLevel
```

| Type | Tuple of values | Values |
|------|-----------------|--------|
| `Kind` | `KINDS` | role, task, workflow |
| `DomainArea` | `DOMAIN_AREAS` | the 16 areas listed above |
| (none) | `HIGH_RISK_AREAS` (frozenset) | legal, medical, finance |
| `RiskLevel` | `RISK_LEVELS` | low, medium, high: the risk of a skill request (AI-05) or benchmark skill (AI-04). `high` is only for the high-risk areas |
| `Capability` | `CAPABILITIES` | the 7 tool capabilities |
| `Target` | `TARGETS` | claude, codex, chatgpt, generic |
| `Severity`, `GuardrailCategory` | `SEVERITIES`, `GUARDRAIL_CATEGORIES` | as in the field table |

The tuples are derived from the `Literal` types, so there is one place to change. A test checks that they match the enums in `schema.json`.

## Platform limits

| Target | Name | Description | Status |
|--------|------|-------------|--------|
| claude | 64 | 1024 | Checked against Anthropic's Agent Skills docs on 2026-10-23. Lowercase, digits and hyphens only; no "claude" or "anthropic"; no XML tags |
| codex | 64 | 1024 | Codex docs give no limit. These are the Agent Skills standard values; **to confirm in BE-09** |
| chatgpt, generic | 64 | 1024 | Placeholder until those adapters are designed (BE-23) |

The limits are in `PLATFORM_LIMITS` in `validator.py`. Changing one is a contract change.

## Versioning and the freeze

- **Until 5 Nov:** the draft can change. Please review it by 30 Oct. In particular, BE (compiler inputs, issue format, `existing_names`) and FE (form generation from `schema.json`, issue `path` handling).
- **From 5 Nov:** `schema.json` v0.2 is frozen. Any change needs a PR approved by both AI tracks and by the BE and FE reviewers.
  - An added optional field becomes `0.3`.
  - Any breaking change, such as renaming, removing or tightening a field, bumps `spec_version`, and the validator gets a migration note.
- `schema.json` is generated, never edited by hand. CI (`tests/spec/test_schema.py`) fails if it differs from the models.
