"""What Data Engineering needs from AI's code, as interfaces.

AI owns `extract_page`, `embed` and `normalise_url`. They are not copied or imported here: the pipeline depends on
these small interfaces, tests use fakes, and a thin adapter around AI's real functions is added when their package
is installable. The shapes below are the fields DE stores; adapters convert AI's models into them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


class PipelineError(Exception):
    """A page could not be processed. The old content stays as it was."""


@dataclass(frozen=True)
class ExtractedChunk:
    chunk_id: str                      # AI's id: <host>-<sha256(url)[:8]>-<sha256(text)[:8]>
    text: str                          # at most 2000 characters
    position: int                      # order on the page, from 0
    word_count: int
    content_hash: str                  # sha256 hex of `text`
    section: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedPage:
    url: str                           # canonical URL
    title: str
    text: str                          # clean main text
    quality_ok: bool
    quality_reasons: tuple[str, ...] = ()
    language: str | None = None
    screening: Mapping[str, Any] | None = None     # AI's ScreeningReport as a dict, stored as it is
    chunks: tuple[ExtractedChunk, ...] = field(default_factory=tuple)   # empty unless quality_ok


class ExtractPage(Protocol):
    """AI's `extract_page(html, url=..., retrieved=..., config=...)`, with the config already bound."""

    def __call__(self, html: bytes | str, *, url: str, retrieved: date) -> ExtractedPage: ...


class Embed(Protocol):
    """AI's `embed(texts, model_role="embedding")`: one 384-d unit-length vector per text, in order."""

    def __call__(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class NormaliseUrl(Protocol):
    """AI's `normalise_url(url)`: the canonical URL. Raises ValueError for anything that is not http(s)."""

    def __call__(self, url: str) -> str: ...
