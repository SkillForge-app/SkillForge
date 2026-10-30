"""Chunking rules (AI-10) on built units: no spaCy, no pages."""

import json
import re

import pytest
from pydantic import ValidationError

from core.knowledge.chunking import (
    ChunkSettings,
    Unit,
    chunk_id,
    chunk_units,
    content_hash,
    join_units,
)
from core.knowledge.types import Passage

SETTINGS = ChunkSettings()
URL = "https://www.example.org/guide"


def sentences(section: str, count: int, words: int = 12, *, heading: bool = True) -> list[Unit]:
    """A section: an optional heading, then one paragraph of `count` distinct sentences."""
    path = (section,)
    units = [Unit(section, path, True, True, kind="heading")] if heading else []
    return units + paragraph(section.lower(), count, path, words)


def paragraph(
    name: str, count: int, path: tuple[str, ...], words: int = 12, group: int | None = None
) -> list[Unit]:
    """`count` distinct sentences of `words` words; the first one opens the paragraph."""
    return [
        Unit(
            " ".join(f"{name}{i}w{j}" for j in range(words - 1)) + " end.",
            path,
            new_block=i == 0,
            group=group,
        )
        for i in range(count)
    ]


def items(name: str, count: int, path: tuple[str, ...], group: int, words: int = 8) -> list[Unit]:
    return [
        Unit(
            "- " + " ".join(f"{name}{i}w{j}" for j in range(words - 1)),
            path,
            new_block=True,
            kind="item",
            group=group,
        )
        for i in range(count)
    ]


def test_chunks_respect_size_limits() -> None:
    chunks = chunk_units(sentences("Long", 60), SETTINGS)
    assert len(chunks) > 3
    for c in chunks:
        words = len(c.text.split())
        assert SETTINGS.min_words <= words <= SETTINGS.max_words
        assert len(c.text) <= SETTINGS.max_chars
    # Packing aims at the target: no chunk but the last stops far short of it.
    assert all(len(c.text.split()) > SETTINGS.target_words - 15 for c in chunks[:-1])


def test_a_continuing_chunk_starts_with_its_heading_then_the_last_sentences_before() -> None:
    chunks = chunk_units(sentences("Long", 60), SETTINGS)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        context, rest = nxt.units[0], nxt.units[1:]
        assert context.context and context.text == "Long"
        assert nxt.text.startswith("Long\n")
        new = [u for u in rest if u not in prev.units]
        overlap = rest[: len(rest) - len(new)]
        assert 1 <= len(overlap) <= SETTINGS.overlap_sentences
        assert sum(u.words for u in overlap) <= SETTINGS.overlap_words
        assert list(overlap) == list(prev.units[-len(overlap) :])


def test_the_repeated_heading_counts_toward_the_limits() -> None:
    long_heading = " ".join(f"question{i}" for i in range(60)) + "?"
    path = (long_heading,)
    units = [Unit(long_heading, path, new_section=True, new_block=True, kind="heading")]
    units += [
        Unit(" ".join(f"s{i}w{j}" for j in range(19)) + ".", path, new_block=i == 0)
        for i in range(40)
    ]
    chunks = chunk_units(units, SETTINGS)
    assert len(chunks) > 2
    for c in chunks:
        assert c.text.startswith(long_heading + "\n")
        assert len(c.text.split()) <= SETTINGS.max_words and len(c.text) <= SETTINGS.max_chars


def test_a_section_without_a_heading_gets_no_heading_line() -> None:
    chunks = chunk_units(sentences("Intro", 40, heading=False), SETTINGS)
    assert len(chunks) > 1
    assert not any(u.context for c in chunks for u in c.units)


def test_the_leftover_of_a_long_section_joins_the_chunk_before_not_the_next_section() -> None:
    # Alpha: about 200 words, so one full chunk plus a leftover under min_words.
    units = sentences("Alpha", 16) + sentences("Beta", 8)
    chunks = chunk_units(units, SETTINGS)
    assert [c.section for c in chunks] == [("Alpha",), ("Beta",)]
    assert chunks[0].text.endswith(units[16].text)  # Alpha's last sentence stayed in Alpha
    assert chunks[1].text.startswith("Beta\n") and "alpha" not in chunks[1].text


