"""Extraction and NLP rules (AI-10): raw HTML of one page -> clean text, a quality verdict,
key concepts and chunks that become A4 Passages.

    page = extract_page(html, url="https://www.nist.gov/...", retrieved=date(2026, 10, 25))
    if page.quality.ok:
        passages = [chunk.to_passage() for chunk in page.chunks]
    else:
        page.quality.reasons    # e.g. ("paywall_or_login",)

No network: DE-04 fetches the page, DE-05 calls this, DE-06 stores the provenance. The same
HTML and config always give the same output. See docs/ai/extraction.md.
"""

import hashlib
import itertools
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

import trafilatura
from bs4 import BeautifulSoup, Tag
from charset_normalizer import from_bytes
from lxml import etree
from lxml import html as lxml_html
from pydantic import Field, HttpUrl, ValidationError, field_validator

from core.knowledge import nlp
from core.knowledge.chunking import (
    ChunkSettings,
    RawChunk,
    Unit,
    UnitKind,
    chunk_id,
    chunk_units,
)
from core.knowledge.chunking import content_hash as hash_text
from core.knowledge.injection_guard import ScreeningReport, page_rejected, screen_block
from core.knowledge.types import ChunkId, Passage, PassageText
from core.spec.models import Line, SpecModel

Reason = Literal[
    "empty", "paywall_or_login", "boilerplate", "wrong_language", "too_short", "injection"
]
REASONS: tuple[Reason, ...] = (
    "empty",
    "paywall_or_login",
    "boilerplate",
    "wrong_language",
    "too_short",
    "injection",
)
Extractor = Literal["trafilatura", "bs4", "none"]
# Languages with a spaCy pipeline wired in (nlp.SPACY_MODEL). Add a pipeline before a language.
SUPPORTED_LANGUAGES = frozenset({"en"})

PAYWALL_PHRASES = (
    "subscribe to continue reading",
    "subscribe to keep reading",
    "subscribe to read the full",
    "this content is for subscribers",
    "for subscribers only",
    "sign in to continue",
    "sign in to read",
    "log in to continue",
    "log in to read",
    "login to continue",
    "create a free account to continue",
    "register to continue reading",
    "you have reached your limit of free articles",
)
CONSENT_PHRASES = (
    "we use cookies",
    "this site uses cookies",
    "this website uses cookies",
    "accept all cookies",
    "cookie preferences",
    "cookie settings",
    "manage consent",
)


class ExtractionInputError(ValueError):
    """The caller passed a bad URL."""


class ExtractConfig(SpecModel):
    """Every threshold DE-05 may tune. Defaults are the ones docs/ai/extraction.md explains."""

    min_words: int = Field(default=150, ge=1)
    # trafilatura's trade-off: "precision" drops more boilerplate, "recall" keeps more content.
    extraction_mode: Literal["precision", "balanced", "recall"] = "precision"
    languages: tuple[str, ...] = ("en",)
    min_language_confidence: float = Field(default=0.8, ge=0, le=1)
    max_link_density: float = Field(default=0.5, gt=0, le=1)
    max_short_line_ratio: float = Field(default=0.6, gt=0, le=1)
    short_line_words: int = Field(default=5, ge=1)
    consent_max_words: int = Field(default=300, ge=0)
    password_max_words: int = Field(default=300, ge=0)
    paywall_phrase_max_words: int = Field(default=400, ge=0)
    page_concepts: int = Field(default=10, ge=0)
    chunk_concepts: int = Field(default=5, ge=0)
    chunking: ChunkSettings = Field(default_factory=ChunkSettings)
    # Off by default. To remove a site's template text (an "About us" block repeated inside
    # every article body), pass the hashes find_site_boilerplate() returns for that site.
    site_boilerplate: tuple[str, ...] = Field(
        default=(),
        description="sha256 of normalised sentences to remove; empty turns removal off.",
    )
    # AI-19: remove sentences aimed at an AI reader before chunking (injection_guard rules).
    injection_screen: bool = True
    # This many low findings on one page reject it, like any high finding (reason injection).
    injection_max_low: int = Field(default=3, ge=1)

    @field_validator("languages")
    @classmethod
    def _supported(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unsupported = sorted(set(value) - SUPPORTED_LANGUAGES)
        if not value or unsupported:
            raise ValueError(f"languages must be from {sorted(SUPPORTED_LANGUAGES)}")
        return value


class QualityReport(SpecModel):
    reasons: tuple[Reason, ...] = Field(description="Why the page is rejected; empty when ok.")
    word_count: int
    link_density: float = Field(description="Share of main-content characters inside links.")
    short_line_ratio: float = Field(description="Share of text blocks under short_line_words.")
    language: str | None
    language_confidence: float | None

    @property
    def ok(self) -> bool:
        return not self.reasons


class Chunk(SpecModel):
    chunk_id: ChunkId
    source_url: HttpUrl
    title: Line
    retrieved: date
    text: PassageText
    section: list[str] = Field(description="Heading path (H1–H3) the chunk starts under.")
    position: int = Field(ge=0, description="Order of the chunk on the page, from 0.")
    word_count: int = Field(ge=1)
    concepts: list[str]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="sha256 of `text`.")

    def to_passage(self) -> Passage:
        """The A4 Passage for this chunk (the five contract fields only)."""
        return Passage(
            chunk_id=self.chunk_id,
            text=self.text,
            source_url=self.source_url,
            title=self.title,
            retrieved=self.retrieved,
        )


