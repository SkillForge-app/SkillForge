# FE-02 — Low-fidelity wireframes

**Status:** Draft for Backend and AI review  
**Fidelity:** Structure and information hierarchy only. FE-03 will set final components, responsive breakpoints, colors, type, and light/dark behavior.  
**Direction:** Keep the quiet, low-chrome SkillForge shell already started; make the actual job—creating and managing agent skills—the center of each screen. Arabic-first copy and right-to-left layout follow the current interface.

## Shared application shell

Desktop places the navigation rail on the right in RTL. On narrow screens it becomes a menu drawer; the page content stays the primary scroll region.

```text
┌────────────────────┬──────────────────────────────────────────┐
│ SKILLFORGE         │ Breadcrumb / page title       Account    │
│                    ├──────────────────────────────────────────┤
│ + Create a skill   │                                          │
│   Skill library    │             Current page                  │
│   My skills        │                                          │
│                    │                                          │
│ Recent skills      │                                          │
│   [skill title]    │                                          │
│   [skill title]    │                                          │
│                    │                                          │
│ Settings / profile │                                          │
└────────────────────┴──────────────────────────────────────────┘
```

The drawing is arranged for readability; in the Arabic UI, the navigation rail is on the right. “Projects”, a model picker, and an upgrade CTA are not part of the V1 page list in the supplied specification.

## V1 screens

### 1. Home — `/`

```text
┌───────────────────────────────────────────────────────────────┐
│ Welcome / what skill do you need?                              │
│ [Describe a role or repeatable task                       ]    │
│ Target platforms   [ Claude Code ] [ Codex ]                  │
│                         [ Create a skill ]                    │
├───────────────────────────────────────────────────────────────┤
│ Recent skills                                                  │
│ [Skill title] [status] [updated]     [Skill title] [status]    │
│ [Browse the skill library]                                     │
└───────────────────────────────────────────────────────────────┘
```

Primary action: start a skill request. Empty state explains the create and browse paths; no placeholder “recent chat” list.

### 2. Sign in / create account — `/auth/sign-in`, `/auth/sign-up`

```text
┌─────────────────────────────┬─────────────────────────────────┐
│ SkillForge mark             │ Sign in / Create account        │
│ Short product explanation   │ [ Continue with GitHub ]        │
│                             │ [ Continue with Google ]        │
│                             │ [ Email                     ]    │
│                             │ [ Password                  ]    │
│                             │ [ Continue ]                     │
│                             │ Switch sign-in / sign-up         │
└─────────────────────────────┴─────────────────────────────────┘
```

The email/password and OAuth flows are owned by BE-04. Password recovery and verification screens need the auth contract before being added.

### 3. Create a skill — `/skills/new`

```text
┌───────────────────────────────────────────────────────────────┐
│ Create a skill                                      Step 1     │
│ What should this skill help an agent do?                      │
│ [ Describe the role or task in your own words             ]   │
│ Skill kind     ( Role ) ( Task ) ( Workflow )                 │
│ Build for      [ Claude Code ] [ Codex ]                      │
│                                      [ Continue ]              │
└───────────────────────────────────────────────────────────────┘
```

Primary action: submit the description and selected platforms. Client-side validation stays next to the field; exact required fields follow the request schema.

### 4. Clarifying questions — `/skills/requests/[requestId]/questions`

```text
┌───────────────────────────────────────────────────────────────┐
│ A few questions will help shape this skill       Step 2        │
│ Question 1 of 3–5                                              │
│ [ Question text from Request Analyzer                      ]  │
│ ( ) Option A   ( ) Option B   ( ) Other: [                ]   │
│ [Back]                      [Save and continue] [Skip]        │
└───────────────────────────────────────────────────────────────┘
```

Question type is driven by the AI response, not a hard-coded radio layout. Answers remain recoverable after refresh if supported by BE-05.

### 5. Gap-check result — `/skills/requests/[requestId]/match`

