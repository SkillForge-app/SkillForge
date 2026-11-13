"""Chunking for retrieval (AI-10): pack sentences into chunks of about one idea each.

Input is a page as a list of `Unit`s in reading order: a sentence, a heading, a list item or a
table row. Rules (sizes from `ChunkSettings`; docs/ai/extraction.md explains the choices):
- A new section (an H1–H3 heading) starts a new chunk. Only a section that is itself short
  (under `min_words`) is packed together with the next one, headings included.
- Within a section, units are packed up to `target_words`. A chunk that continues a section
  starts with the section's heading (so it stands alone). When the break falls inside a
  paragraph, it then repeats the last whole sentences of the chunk before (at most
  `overlap_sentences` and `overlap_words`). Both count toward the limits.
- Where a chunk ends: never on a heading or sub-heading, and never on a lone sentence that
  opens a paragraph; those move to the next chunk. A list stays with the sentence that
  introduces it: it is finished in the chunk when it fits there, or moves on whole when it
  fits in one chunk. A list too long for one chunk is split, but never right after its intro
  and a single item.
- The leftover of a long section (under `min_words`) joins the chunk before it, never the next
  section; a short last chunk on the page does the same, when the result still fits.
- A heading with no text after it (at a section or page end) is dropped.
- No chunk goes over `max_words` or `max_chars`; a longer unit is split at word boundaries.
- A chunk whose text already appeared on the page is dropped.
"""

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from core.spec.models import SpecModel


