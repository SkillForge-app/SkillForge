# Claude Code and Codex Compiler Field Mapping

## 1. Overview

This document describes how SkillSpec v0.2 capabilities are translated into Claude Code and OpenAI Codex configuration.

SkillSpec defines:
- `tools.required`: capabilities the skill needs.
- `tools.optional`: capabilities the skill may use.

The legacy AgentSpec `autonomy.level` field is not part of SkillSpec v0.2. Codex receives it separately through the `autonomy_level` compiler argument, defaulting to `medium`.

## 2. Claude Code

Generated files:
- `CLAUDE.md`
- `.claude/settings.json`

### Capability mapping

| SkillSpec capability | Claude Code tools |
|---|---|
| `filesystem_read` | `Read`, `Glob`, `Grep` |
| `filesystem_write` | `Write`, `Edit` |
| `terminal` | `Bash` |
| `code_execution` | `Bash` |
| `web_search` | `WebSearch` |
| `web_fetch` | `WebFetch` |
| `browser` | No direct mapping |

### Permission mapping

| Declaration | Permission |
|---|---|
| Required read/search/fetch | `allow` |
| Required filesystem write | `ask` |
| Required terminal/code execution | `ask` |
| Supported optional capability | `ask` |
| Unsupported capability | No permission entry |

Duplicate tool names are removed and generated lists are sorted. The `deny` list is currently empty.

### Autonomy

The Claude compiler does not currently accept or process an autonomy level. Permissions are determined by required and optional capabilities.

## 3. OpenAI Codex

Generated files:
- `AGENTS.md`
- `.codex/config.toml`

### Capability mapping

| SkillSpec capability | Codex behavior |
|---|---|
| `filesystem_read` | Covered by the selected sandbox |
| `filesystem_write` | Selects `workspace-write`, except at low autonomy |
| `terminal` | No separate capability-specific setting |
| `code_execution` | No separate capability-specific setting |
| Required `web_search` | `web_search = "live"` |
| Optional `web_search` | `web_search = "cached"` |
| Undeclared `web_search` | `web_search = "disabled"` |
| `web_fetch` | No direct mapping |
| `browser` | No direct mapping |

### Autonomy mapping

| Level | Approval policy | Sandbox |
|---|---|---|
| `low` | `on-request` | Always `read-only` |
| `medium` | `on-request` | `workspace-write` if filesystem_write is required; otherwise `read-only` |
| `high` | `never` | `workspace-write` if filesystem_write is required; otherwise `read-only` |

Low autonomy takes precedence over required filesystem write access. Invalid autonomy values are rejected.

## 4. Legacy AgentSpec Compatibility

- Legacy flat tool declarations are represented through `tools.required` and `tools.optional`.
- Legacy `autonomy.level` is passed separately to Codex through `autonomy_level`.
- Claude currently has no direct autonomy mapping.

## 5. Security Considerations

- `read-only` restricts filesystem writes through the Codex sandbox.
- `workspace-write` allows writes within the configured workspace boundary.
- `approval_policy = "never"` disables approval prompts and should be used carefully.
- Approval policy and sandbox mode are separate controls.
- Generated configuration does not replace runtime isolation or platform security controls.

## 6. Platform References

- Codex: https://developers.openai.com/codex/config-reference/
- Claude Code: https://docs.anthropic.com/en/docs/claude-code/settings