def test_a_new_section_starts_a_new_chunk_without_overlap() -> None:
    units = sentences("Alpha", 8) + sentences("Beta", 8)
    chunks = chunk_units(units, SETTINGS)
    assert [c.section for c in chunks] == [("Alpha",), ("Beta",)]
    assert chunks[1].text.startswith("Beta\n")
    assert "Alpha" not in chunks[1].text and "beta0" not in chunks[0].text


def test_short_sections_are_packed_together_with_their_headings() -> None:
    units = sentences("One", 1) + sentences("Two", 1) + sentences("Three", 1) + sentences("Four", 9)
    chunks = chunk_units(units, SETTINGS)
    first = chunks[0].text
    assert first.startswith("One\n") and "\nTwo\n" in first and "\nThree\n" in first
    assert chunks[0].section == ("One",)


def test_a_chunk_never_ends_on_a_sub_heading() -> None:
    path = ("Long",)
    units = sentences("Long", 14)  # 169 words: "Details" still fits, its text does not
    units += [Unit("Details", path, new_block=True, kind="subheading")]
    units += paragraph("detail", 5, path)
    chunks = chunk_units(units, SETTINGS)
    assert len(chunks) == 2
    assert all(c.units[-1].kind not in {"heading", "subheading"} for c in chunks)
    assert chunks[1].text.startswith("Long\nDetails\ndetail0w0")


def test_a_heading_with_no_text_after_it_is_dropped() -> None:
    orphan = Unit("Orphan", ("Orphan",), True, True, kind="heading")
    chunks = chunk_units(sentences("Alpha", 6) + [orphan], SETTINGS)
    assert len(chunks) == 1 and "Orphan" not in chunks[0].text


def test_a_lone_sentence_opening_a_paragraph_moves_to_the_next_chunk() -> None:
    path = ("Long",)
    # 169 words, then a paragraph whose 10-word first sentence fits but whose second does not.
    units = sentences("Long", 14) + paragraph("next", 6, path, words=10)
    chunks = chunk_units(units, SETTINGS)
    assert chunks[0].units[-1] == units[14]  # ends on the last sentence of the old paragraph
    assert chunks[1].units[1] == units[15]  # the new paragraph starts the next chunk ...
    assert chunks[1].text.startswith("Long\nnext0w0")  # ... with no overlap before it


def test_a_list_is_finished_in_the_chunk_when_it_fits() -> None:
    path = ("Long",)
    intro = Unit("The steps are as follows:", path, group=1)
    units = sentences("Long", 13) + [intro] + items("step", 6, path, group=1)
    chunks = chunk_units(units, SETTINGS)  # 210 words: over the target, under max_words
    assert len(chunks) == 1
    assert chunks[0].text.endswith(units[-1].text)


def test_a_list_moves_on_with_its_intro_when_it_cannot_finish_here() -> None:
    path = ("Long",)
    intro = Unit("The steps are as follows:", path, group=1)
    steps = items("step", 12, path, group=1)
    chunks = chunk_units(sentences("Long", 13) + [intro] + steps, SETTINGS)
    assert len(chunks) == 2
    assert intro.text not in chunks[0].text
    assert f"{intro.text}\n{steps[0].text}" in chunks[1].text
    assert chunks[1].text.endswith(steps[-1].text)


def test_a_long_list_never_splits_right_after_its_intro_and_one_item() -> None:
    path = ("Long",)
    intro = Unit("These are the main requirements:", path, group=1)
    steps = items("rule", 10, path, group=1, words=30)  # 300 words: no chunk can hold it all
    chunks = chunk_units(sentences("Long", 13) + [intro] + steps, SETTINGS)
    assert intro.text not in chunks[0].text
    holder = next(c for c in chunks if intro.text in c.text)
    after = holder.text.split(intro.text, 1)[1]
    assert after.count("\n- ") >= 2  # the intro is followed by at least two items
    assert all(len(c.text.split()) <= SETTINGS.max_words for c in chunks)


