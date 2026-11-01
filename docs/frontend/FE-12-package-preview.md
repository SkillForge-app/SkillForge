# FE-12 — Package preview

**Status:** UI preview implemented; BE-09 compiler output and BE-10 package/download contract pending  
**Route:** `/skills/[skillId]/preview`

## Frontend work completed

- Added Claude Code and Codex platform selection.
- Added a package file tree and file selection for `SKILL.md`, references, and templates.
- Added formatted and raw Markdown views for the selected file.
- Kept download and install actions disabled until real package outputs and the FE-13 route are available.
- Labeled all displayed package content as local UI preview data.

## Contract boundary

The tree and file contents are fixtures, not compiler output. BE-09 must define compile operations and returned files; BE-10 must define package/download availability and URL or stream behavior. Platform-specific file paths and contents must come from the compiler. FE-12's archive-parity acceptance check remains pending until the UI previews the same returned file bytes that the ZIP contains.

FE-12 is complete when the selected platform's actual generated files render in both views and the preview matches the downloaded archive exactly.
