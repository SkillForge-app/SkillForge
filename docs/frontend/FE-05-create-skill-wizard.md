# FE-05 — Create-skill wizard v0

**Status:** UI implemented; API submission remains pending BE-05  
**Route:** `/skills/new`

## Frontend work completed

- The user can describe a role or repeatable task, select a skill kind, and choose Claude Code,
  Codex, or both target platforms.
- Required fields show inline validation and preserve the user's input while editing.
- The route is responsive and uses FE-03 theme tokens.
- The home shell's create-skill actions link to this route.

## API boundary

The supplied OpenAPI contract currently covers Projects and Repositories. It does not yet include
the BE-05 skill-request operation, so this page does not send a guessed request or define a
hand-written wire payload. The form currently reports that its values are ready. When BE-05 adds
the request operation and schema to OpenAPI, use the generated client to submit it and navigate
according to its response.

FE-05 is complete when the generated client submits the user's request to the API on staging, in
addition to this UI work.