class ExtractedPage(SpecModel):
    url: HttpUrl
    title: Line
    retrieved: date
    extractor: Extractor
    text: str = Field(description="Clean main text, one block per line.")
    quality: QualityReport
    concepts: list[str] = Field(description="Top key concepts of the page.")
    chunks: list[Chunk] = Field(description="Empty unless quality.ok.")
    screening: ScreeningReport = Field(
        default_factory=ScreeningReport,
        description="AI-19 prompt-injection findings (codes, positions, hashes; never text).",
    )


# ------------------------------------------------------------------ entry point


def extract_page(
    html: str | bytes,
    *,
    url: str,
    retrieved: date,
    config: ExtractConfig | None = None,
) -> ExtractedPage:
    """Extract one page. Never fetches; bad pages come back with `quality.reasons` set."""
    config = config or ExtractConfig()
    try:
        page_url = HttpUrl(url)
    except ValidationError as exc:
        raise ExtractionInputError(f"not an http(s) URL: {url!r}") from exc

    tree = _parse(_decode(html))
    signals = _page_signals(tree)
    cleaned = lxml_html.tostring(tree, encoding="unicode") if tree is not None else ""
    content = _main_content(cleaned, url, config)
    if config.site_boilerplate:
        content = replace(
            content, blocks=_drop_site_boilerplate(content.blocks, set(config.site_boilerplate))
        )
    screening = ScreeningReport(invisible_chars=signals.invisible_chars)
    if config.injection_screen:
        blocks, screening = _screen(content.blocks, screening, config)
        content = replace(content, blocks=blocks)

    text = "\n".join(b.text for b in content.blocks)
    words = len(text.split())
    body = " ".join(b.text for b in content.blocks if b.kind != "heading")
    language = nlp.detect_language(body) if words else None
    quality = QualityReport(
        reasons=_reasons(content, signals, words, language, config, screening.rejected),
        word_count=words,
        link_density=content.link_density,
        short_line_ratio=content.short_line_ratio,
        language=language[0] if language else None,
        language_confidence=language[1] if language else None,
    )
    title = _title(content.title, content.sitename, tree, url)
    if not quality.ok:
        return ExtractedPage(
            url=page_url,
            title=title,
            retrieved=retrieved,
            extractor=content.extractor,
            text=text,
            quality=quality,
            concepts=[],
            chunks=[],
            screening=screening,
        )

    analysed = nlp.analyse([title] + [b.text for b in content.blocks])
    title_terms, block_sentences = analysed[0], analysed[1:]
    units = _units(content.blocks, block_sentences)
    boost = frozenset(
        [t for s in title_terms for t in s.terms]
        + [t for u in units if u.new_section for t in u.terms]
    )
    raw_chunks = chunk_units(units, config.chunking)
    return ExtractedPage(
        url=page_url,
        title=title,
        retrieved=retrieved,
        extractor=content.extractor,
        text=text,
        quality=quality,
        concepts=nlp.rank_concepts(
            (t for u in units for t in u.terms), boost=boost, top=config.page_concepts
        ),
        chunks=[
            _chunk(raw, i, page_url, title, retrieved, boost, config)
            for i, raw in enumerate(raw_chunks)
        ],
        screening=screening,
    )


