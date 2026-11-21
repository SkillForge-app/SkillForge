"""Writers that turn a SkillSpec into package content (Track B): AI-13 reference files and
AI-14 trigger descriptions. See docs/ai/skill-architect.md, "Writers"."""

from core.agents.writers.references import (
    Claim,
    ReferenceFile,
    WriterRefused,
    WriterUnavailable,
    claim_issues,
    summarise,
    write_reference,
    write_references,
)

__all__ = [
    "Claim",
    "ReferenceFile",
    "WriterRefused",
    "WriterUnavailable",
    "claim_issues",
    "summarise",
    "write_reference",
    "write_references",
]
