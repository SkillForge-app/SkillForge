
from dataclasses import dataclass


@dataclass
class PlatformSchema:
    name: str
    instruction_file: str
    config_file: str


CLAUDE_CODE_SCHEMA = PlatformSchema(
    name="claude_code",
    instruction_file="CLAUDE.md",
    config_file=".claude/settings.json"
)


CODEX_SCHEMA = PlatformSchema(
    name="codex",
    instruction_file="AGENTS.md",
    config_file=".codex/config.toml"
)
