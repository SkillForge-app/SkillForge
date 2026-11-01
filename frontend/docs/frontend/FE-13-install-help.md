# FE-13 — Install help

**Status:** Install screen and copy interaction prepared; compiler guidance and package download contract pending
**Route:** `/skills/[skillId]/install`

## Frontend work completed

- Added platform selection for Claude Code and Codex.
- Added a guidance-driven destination path, ordered setup steps, optional command, and package download action.
- Added keyboard-accessible copy-to-clipboard behavior with copied and failure feedback.
- Connected FE-12's install-help action to the new route.
- Shows a clear unavailable state while platform install guidance is not supplied.

## Contract boundary

The route does not infer platform-specific paths or commands. Its `InstallGuidance` view model must be populated from BE-09 compiler/install guidance, and the download URL must come from the BE-10 package response. The route currently receives no guidance, so copy and download actions cannot run.

FE-13 is complete when both platforms display the compiler-provided path and steps, copy reports the real clipboard result, and download uses a valid package response.