class ChunkSettings(SpecModel):
    target_words: int = Field(default=180, ge=20)
    max_words: int = Field(default=250, ge=20)
    max_chars: int = Field(default=1800, ge=200, le=2000)  # A4 Passage.text allows 2000
    min_words: int = Field(default=50, ge=1)
    overlap_sentences: int = Field(default=2, ge=0)
    overlap_words: int = Field(default=40, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "ChunkSettings":
        if not self.min_words < self.target_words <= self.max_words:
            raise ValueError("need min_words < target_words <= max_words")
        if self.overlap_words >= self.target_words:
            raise ValueError("overlap_words must be smaller than target_words")
        return self


UnitKind = Literal["heading", "subheading", "sentence", "item", "row"]
_HEADINGS = frozenset({"heading", "subheading"})


@dataclass(frozen=True)
class Unit:
    text: str
    section: tuple[str, ...]  # heading path (H1–H3) this unit sits under
    new_section: bool = False  # True for the first unit of a section (its heading, if any)
    new_block: bool = False  # starts a paragraph, list item, row or heading: joined with "\n"
    terms: tuple[str, ...] = ()
    context: bool = False  # the section heading repeated at the top of a continuing chunk
    kind: UnitKind = "sentence"  # "heading" is an H1–H3, "subheading" an H4–H6
    group: int | None = None  # a list: its items, and the sentence that introduces them

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class RawChunk:
    text: str
    section: tuple[str, ...]
    units: tuple[Unit, ...]  # including the heading context and overlap units at the start


def chunk_units(units: list[Unit], settings: ChunkSettings) -> list[RawChunk]:
    pieces = [piece for unit in units for piece in _split_long(unit, settings)]
    lists: dict[int, list[Unit]] = {}
    for piece in pieces:
        if piece.group is not None:
            lists.setdefault(piece.group, []).append(piece)
    headings: dict[tuple[str, ...], Unit] = {}
    groups: list[tuple[list[Unit], int]] = []  # (units, how many leading units are carried)
    current: list[Unit] = []
    carried = 0

    def emit() -> None:
        nonlocal current, carried
        fresh = _without_trailing_headings(current[carried:])  # a heading needs text after it
        if fresh:
            groups.append((current[:carried] + fresh, carried))
        current, carried = [], 0

    def continues() -> bool:
        # The chunk picks up a section that an earlier chunk started (not its heading).
        return bool(groups) and not current[carried].new_section

    for unit in pieces:
        if unit.new_section and unit.section and unit.text == unit.section[-1]:
            headings[unit.section] = unit
        if not current:
            current = [unit]
            continue
        size = _words(current)
        fresh = current[carried:]
        if unit.new_section and (_words(fresh) >= settings.min_words or continues()):
            leftover = _without_trailing_headings(fresh)
            if _words(leftover) < settings.min_words and _fits(groups[-1][0] + leftover, settings):
                prev, prev_carried = groups[-1]
                groups[-1] = (prev + leftover, prev_carried)  # a leftover joins the chunk before
                current, carried = [], 0
            emit()
            current = [unit]
            continue
        rest = _rest_of_list(fresh, unit, lists)
        if _fits(current + [unit], settings) and (
            size + unit.words <= settings.target_words
            or size < settings.min_words
            or (rest and _fits(current + rest, settings))  # finish a list begun in this chunk
        ):
            current.append(unit)
            continue
        cut = _cut(current, carried, unit, lists, headings, settings)
        moved = current[cut:]
        start = moved[0] if moved else unit
        following = moved + [unit]
        prefix = _context(start, headings.get(start.section), following, settings)
        # Overlap only when the break falls inside a paragraph: a chunk that starts a new
        # paragraph should not open with the end of the one before.
        overlap = (
            [] if start.new_block else _overlap(current[carried:cut], prefix, following, settings)
        )
        current = current[:cut]
        emit()
        current = prefix + overlap + following
        carried = len(prefix) + len(overlap)
    emit()

    if len(groups) > 1:
        (prev, prev_carried), (last, last_carried) = groups[-2], groups[-1]
        tail = last[last_carried:]
        if _words(tail) < settings.min_words and _fits(prev + tail, settings):
            groups[-2:] = [(prev + tail, prev_carried)]

    chunks: list[RawChunk] = []
    seen: set[str] = set()
    for group, skip in groups:
        text = join_units(group)
        if text in seen:
            continue
        seen.add(text)
        chunks.append(RawChunk(text, group[skip].section, tuple(group)))
    return chunks


def join_units(units: list[Unit] | tuple[Unit, ...]) -> str:
    out = ""
    for i, unit in enumerate(units):
        if i:
            out += "\n" if unit.new_block or units[i - 1].context else " "
        out += unit.text
    return out


def _words(units: list[Unit]) -> int:
    return sum(u.words for u in units)


def _fits(units: list[Unit], settings: ChunkSettings) -> bool:
    return _words(units) <= settings.max_words and len(join_units(units)) <= settings.max_chars


def _without_trailing_headings(units: list[Unit]) -> list[Unit]:
    end = len(units)
    while end and units[end - 1].kind in _HEADINGS:
        end -= 1
    return units[:end]


def _rest_of_list(fresh: list[Unit], unit: Unit, lists: dict[int, list[Unit]]) -> list[Unit]:
    """`unit` and the rest of its list, when this chunk already holds the list's start."""
    if unit.group is None or not any(u.group == unit.group for u in fresh):
        return []
    members = lists[unit.group]
    at = next(i for i, u in enumerate(members) if u is unit)
    return members[at:]


def _cut(
    current: list[Unit],
    carried: int,
    nxt: Unit,
    lists: dict[int, list[Unit]],
    headings: dict[tuple[str, ...], Unit],
    settings: ChunkSettings,
) -> int:
    """Where the chunk ends when `nxt` does not fit: units from the cut on move to the next
    chunk. At least one unit the chunk did not carry always stays."""
    cut = len(current)
    # A list's intro and items move on together when the whole list fits in one chunk. A list
    # too long for any chunk is split, but never right after its intro and a single item.
    if nxt.group is not None:
        start = next((k for k in range(carried, cut) if current[k].group == nxt.group), None)
        whole = lists[nxt.group]
        context = _context(whole[0], headings.get(whole[0].section), whole, settings)
        if start is not None and start > carried:
            begun = current[start:cut]
            has_intro = begun[0].kind == "sentence"
            if _fits(context + whole, settings) or (
                has_intro and sum(u.kind == "item" for u in begun) < 2
            ):
                cut = start
    # A sentence that opens a paragraph never ends a chunk alone: it moves on with the rest.
    follower = current[cut] if cut < len(current) else nxt
    last = current[cut - 1]
    if cut - 1 > carried and last.kind == "sentence" and last.new_block and not follower.new_block:
        cut -= 1
    # Nor does a heading or sub-heading: it moves on with its text.
    while cut - 1 > carried and current[cut - 1].kind in _HEADINGS:
        cut -= 1
    if cut < len(current) and not _fits(current[cut:] + [nxt], settings):
        return len(current)  # what would move does not fit in one chunk: break as it is
    return cut


def _context(
    start: Unit, heading: Unit | None, following: list[Unit], settings: ChunkSettings
) -> list[Unit]:
    """The section heading, repeated at the top of a chunk that continues the section."""
    if start.new_section or heading is None:
        return []
    context = Unit(
        heading.text,
        heading.section,
        new_block=True,
        terms=heading.terms,
        context=True,
        kind="heading",
    )
    return [context] if _fits([context] + following, settings) else []


def _overlap(
    before: list[Unit], prefix: list[Unit], following: list[Unit], settings: ChunkSettings
) -> list[Unit]:
    """The last whole sentences of the chunk before, as long as there is still room."""
    overlap: list[Unit] = []
    for unit in reversed(before):
        candidate = [unit] + overlap
        if (
            len(candidate) > settings.overlap_sentences
            or _words(candidate) > settings.overlap_words
            or unit.kind != "sentence"
            or not _fits(prefix + candidate + following, settings)
        ):
            break
        overlap = candidate
    return overlap


def _split_long(unit: Unit, settings: ChunkSettings) -> list[Unit]:
    if unit.words <= settings.max_words and len(unit.text) <= settings.max_chars:
        return [unit]
    pieces: list[Unit] = []
    words = unit.text.split()
    start = 0
    while start < len(words):
        end = min(start + settings.max_words, len(words))
        while end - start > 1 and len(" ".join(words[start:end])) > settings.max_chars:
            end -= 1
        first = start == 0
        pieces.append(
            replace(
                unit,
                text=" ".join(words[start:end]),
                new_section=unit.new_section and first,
                new_block=unit.new_block and first,
                terms=unit.terms if first else (),
            )
        )
        start = end
    return pieces


# ------------------------------------------------------------------ ids

_HOST_CHARS = re.compile(r"[^a-z0-9.-]")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(url: str, text: str) -> str:
    """`<host>-<url hash>-<text hash>`: the same text on the same page always gets the same id."""
    host = _HOST_CHARS.sub("", (urlsplit(url).hostname or "").lower().removeprefix("www."))
    host = host.strip(".-")[:60] or "page"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{host}-{url_hash}-{content_hash(text)[:8]}"