```text
┌───────────────────────────────────────────────────────────────┐
│ We found a skill that may fit                                 │
│ [Existing skill: title / summary / platform / version]        │
│ [Use this skill] [Customize it]                               │
│                                                               │
│ Or continue with a new skill                                  │
│ [Generate a new skill]                                        │
└───────────────────────────────────────────────────────────────┘
```

Show a similarity score only if AI/Backend define its meaning and threshold. Also define no-match, multiple-match, and lookup-error states.

### 6. Generation progress — `/skills/jobs/[jobId]`

```text
┌───────────────────────────────────────────────────────────────┐
│ Creating: [skill title]                       [current state]  │
│ ✓ Understand request     ✓ Check existing skills              │
│ ● Gather knowledge       ○ Design SkillSpec                   │
│ ○ Validate               ○ Prepare packages                   │
│ Sources being reviewed                                        │
│ [Source title] [domain] [open citation]                       │
│ [Source title] [domain] [open citation]                       │
│ On error: explanation + [Retry] or [Return to request]        │
└───────────────────────────────────────────────────────────────┘
```

Stages and source records come from AI/BE events. Refresh restores the same job. Avoid invented percentage-complete values if the service only reports named stages.

### 7. SkillSpec review and edit — `/skills/[skillId]/review`

```text
┌──────────────────────────┬────────────────────────────────────┐
│ Skill outline            │ Review and edit                    │
│ Identity                 │ Name [                         ]   │
│ Triggers                 │ Summary / description [         ]   │
│ Expertise                │ Use when [                     ]   │
│ Procedures               │ Avoid when [                   ]   │
│ Outputs                  │ Procedures / outputs / tools       │
│ Guardrails               │ References / sources               │
│ Sources                  │ Inline schema errors               │
│                          │ [Save draft] [Compile packages]     │
└──────────────────────────┴────────────────────────────────────┘
```

Sections are generated from AI-01 `schema.json`; no duplicate frontend-only SkillSpec schema. Preserve unsaved edits and expose API validation errors beside the related field.

### 8. Package preview — `/skills/[skillId]/preview`

```text
┌───────────────────────────────────────────────────────────────┐
│ Preview package       [Claude Code] [Codex]                   │
├──────────────────┬────────────────────────────────────────────┤
│ File tree         │ File name                                  │
│ ▾ skill-folder    │ [Rendered] [Raw Markdown]                 │
│   SKILL.md        │                                            │
│   references/     │ Preview of selected generated file         │
│   templates/      │                                            │
│                  │ [Install help]              [Download ZIP]  │
└──────────────────┴────────────────────────────────────────────┘
```

The selected platform and previewed file are visible. The preview must match the downloaded archive exactly (FE-12 acceptance criterion).

### 9. Install help — `/skills/[skillId]/install`

```text
┌───────────────────────────────────────────────────────────────┐
│ Install this skill         [Claude Code] [Codex]              │
│ Destination folder                                             │
│ [ .claude/skills/<skill-name>/                    ] [Copy]   │
│ Steps: 1. Download ZIP  2. Unpack  3. Copy to project         │
│ [Open package preview]                            [Download]  │
└───────────────────────────────────────────────────────────────┘
```

Platform path and commands must come from the compiler/install guidance, not be inferred by the UI. Provide a visible copied confirmation and keyboard-accessible copy action.

### 10. Result and download — `/skills/jobs/[jobId]/result`

```text
┌───────────────────────────────────────────────────────────────┐
│ Skill package is ready                                        │
│ [Skill title]   [Claude Code package] [Codex package]         │
│ [Download ZIP]       [Preview files]       [Install help]     │
│ Version [from package]   Sources [open list]                  │
└───────────────────────────────────────────────────────────────┘
```

The same route has pending, failed, and completed states. Downloads are disabled until the package builder returns a usable package/link; errors offer recovery.

### 11. Skill library — `/library`

```text
┌───────────────────────────────────────────────────────────────┐
│ Skill library                 [Search skills              ]   │
│ Categories [All v]  Platforms [All v]  Sort [Relevant v]     │
├───────────────────────────────────────────────────────────────┤
│ [Skill title] [kind] [platforms] [summary] [Open]             │
│ [Skill title] [kind] [platforms] [summary] [Open]             │
│ [Skill title] [kind] [platforms] [summary] [Open]             │
│ Empty / loading / error / pagination                          │
└───────────────────────────────────────────────────────────────┘
```