def _chunk(
    raw: RawChunk,
    position: int,
    url: HttpUrl,
    title: str,
    retrieved: date,
    boost: frozenset[str],
    config: ExtractConfig,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id(str(url), raw.text),
        source_url=url,
        title=title,
        retrieved=retrieved,
        text=raw.text,
        section=[_clip(h) for h in raw.section],
        position=position,
        word_count=len(raw.text.split()),
        concepts=nlp.rank_concepts(
            (t for u in raw.units for t in u.terms), boost=boost, top=config.chunk_concepts
        ),
        content_hash=hash_text(raw.text),
    )


# ------------------------------------------------------------------ parsing and pre-cleaning


def _decode(html: str | bytes) -> str:
    if isinstance(html, str):
        return html
    try:
        return html.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(html).best()
        return str(best) if best is not None else html.decode("latin-1")


def _parse(html: str) -> Any:
    if not html.strip():
        return None
    try:
        return lxml_html.document_fromstring(html)
    except ValueError:  # a str with an XML encoding declaration: lxml wants bytes
        try:
            return lxml_html.document_fromstring(html.encode("utf-8"))
        except (etree.ParserError, ValueError):
            return None
    except etree.ParserError:
        return None


@dataclass(frozen=True)
class _Signals:
    paywall_markup: bool  # JSON-LD isAccessibleForFree: false
    password_field: bool
    page_text: str  # visible text of the whole page, lowercase, after pre-cleaning
    invisible_chars: int = 0  # zero-width, bidi and tag characters in the visible text


_HIDDEN = "//*[@hidden] | //*[@aria-hidden='true']"
# Never prose: page code, form controls and inline SVG (its <text>, <title> and <desc>).
_NOT_TEXT = (
    "//script | //style | //noscript | //template | //svg | //textarea | //input | //select"
    " | //option | //comment() | //processing-instruction()"
)
# Classes that hide text visually on almost every site (screen-reader text, Bootstrap, ...).
_HIDING_CLASSES = frozenset(
    {"sr-only", "visually-hidden", "screen-reader-text", "d-none", "hidden", "invisible"}
)
# Zero-width, soft-hyphen, bidi-control and Unicode tag characters ("ASCII smuggling"): they
# are invisible on the page, so text hidden in them never reaches a chunk.
INVISIBLE_CHARS = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
_WHITE = frozenset({"white", "#fff", "#ffffff", "rgb(255,255,255)", "rgba(255,255,255,1)"})
_LENGTH = re.compile(r"^(-?[\d.]+)(px|em|rem|pt|%)?$")


def _declarations(style: str) -> dict[str, str]:
    """Inline CSS as {property: value}, lowercase, without spaces or !important."""
    found = {}
    for part in style.split(";"):
        name, sep, value = part.partition(":")
        if sep:
            value = "".join(value.lower().split()).replace("!important", "")
            found["".join(name.lower().split())] = value
    return found


def _length(value: str | None) -> tuple[float, str] | None:
    match = _LENGTH.match(value or "")
    if match is None:
        return None
    try:
        return float(match.group(1)), match.group(2) or "px"
    except ValueError:
        return None


def _style_hides(css: dict[str, str]) -> bool:
    """True when these declarations make text invisible to a reader. White text counts here;
    the caller checks for a dark background."""
    if css.get("display") == "none" or css.get("visibility") in {"hidden", "collapse"}:
        return True
    opacity = _length(css.get("opacity"))
    if opacity is not None and opacity[0] <= 0.01:
        return True
    size = _length(css.get("font-size"))
    if size is not None and (size[0] <= 2 if size[1] in {"px", "pt"} else size[0] <= 0.1):
        return True
    for prop in ("left", "top", "text-indent", "margin-left"):
        offset = _length(css.get(prop))
        if offset is not None and offset[1] == "px" and offset[0] <= -999:
            return True
    if css.get("clip", "").startswith("rect(0") or css.get("clip-path") in {
        "inset(50%)",
        "circle(0)",
    }:
        return True
    if css.get("overflow") == "hidden" and any(
        (size := _length(css.get(p))) is not None and size[0] == 0 for p in ("width", "height")
    ):
        return True
    if "scale(0)" in css.get("transform", "") or "scale(0,0)" in css.get("transform", ""):
        return True
    return css.get("color") in _WHITE


