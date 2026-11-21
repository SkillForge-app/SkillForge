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
from core.agents.writers.triggers import (
    Descriptions,
    describe,
    description_issues,
    write_descriptions,
)

__all__ = [
    "Claim",
    "Descriptions",
    "ReferenceFile",
    "WriterRefused",
    "WriterUnavailable",
    "claim_issues",
    "describe",
    "description_issues",
    "summarise",
    "write_reference",
    "write_descriptions",
    "write_references",
]
