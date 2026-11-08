"""DE-09: freshness rules, as configuration (the architecture doc: "the freshness window is a config value, not a column")."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta


@dataclass(frozen=True)
class FreshnessRules:
    """How old a page may be and how many pages make a domain "covered".

    Assumptions (documents give the 30 days only): web pages 30 days; SKILL.md files and repository files 90 days (they change
    slowly); 5 fresh current documents cover a domain until AI gives the number that really counts as enough.
    """

    max_age: timedelta = timedelta(days=30)
    max_age_by_source_type: dict[str, timedelta] = field(
        default_factory=lambda: {"skill_md": timedelta(days=90), "repo_file": timedelta(days=90)})
    min_documents: int = 5

    def __post_init__(self) -> None:
        if self.min_documents < 1:
            raise ValueError("min_documents must be at least 1")
        if self.max_age <= timedelta(0) or any(a <= timedelta(0) for a in self.max_age_by_source_type.values()):
            raise ValueError("a maximum age must be positive")

    def max_age_for(self, source_type: str) -> timedelta:
        return self.max_age_by_source_type.get(source_type, self.max_age)