def _hidden_by_style(el: Any) -> bool:
    css = _declarations(el.get("style", ""))
    if not _style_hides(css):
        return False
    if css.get("color") not in _WHITE or len(css) > 1 and _style_hides({**css, "color": ""}):
        return True
    # White text is visible on a dark background set on the element or an ancestor.
    for node in [el, *el.iterancestors()]:
        node_css = _declarations(node.get("style", "") if isinstance(node.tag, str) else "")
        background = node_css.get("background-color") or node_css.get("background")
        if background and background not in _WHITE and background not in {"none", "transparent"}:
            return False
    return True


def _hiding_selectors(tree: Any) -> tuple[set[str], set[str]]:
    """Class and id selectors that the page's own <style> blocks hide (top level only: rules
    inside @media and other at-rules apply to some screens only, so they are left alone)."""
    classes: set[str] = set()
    ids: set[str] = set()
    for style in tree.xpath("//style"):
        for selectors, body in _top_level_rules(style.text_content()):
            if not _style_hides({**_declarations(body), "color": ""}):
                continue
            for selector in selectors.split(","):
                match = re.fullmatch(r"\s*[a-z0-9]*([.#])([\w-]+)\s*", selector, re.IGNORECASE)
                if match:
                    (classes if match.group(1) == "." else ids).add(match.group(2))
    return classes, ids


