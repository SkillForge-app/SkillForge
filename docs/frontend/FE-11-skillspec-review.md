# FE-11 — SkillSpec review and edit

**Status:** Review route and generic schema-driven form component prepared; AI-01 schema and BE-09 operations pending  
**Route:** `/skills/[skillId]/review`

## Frontend work completed

- Added the review route with a clear unavailable state while the SkillSpec schema is missing.
- Added a reusable form renderer driven by JSON Schema object properties, required fields, descriptions, primitive types, enums, nested objects, and arrays.
- Added support for displaying field-level errors and warnings supplied by a validator.
- Kept save and compile controls disabled until the SkillSpec and BE-09 contracts are available.

## Contract boundary

No `schema.json` is present in the workspace or the current OpenAPI document, so this screen does not define local SkillSpec fields or sections. The generic renderer is ready to consume an AI-01 JSON Schema; its current supported subset may need extension after reviewing that real schema. BE-09 must define read/update/save operations, compile behavior, schema versioning, and validation error paths/codes/messages/severity before the form can be connected.

FE-11 is complete when the actual AI-01 schema drives the editor, edits persist through BE-09, and validation errors render beside the matching fields.
