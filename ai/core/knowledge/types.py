"""Passage: what retrieval returns (contract A4, Track A → Track B's AI-12 and AI-13).

A passage is one chunk of a source page: a short summary of what the page says, with the
page's URL, its own title and the date it was retrieved. The SkillSpec needs that date
(`sources[].retrieved`), so every passage carries it. `to_source` turns a passage into a
SkillSpec `sources[]` entry, so callers cite without re-typing fields.

The five fields are the contract. Adding one is a contract change: a PR both tracks approve.
"""

from datetime import date
from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints

from core.spec.models import Line, Source, SpecModel

ChunkId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:/-]{2,127}$")]
PassageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class Passage(SpecModel):
    chunk_id: ChunkId = Field(
        description="Stable id of the chunk, e.g. mkt-ftc-endorsements-01. Same chunk, same id."
    )
    text: PassageText = Field(
        description="A short summary of what the source says here. Summarised, never a long "
        "copied passage."
    )
    source_url: HttpUrl = Field(description="The page this chunk comes from.")
    title: Line = Field(description="The page's own title.")
    retrieved: date = Field(description="Date the page was retrieved (YYYY-MM-DD).")


def to_source(passage: Passage, source_id: str) -> Source:
    """The SkillSpec `sources[]` entry for a passage. `source_id` is a kebab-case id, e.g. src-1.

    Passages from the same page give equal sources apart from the id: cite the page once.
    """
    return Source(
        id=source_id, url=passage.source_url, retrieved=passage.retrieved, title=passage.title
    )


__all__ = ["ChunkId", "Passage", "to_source"]