def _top_level_rules(css: str) -> Iterator[tuple[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    depth, start, selector = 0, 0, ""
    for i, char in enumerate(css):
        if char == "{":
            if depth == 0:
                selector, start = css[start:i], i + 1
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                if not selector.strip().startswith("@"):
                    yield selector, css[start:i]
                start = i + 1


# Citation markers, reference lists and edit links: not prose a skill can learn from.
_NOT_PROSE = (
    "//sup[contains(@class, 'reference')] | //*[contains(@class, 'mw-editsection')]"
    " | //*[contains(concat(' ', normalize-space(@class), ' '), ' references ')]"
    " | //*[contains(@class, 'reflist')] | //*[contains(@class, 'mw-references-wrap')]"
    " | //*[contains(@class, 'navbox')]"
)


def _page_signals(tree: Any) -> _Signals:
    """Read page-level signals, then pre-clean the tree in place for the extractors."""
    if tree is None:
        return _Signals(False, False, "")
    paywall = any(
        _not_free(_json_or_none(script.text_content()))
        for script in tree.xpath("//script[@type='application/ld+json']")
    )
    password = bool(tree.xpath("//input[translate(@type, 'PASSWORD', 'password')='password']"))
    hidden_classes, hidden_ids = _hiding_selectors(tree)
    hidden_classes |= _HIDING_CLASSES
    for el in tree.xpath(_NOT_TEXT):
        if el.getparent() is not None:
            el.drop_tree()
    hidden = [
        el
        for el in tree.xpath("//*[@style] | //*[@class] | //*[@id]")
        if el.get("id") in hidden_ids
        or not hidden_classes.isdisjoint(el.get("class", "").split())
        or _hidden_by_style(el)
    ]
    for el in [*tree.xpath(f"{_HIDDEN} | {_NOT_PROSE}"), *hidden]:
        if el.getparent() is not None:
            el.drop_tree()
    # Some sites wrap each heading in a <div> that extractors skip: keep just the heading.
    for heading in tree.xpath("//h1 | //h2 | //h3 | //h4 | //h5 | //h6"):
        parent = heading.getparent()
        if (
            parent is not None
            and parent.tag == "div"
            and len(parent) == 1
            and not (parent.text or "").strip()
            and parent.getparent() is not None
        ):
            parent.drop_tag()
    body = tree.find("body")
    raw = (body if body is not None else tree).text_content()
    text = " ".join(INVISIBLE_CHARS.sub("", raw).split()).lower()
    return _Signals(paywall, password, text, len(INVISIBLE_CHARS.findall(raw)))


def _json_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _not_free(data: Any) -> bool:
    if isinstance(data, dict):
        value = data.get("isAccessibleForFree")
        if value is False or (isinstance(value, str) and value.strip().lower() == "false"):
            return True
        return any(_not_free(v) for v in data.values())
    if isinstance(data, list):
        return any(_not_free(v) for v in data)
    return False


# ------------------------------------------------------------------ main content


_BlockKind = Literal["heading", "paragraph", "item", "row"]


@dataclass(frozen=True)
class _Block:
    kind: _BlockKind
    text: str
    level: int = 0  # heading level 1–6
    links: int = 0  # characters of link text in the block
    group: int | None = None  # the items of one list share a number


@dataclass(frozen=True)
class _Content:
    extractor: Extractor
    blocks: list[_Block]
    link_density: float
    short_line_ratio: float = 0.0
    title: str | None = None
    sitename: str | None = None

    @property
    def words(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)


def _content(
    extractor: Extractor,
    raw: list[_Block],
    config: ExtractConfig,
    *,
    title: str | None = None,
    sitename: str | None = None,
) -> _Content:
    """Measure links and short lines over every block, then drop the page chrome."""
    all_chars = sum(len(b.text) for b in raw)
    links = sum(b.links for b in raw)
    density = round(min(links / all_chars, 1.0), 4) if all_chars else 0.0
    return _Content(
        extractor,
        _drop_chrome(raw),
        density,
        _short_line_ratio(raw, config),
        title=title,
        sitename=sitename,
    )


def _main_content(html: str, url: str, config: ExtractConfig) -> _Content:
    if not html:
        return _Content("none", [], 0.0)
    primary = _trafilatura_content(html, url, config)
    if primary is not None and primary.words >= config.min_words:
        return primary
    fallback = _bs4_content(html, config)
    if primary is None or fallback.words > primary.words:
        return fallback if fallback.blocks else _Content("none", [], 0.0)
    return primary


def _trafilatura_content(html: str, url: str, config: ExtractConfig) -> _Content | None:
    xml = trafilatura.extract(
        html,
        url=url,
        output_format="xml",
        favor_precision=config.extraction_mode == "precision",
        favor_recall=config.extraction_mode == "recall",
        include_comments=False,
        include_tables=True,
        include_formatting=True,
        include_links=True,
        include_images=False,
        with_metadata=True,
        deduplicate=False,
    )
    if not xml:
        return None
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml.encode("utf-8"), parser)
    main = root.find("main")
    if main is None:
        return None
    return _content(
        "trafilatura",
        list(_xml_blocks(main, itertools.count())),
        config,
        title=root.get("title"),
        sitename=root.get("sitename"),
    )


def _xml_blocks(parent: Any, lists: Iterator[int]) -> Iterator[_Block]:
    for el in parent:
        tag = el.tag
        if tag == "head":
            rend = el.get("rend") or "h2"
            level = int(rend[1]) if re.fullmatch(r"h[1-6]", rend) else 2
            yield from _block("heading", _norm(_xml_text(el)), level)
        elif tag == "list":
            group = next(lists)
            for item in el.findall("item"):
                text = _norm(_xml_text(item, skip="list"))
                yield from _block("item", text, links=_link_chars(item, "list"), group=group)
                for nested in item.findall("list"):
                    yield from _xml_blocks([nested], lists)
        elif tag == "table":
            for row in el.iter("row"):
                cells = [_norm(_xml_text(c)) for c in row.findall("cell")]
                yield from _block("row", " | ".join(c for c in cells if c), links=_link_chars(row))
        elif tag in {"graphic", "lb"} or not isinstance(tag, str):
            continue
        else:
            # A <br> (<lb/>) inside a paragraph is a real line break, e.g. "About the FTC<br>The
            # FTC works...": each line becomes its own block instead of gluing the words.
            refs = [_norm(_xml_text(ref)) for ref in el.iter("ref")]
            for line in _xml_text(el, lb="\n").split("\n"):
                text = _norm(line)
                links = sum(len(ref) for ref in refs if ref and ref in text)
                yield from _block("paragraph", text, links=links)


# Block-level elements in trafilatura's XML: their text never runs into the text around them.
_XML_BLOCKS = frozenset({"p", "head", "list", "item", "quote", "table", "row", "cell", "code"})


def _xml_text(el: Any, *, lb: str = " ", skip: str | None = None) -> str:
    """Text of an XML element. <lb/> becomes `lb`, and so does every block boundary inside it;
    `skip` children are left out."""
    parts = [el.text or ""]
    for child in el:
        if child.tag == "lb":
            parts.append(lb)
        elif isinstance(child.tag, str) and child.tag != skip:
            text = _xml_text(child, lb=lb, skip=skip)
            parts.append(f"{lb}{text}{lb}" if child.tag in _XML_BLOCKS else text)
        parts.append(child.tail or "")
    return "".join(parts)


def _link_chars(el: Any, skip: str | None = None) -> int:
    total = 0
    for child in el:
        if not isinstance(child.tag, str) or child.tag == skip:
            continue
        total += len(_norm(_xml_text(child))) if child.tag == "ref" else _link_chars(child, skip)
    return total


_BS4_DROP = (
    "script", "style", "noscript", "template", "svg", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "select",
)  # fmt: skip
_BS4_BLOCKS = [
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "blockquote", "pre", "dt", "dd",
]  # fmt: skip


def _bs4_content(html: str, config: ExtractConfig) -> _Content:
    soup = BeautifulSoup(html, "lxml")
    for el in soup.find_all(_BS4_DROP):
        el.decompose()
    container = soup.find("main") or soup.find("article") or soup.find("body") or soup
    raw: list[_Block] = []
    lists: dict[int, int] = {}
    for el in container.find_all([*_BS4_BLOCKS, "div"]):
        if not isinstance(el, Tag) or _inside_block(el):
            continue
        if el.name == "div" and el.find([*_BS4_BLOCKS, "div"]) is not None:
            continue
        block = _bs4_block(el, lists)
        if block is not None:
            raw.append(block)
    return _content("bs4", raw, config)


def _bs4_block(el: Tag, lists: dict[int, int]) -> _Block | None:
    links = sum(len(_norm(a.get_text(" "))) for a in el.find_all("a"))
    if el.name == "tr":
        cells = [_norm(c.get_text(" ")) for c in el.find_all(["td", "th"])]
        row = " | ".join(c for c in cells if c)
        return _Block("row", row, links=links) if row else None
    kind: _BlockKind = "paragraph"
    level = 0
    group = None
    if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        kind, level = "heading", int(el.name[1])
    elif el.name == "li":
        kind = "item"
        group = lists.setdefault(id(el.parent), len(lists))
    text = _norm(el.get_text(" "))
    return _Block(kind, text, level, links, group) if text else None


def _inside_block(el: Tag) -> bool:
    return el.find_parent([*_BS4_BLOCKS]) is not None


def _block(
    kind: _BlockKind, text: str, level: int = 0, *, links: int = 0, group: int | None = None
) -> Iterator[_Block]:
    if text:
        yield _Block(kind, text, level, links, group)


# ------------------------------------------------------------------ page chrome

_COPYRIGHT = re.compile(r"(©|\(c\)|copyright|all rights reserved)", re.IGNORECASE)
_CALL_TO_ACTION = re.compile(
    r"^(download|view|visit|learn more|read more|see more|see all|find out more|click here"
    r"|sign up|subscribe|register|watch|explore|back to top|share)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}|\w\s*\[\s*at\s*\]\s*\w", re.IGNORECASE)
_PLACEHOLDER = re.compile(
    r"^(image|photo|picture|video|figure|icon|logo|graphic|illustration|thumbnail)s?"
    r"(\s+\d+)?:?$",
    re.IGNORECASE,
)
# "...capabilities. Learn more." -> "...capabilities."
_TRAILING_CALL = re.compile(
    r"(?:^|(?<=[.!?]))\s*(learn more|read more|see more|find out more|click here)\b"
    r"[^.!?]{0,40}[.!?]?$",
    re.IGNORECASE,
)


def _drop_chrome(blocks: list[_Block]) -> list[_Block]:
    """Drop lines that are page furniture, not content: a short line that is only a link or a
    call to action ("Download the AI RMF 1.0", "Learn more"), a contact or email line, an image
    placeholder ("Image") and a short copyright line. Headings stay; a heading left with no
    text is dropped later, when chunking."""
    kept: list[_Block] = []
    for block in blocks:
        if block.kind != "heading":
            text, words = block.text, len(block.text.split())
            if (
                _PLACEHOLDER.match(text)
                or (words < 20 and (block.links > 0.6 * len(text) or _COPYRIGHT.search(text)))
                or (words < 8 and _CALL_TO_ACTION.match(text))
                or (words < 15 and _EMAIL.search(text))
            ):
                continue
            if block.kind == "paragraph":
                trimmed = _TRAILING_CALL.sub("", text).strip()
                if not trimmed:
                    continue
                if trimmed != text:
                    block = replace(block, text=trimmed)
        kept.append(block)
    return kept


_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?)\]])")
# "...suspicious conduct.(Question about..." -> "...suspicious conduct. (Question about..."
_GLUED_BRACKET = re.compile(r"(?<=[A-Za-z]{2}[.!?])(?=[(\[])")


