# FE-08 — Clarifying questions

**Status:** UI preview implemented; AI-05 question contract and BE-05 answer persistence pending  
**Route:** `/skills/requests/[requestId]/questions`

## Frontend work completed

- Added a responsive, Arabic-first one-question-at-a-time flow.
- Supports single choice, multiple choice, and free-text question presentations in the UI.
- Keeps entered answers while moving back and forward, permits skipping, and shows local required-answer feedback.
- Shows the request ID and a clear preview state after the final step.

## Contract boundary

The question examples and their discriminated UI types in `questions-wizard.tsx` are local preview fixtures. They are not an AI-05 response schema. The UI can present the three sample input styles, but it must be adapted to the actual AI question schema once agreed with the AI team. No assumptions are made about question IDs, answer payloads, validation rules, or whether skipping is allowed for every question.

BE-05 must define how answers and skipped questions are submitted and resumed. Until that operation is available, the final action only shows a local preview notice and does not send or persist data.

FE-08 is complete when actual AI-05 question responses render through the agreed schema and answers/skips persist and resume through BE-05.
