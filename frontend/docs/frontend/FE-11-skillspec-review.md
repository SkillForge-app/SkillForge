# FE-11 — SkillSpec review and edit

**Status:** AI-01 SkillSpec v0.2 editor connected; BE-09 read/save/validation/compile operations pending
**Route:** `/skills/[skillId]/review`

## Frontend work completed

- Imported `apps/web/lib/skillspec/schema.json` from the AI-01-clean branch at commit `565ae041`.
- Generated review fields from SkillSpec v0.2 `$defs`, `$ref`s, nested objects, arrays, enums, constraints, and nullable fields.
- Added add/remove controls for repeated objects and JSON Pointer field-level errors/warnings with validator codes.
- Preserved edits in local page state and kept save/compile controls disabled until BE-09 operations are available.

## Contract boundary

The imported schema is the AI-01-clean draft for SkillSpec v0.2; the AI team documentation schedules the contract freeze for 5 November 2026. The Backend OpenAPI on the `Backend` branch currently exposes Projects and Repositories only, so it has no SkillSpec operations yet. BE-09 must define read/update/save operations, compile behavior, schema versioning, and validation error paths/codes/messages/severity before the form can be connected.

FE-11 is complete when the frozen AI-01 schema drives the editor, edits persist through BE-09, and live validation errors and warnings render beside the matching fields.