def _norm(text: str) -> str:
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(INVISIBLE_CHARS.sub("", text).split()))
    return _GLUED_BRACKET.sub(" ", text)


# ------------------------------------------------------------------ site boilerplate

SITE_BOILERPLATE_MIN_WORDS = 6  # shorter sentences ("Yes.", "For example:") repeat by chance
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def find_site_boilerplate(
    pages: Iterable[tuple[str | bytes, str]],
    *,
    min_pages: int = 2,
    config: ExtractConfig | None = None,
) -> dict[str, tuple[str, ...]]:
    """Sentences that repeat in the main text of at least `min_pages` pages of one host.

    `pages` are (html, url) pairs. Returns {host: hashes} to pass as
    `ExtractConfig(site_boilerplate=hashes)` when extracting that host's pages. Sentences of
    fewer than SITE_BOILERPLATE_MIN_WORDS words are never counted.
    """
    config = config or ExtractConfig()
    counts: dict[str, Counter[str]] = {}
    for html, url in pages:
        host = HttpUrl(url).host or ""
        tree = _parse(_decode(html))
        _page_signals(tree)
        cleaned = lxml_html.tostring(tree, encoding="unicode") if tree is not None else ""
        keys = {
            _sentence_key(sentence)
            for block in _main_content(cleaned, url, config).blocks
            for sentence in _SENTENCE_END.split(block.text)
            if len(sentence.split()) >= SITE_BOILERPLATE_MIN_WORDS
        }
        counts.setdefault(host, Counter()).update(keys)
    return {
        host: tuple(sorted(k for k, n in found.items() if n >= min_pages))
        for host, found in sorted(counts.items())
    }