Search, categories, filters, sorting, and pagination reflect BE-11 capabilities; keep unsupported filters out of the final UI.

### 12. Skill detail — `/library/[skillId]`

```text
┌───────────────────────────────────────────────────────────────┐
│ [Skill title]  [kind] [platforms] [current version]           │
│ Summary                                                        │
│ [Use skill] [Customize] [Download]                            │
├───────────────────────────────────────────────────────────────┤
│ [Overview] [Versions] [Sources] [Files] [Ratings]             │
│ Selected tab content: version history / citations / file list  │
│ Original source links and available ratings                   │
└───────────────────────────────────────────────────────────────┘
```

Each citation links to its original source. Only display tabs and actions for data the registry returns.

### 13. My skills — `/my/skills`

```text
┌───────────────────────────────────────────────────────────────┐
│ My skills                               [Create a skill]      │
│ [Search] [Status v] [Platform v]                              │
├───────────────────────────────────────────────────────────────┤
│ [Skill title] [Draft/Ready] [version] [Open] [Rate]           │
│ [Skill title] [Draft/Ready] [version] [Open] [Rate]           │
│ Empty state: explain create or library paths                  │
└───────────────────────────────────────────────────────────────┘
```

Private skills are scoped to the authenticated user. The list endpoint and status vocabulary must be agreed with Backend.

### 14. Rating and feedback — inline from My skills / detail

```text
┌───────────────────────────────────────────────────────────────┐
│ Share feedback about [skill title]                            │
│ Rating control [scale defined by API]                         │
│ What worked / what should improve? [                       ]  │
│ [Cancel]                                        [Submit]       │
└───────────────────────────────────────────────────────────────┘
```

Rating scale and required fields remain open until BE-12 publishes the contract. Show saved/error state without losing the comment.

## V2/V3 screens in the frontend plan

### 15. Evaluation report — `/my/skills/[skillId]/evaluations/[evaluationId]` (V2)

```text
┌───────────────────────────────────────────────────────────────┐
│ Evaluation report     [Skill title] [version] [status]        │
│ Overall comparison: without skill | with skill                │
├───────────────────────────────────────────────────────────────┤
│ Trigger accuracy      Task quality uplift                     │
│ Procedure adherence   Guardrail violations                    │
│ Factual grounding     Cross-platform consistency               │
│ Token cost            Execution time                           │
│ [Metric details / benchmark prompts / retry if failed]         │
└───────────────────────────────────────────────────────────────┘
```

Metrics are those named in the project specification. Do not invent scores; show unavailable, pending, and failed states from the evaluation service.

### 16. Optimizer history — `/my/skills/[skillId]/history` (V3)

```text
┌───────────────────────────────────────────────────────────────┐
│ Optimization history                    [current version]     │
│ Version list       │ Selected version comparison              │
│ v1  [baseline]     │ Changed SkillSpec fields                  │
│ v2  [candidate]    │ Evaluation result / benchmark delta       │
│ v3  [best]         │ [Compare versions] [Open package preview] │
└───────────────────────────────────────────────────────────────┘
```

The comparison fields and “best version” label come from AI-23/Backend data. Keep this screen unavailable in V1 until the V3 service exists.

## Shared states and interaction rules

- Every data-backed page has loading, empty, error-with-recovery, and ready states; FE-17 adds and verifies them across the app.
- Multi-step forms show the current step, validate inline, preserve answers when moving back, and provide a clear skip/back action where the task plan allows it.
- Keyboard focus order follows the visible reading order. Desktop navigation collapses; mobile navigation opens as a labeled drawer.
- Long-running work displays named pipeline stages and source links, not a fabricated ETA or percentage.
- Billing, paid marketplace, and chat-history screens are excluded from the V1 wireframes because they are not in the supplied V1 page scope.
