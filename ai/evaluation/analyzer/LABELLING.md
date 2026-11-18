# Labelling rules for skill requests (AI-05)

A labelled request is what a user types to **create** a skill, plus the correct answers. Every label must follow these rules, so two people labelling the same request get the same result. When a request is unclear to you as a labeller, add a `notes:` line. Don't guess silently.

## kind
- **role**: the skill makes the agent act as a professional who handles many kinds of tasks in a field. For example: "a recruiter", "act like our product manager".
- **task**: one repeatable job with a clear input and output. For example: "review NDAs", "write press releases", "turn notes into minutes".
- **workflow**: a process with several stages, done in order, often over time or with several people. For example: "run our postmortems", "onboard new hires step by step", "our month-end close".

If a request asks for a person who does one job only ("someone who writes our release notes"), it is a **task**.

## domain: `<area>/<sub-area>`
- **The area is the expertise the skill applies, not the user's industry.**
  - Budgeting for a bakery is `finance`, not food.
  - Polite emails to a hospital's patients about appointment times are `customer-support`, not `medical`.
  - A revenue dashboard is `data`; building dashboards is the skill.
- The area must be from the closed list in `core.spec.DOMAIN_AREAS`.
- `general` is for everyday, personal tasks that need no professional field: trips, events, home and personal productivity.
- The sub-area is a short kebab-case phrase, for example `ux`, `lesson-planning` or `tax`. It is not scored. Only the area is.

## risk
- **high**: exactly when the area is `legal`, `medical` or `finance`. The skill applies expertise where wrong answers can cause legal, health or money harm. Writing *about* tax rules for readers is `finance/tax`, so it is high.
- **medium**: any other area, when the skill's core work handles personal data about specific people, makes or supports decisions about people (hiring, grading, performance), or works with minors.
- **low**: everything else.

## style
- **clear**: one or two sentences that say what the skill does.
- **vague**: a few words that do not say what the skill should do or produce.
- **detailed**: several sentences with context, tasks and constraints.

## needs_clarification
This is `true` exactly when the style is `vague`. The analyzer should then ask 3 to 5 questions.

## mentioned_targets
This lists only the platforms **named in the text**:

| The text names | Label |
|---|---|
| Claude, Claude Code | `claude` |
| Codex | `codex` |
| ChatGPT, a custom GPT | `chatgpt` |
| "any agent", AGENTS.md, a plain Markdown instructions file | `generic` |

If no platform is named, use `[]`. Platforms chosen in the website's UI are not part of the text, so they are not labelled.

## Data hygiene
- **Synthetic only:** no real people, companies or personal data.
- **No duplicates:** no text may appear twice across the seed benchmark, test, dev and Arabic sets. The tests check this.
- **A changed label is a new version:** after changing any label, bump the file's `version`. Bump the MINOR number for added, changed or removed requests.