def _sentence_key(sentence: str) -> str:
    return hashlib.sha256(" ".join(sentence.lower().split()).encode("utf-8")).hexdigest()


def _drop_site_boilerplate(blocks: list[_Block], keys: set[str]) -> list[_Block]:
    """Remove repeated sentences. A block that is mostly repeated text goes whole, and so does
    a short line right before it (its label, e.g. "About the FTC")."""
    kept: list[_Block | None] = []
    for block in blocks:
        sentences = _SENTENCE_END.split(block.text)
        repeated = sum(len(s.split()) for s in sentences if _sentence_key(s) in keys)
        if not repeated:
            kept.append(block)
        elif 2 * repeated >= len(block.text.split()):
            kept.append(None)
        else:
            rest = " ".join(s for s in sentences if _sentence_key(s) not in keys)
            kept.append(replace(block, text=rest))
    for i in range(len(kept) - 1):
        label = kept[i]
        if (
            label is not None
            and kept[i + 1] is None
            and len(label.text.split()) < SITE_BOILERPLATE_MIN_WORDS
        ):
            kept[i] = None
    return [b for b in kept if b is not None]


# ------------------------------------------------------------------ prompt injection (AI-19)


def _screen(
    blocks: list[_Block], screening: ScreeningReport, config: ExtractConfig
) -> tuple[list[_Block], ScreeningReport]:
    """Remove flagged sentences (and whole headings, items and rows) before chunking, so an
    injected page gives the same chunks as the page without the injection."""
    kept: list[_Block] = []
    findings = []
    removed = 0
    for i, block in enumerate(blocks):
        whole = block.kind != "paragraph"
        text, hits = screen_block(block.text, whole=whole)
        findings += [h.model_copy(update={"block": i}) for h in hits]
        removed += (1 if hits else 0) if whole else len({h.sentence for h in hits})
        if text:
            kept.append(block if text == block.text else replace(block, text=text))
    report = screening.model_copy(
        update={
            "findings": findings,
            "removed": removed,
            "rejected": page_rejected(findings, config.injection_max_low),
        }
    )
    return kept, report


# ------------------------------------------------------------------ quality