def test_a_list_too_long_for_one_chunk_is_split_within_the_limits() -> None:
    path = ("Long",)
    steps = items("step", 40, path, group=1)
    chunks = chunk_units(sentences("Long", 3) + [Unit("Steps:", path, group=1)] + steps, SETTINGS)
    assert len(chunks) > 1
    assert all(len(c.text.split()) <= SETTINGS.max_words for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    assert all(step.text in joined for step in steps)


def test_a_small_tail_joins_the_chunk_before() -> None:
    units = sentences("Tail", 17)  # about 205 words: one chunk plus a tail under min_words
    chunks = chunk_units(units, SETTINGS)
    assert len(chunks) == 1
    assert chunks[0].text.endswith(units[-1].text)
    assert len(chunks[0].text.split()) <= SETTINGS.max_words


def test_a_unit_longer_than_max_words_is_split_at_word_boundaries() -> None:
    giant = Unit(" ".join(f"w{i}" for i in range(700)) + ".", ("Big",), True, True)
    chunks = chunk_units([giant], SETTINGS)
    assert len(chunks) == 3
    assert all(len(c.text.split()) <= SETTINGS.max_words for c in chunks)
    assert " ".join(c.text for c in chunks).split() == giant.text.split()


def test_long_words_respect_the_character_cap() -> None:
    # 10 words of 21 characters per unit: 250 words would be over 5,000 characters.
    wide = [Unit(" ".join(["x" * 20] * 10) + ".", ("Wide",), i == 0, i == 0) for i in range(30)]
    chunks = chunk_units(wide, SETTINGS)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= SETTINGS.max_chars
        passage = {
            "chunk_id": chunk_id(URL, c.text),
            "text": c.text,
            "source_url": URL,
            "title": "Wide",
            "retrieved": "2026-10-25",
        }
        Passage.model_validate_json(json.dumps(passage))  # fits the A4 text limit


def test_identical_chunks_on_a_page_are_dropped() -> None:
    repeated = sentences("Same", 6)
    chunks = chunk_units(repeated + repeated, SETTINGS)
    assert len(chunks) == 1


def test_units_join_with_newlines_between_blocks_and_spaces_within() -> None:
    units = [
        Unit("Heading", ("Heading",), True, True, kind="heading"),
        Unit("First sentence.", ("Heading",), new_block=True),
        Unit("Second sentence.", ("Heading",)),
        Unit("- a list item", ("Heading",), new_block=True),
    ]
    assert join_units(units) == "Heading\nFirst sentence. Second sentence.\n- a list item"


def test_empty_input_gives_no_chunks() -> None:
    assert chunk_units([], SETTINGS) == []


# ------------------------------------------------------------------ ids


def test_chunk_ids_are_deterministic_and_match_the_a4_pattern() -> None:
    first = chunk_id(URL, "Some text.")
    assert first == chunk_id(URL, "Some text.")
    assert first != chunk_id(URL, "Other text.")
    assert first != chunk_id("https://www.example.org/other", "Some text.")
    assert first.startswith("example.org-")
    assert re.fullmatch(r"^[a-z0-9][a-z0-9._:/-]{2,127}$", first)
    assert re.fullmatch(r"[0-9a-f]{64}", content_hash("Some text."))


def test_odd_hosts_still_give_valid_ids() -> None:
    for url in ("https://Ünïcode.Example/x", "https://-weird-.example/", "https://[::1]/a"):
        assert re.fullmatch(r"^[a-z0-9][a-z0-9._:/-]{2,127}$", chunk_id(url, "t"))


def test_unchanged_chunks_keep_their_ids_when_another_section_changes() -> None:
    def ids(units: list[Unit]) -> set[str]:
        return {chunk_id(URL, c.text) for c in chunk_units(units, SETTINGS)}

    before = sentences("Alpha", 8) + sentences("Beta", 8)
    after = sentences("Alpha", 8) + sentences("Beta", 8) + sentences("Gamma", 8)
    assert ids(before) <= ids(after)


# ------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    "changes",
    [
        {"min_words": 200},
        {"target_words": 300},
        {"max_chars": 2001},
        {"overlap_words": 180},
        {"overlap_sentences": -1},
    ],
)
def test_bad_settings_are_rejected(changes: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        ChunkSettings.model_validate(changes)