def _reasons(
    content: _Content,
    signals: _Signals,
    words: int,
    language: tuple[str, float] | None,
    config: ExtractConfig,
    injection: bool = False,
) -> tuple[Reason, ...]:
    found: set[Reason] = {"injection"} if injection else set()
    if words == 0:
        found.add("empty")
    if (
        signals.paywall_markup
        or (signals.password_field and words < config.password_max_words)
        or (
            words < config.paywall_phrase_max_words
            and any(p in signals.page_text for p in PAYWALL_PHRASES)
        )
    ):
        found.add("paywall_or_login")
    if words:
        text = " ".join(b.text for b in content.blocks).lower()
        if (
            content.link_density > config.max_link_density
            or content.short_line_ratio > config.max_short_line_ratio
            or (words < config.consent_max_words and any(p in text for p in CONSENT_PHRASES))
        ):
            found.add("boilerplate")
        if language is not None and (
            language[0] not in config.languages or language[1] < config.min_language_confidence
        ):
            found.add("wrong_language")
        if words < config.min_words:
            found.add("too_short")
    return tuple(r for r in REASONS if r in found)


def _short_line_ratio(blocks: list[_Block], config: ExtractConfig) -> float:
    lines = [b for b in blocks if b.kind != "heading"]
    if not lines:
        return 0.0
    short = sum(len(b.text.split()) < config.short_line_words for b in lines)
    return round(short / len(lines), 4)


# ------------------------------------------------------------------ title and units


def _title(extracted: str | None, sitename: str | None, tree: Any, url: str) -> str:
    candidates = [extracted]
    if tree is not None:
        candidates += tree.xpath("//meta[@property='og:title']/@content")
        candidates += [el.text_content() for el in tree.xpath("//title")]
        candidates += [el.text_content() for el in tree.xpath("//h1")]
    for candidate in candidates:
        title = _clean_title(_norm(candidate or ""), sitename, url)
        if title:
            return _clip(title)
    return HttpUrl(url).host or "untitled"


def _clean_title(title: str, sitename: str | None, url: str) -> str:
    # "SEO Starter Guide: The Basics | Google Search Central | ..." -> "SEO Starter Guide: ..."
    # "Retrieval-augmented generation - Wikipedia" -> "Retrieval-augmented generation"
    title = title.split(" | ")[0].strip()
    host_labels = set((HttpUrl(url).host or "").lower().split("."))
    for sep in (" - ", " – ", " — "):
        head, _, last = title.rpartition(sep)
        if (
            head
            and len(last.split()) <= 3
            and (last == sitename or last.lower().replace(" ", "") in host_labels)
        ):
            title = head.strip()
    return title


def _clip(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _units(blocks: list[_Block], sentences: list[list[nlp.Sentence]]) -> list[Unit]:
    units: list[Unit] = []
    path: list[tuple[int, str]] = []
    for block, block_sentences in zip(blocks, sentences, strict=True):
        terms = tuple(t for s in block_sentences for t in s.terms)
        if block.kind == "heading" and block.level <= 3:
            while path and path[-1][0] >= block.level:
                path.pop()
            path.append((block.level, block.text))
            units.append(Unit(block.text, _path(path), True, True, terms, kind="heading"))
        elif block.kind == "heading":
            units.append(Unit(block.text, _path(path), False, True, terms, kind="subheading"))
        elif block.kind == "paragraph" and block_sentences:
            for i, sentence in enumerate(block_sentences):
                units.append(Unit(sentence.text, _path(path), False, i == 0, sentence.terms))
        elif block.kind == "item":
            intro = units[-1] if units else None
            if (
                block.group is not None
                and intro is not None
                and intro.kind == "sentence"
                and intro.group is None
                and intro.text.endswith(":")
            ):
                units[-1] = replace(intro, group=block.group)  # "...including:" leads the list
            units.append(
                Unit(
                    f"- {block.text}",
                    _path(path),
                    False,
                    True,
                    terms,
                    kind="item",
                    group=block.group,
                )
            )
        else:
            kind: UnitKind = "row" if block.kind == "row" else "sentence"
            units.append(Unit(block.text, _path(path), False, True, terms, kind=kind))
    return units


def _path(path: list[tuple[int, str]]) -> tuple[str, ...]:
    return tuple(heading for _, heading in path)
