"""The AI-10 chunk-quality report: automatic checks over the labelled pages, plus a seeded
sample of chunks, spread evenly across the pages, for a person to review. AI-10 is done when
the automatic gates pass and the reviewer marks at least 18 of 20 sampled chunks as good.

Site boilerplate removal is on by default here, the way DE-05 would run it: sentences repeated
on several pages of one host (find_site_boilerplate) are removed from that host's pages.
"""

import json
import random
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from statistics import median

from core.knowledge.extract import (
    Chunk,
    ExtractConfig,
    ExtractedPage,
    extract_page,
    find_site_boilerplate,
)
from evaluation.common import AI_ROOT, write_new_files
from evaluation.extraction.data import PageLabel, load_pages

REPORTS_DIR = AI_ROOT / "evaluation" / "extraction" / "reports"
SAMPLE_SIZE = 20
SAMPLE_PASS = 18
# Automatic gates: (name, minimum share). "leaks" is a count that must be 0.
GATES = {
    "verdicts": 1.0,
    "titles": 1.0,
    "languages": 1.0,
    "facts": 0.95,
    "chunk_size": 0.90,
    "valid_passages": 1.0,
    "clean_ends": 0.95,
}
_CLEAN_END = re.compile(r"""[.!?…:;)\]"'”’]$""")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def ends_cleanly(chunk: Chunk) -> bool:
    """Ends at a sentence end, or with a whole list item or table row (never a heading)."""
    last = chunk.text.splitlines()[-1]
    return bool(_CLEAN_END.search(last)) or last.startswith("- ") or " | " in last


@dataclass
class PageResult:
    file: str
    expected: list[str]
    reasons: list[str]
    extractor: str
    title: str
    title_ok: bool | None
    language: str | None
    language_ok: bool | None
    words: int
    link_density: float
    chunks: int
    chunk_words_median: float | None
    chunk_words_max: int | None
    concepts: list[str]
    facts_missing: list[str]
    facts_total: int
    leaks: list[str]

    @property
    def verdict_ok(self) -> bool:
        return self.reasons == self.expected


@dataclass
class SampleChunk:
    file: str
    chunk_id: str
    section: list[str]
    words: int
    concepts: list[str]
    text: str


@dataclass
class Report:
    date: str
    config: dict[str, object]
    site_boilerplate: dict[str, int]  # host -> repeated sentences removed; {} when off
    seed: int  # of the review sample: the same seed and pages give the same sample
    pages: list[PageResult]
    checks: dict[str, float]
    leaks: int
    gates_passed: bool
    sample: list[SampleChunk] = field(default_factory=list)


def evaluate(
    labels: list[PageLabel] | None = None,
    *,
    config: ExtractConfig | None = None,
    sample_size: int = SAMPLE_SIZE,
    seed: int = 7,
    today: date | None = None,
    site_boilerplate: bool = True,
) -> Report:
    labels = load_pages() if labels is None else labels
    config = config or ExtractConfig()
    configs = page_configs(labels, config, site_boilerplate=site_boilerplate)
    results: list[PageResult] = []
    chunks: list[tuple[str, Chunk]] = []
    for label in labels:
        page = extract_page(
            label.path.read_bytes(),
            url=str(label.url),
            retrieved=label.retrieved,
            config=configs[label.file],
        )
        results.append(_page_result(label, page))
        chunks += [(label.file, c) for c in page.chunks]

    all_chunks = [c for _, c in chunks]
    settings = config.chunking
    checks = {
        "verdicts": _share(r.verdict_ok for r in results),
        "titles": _share(r.title_ok for r in results if r.title_ok is not None),
        "languages": _share(r.language_ok for r in results if r.language_ok is not None),
        "facts": _ratio(
            sum(r.facts_total - len(r.facts_missing) for r in results),
            sum(r.facts_total for r in results),
        ),
        "chunk_size": _share(
            settings.min_words <= c.word_count <= settings.max_words for c in all_chunks
        ),
        "valid_passages": _share(
            len(c.text) <= settings.max_chars and c.to_passage() is not None for c in all_chunks
        ),
        "clean_ends": _share(ends_cleanly(c) for c in all_chunks),
    }
    leaks = sum(len(r.leaks) for r in results)
    passed = leaks == 0 and all(checks[name] >= floor for name, floor in GATES.items())
    picked = spread_sample(chunks, sample_size, seed)
    removed = {
        str(label.url.host): len(configs[label.file].site_boilerplate)
        for label in labels
        if configs[label.file].site_boilerplate
    }
    return Report(
        date=(today or date.today()).isoformat(),
        config=config.model_dump(mode="json"),
        site_boilerplate=dict(sorted(removed.items())),
        seed=seed,
        pages=results,
        checks=checks,
        leaks=leaks,
        gates_passed=passed,
        sample=[
            SampleChunk(file, c.chunk_id, c.section, c.word_count, c.concepts, c.text)
            for file, c in picked
        ],
    )


def page_configs(
    labels: list[PageLabel], config: ExtractConfig, *, site_boilerplate: bool = True
) -> dict[str, ExtractConfig]:
    """The config for each page: `config`, plus its host's repeated sentences when switched on."""
    if not site_boilerplate:
        return {label.file: config for label in labels}
    found = find_site_boilerplate(
        ((label.path.read_bytes(), str(label.url)) for label in labels), config=config
    )
    return {
        label.file: config.model_copy(
            update={"site_boilerplate": found.get(str(label.url.host), ())}
        )
        for label in labels
    }


def spread_sample(chunks: list[tuple[str, Chunk]], size: int, seed: int) -> list[tuple[str, Chunk]]:
    """Pick chunks page by page in turn (pages and chunks shuffled with `seed`), so a page with
    many chunks cannot fill the sample: every page with chunks gets one before any gets two."""
    rng = random.Random(seed)
    by_page: dict[str, list[Chunk]] = {}
    for file, chunk in chunks:
        by_page.setdefault(file, []).append(chunk)
    for page_chunks in by_page.values():
        rng.shuffle(page_chunks)
    order = sorted(by_page)
    rng.shuffle(order)
    picked: list[tuple[str, Chunk]] = []
    while len(picked) < size and any(by_page.values()):
        for file in order:
            if by_page[file] and len(picked) < size:
                picked.append((file, by_page[file].pop()))
    return picked


def _page_result(label: PageLabel, page: ExtractedPage) -> PageResult:
    text = _norm("\n".join(c.text for c in page.chunks))
    sizes = [c.word_count for c in page.chunks]
    return PageResult(
        file=label.file,
        expected=list(label.expected),
        reasons=list(page.quality.reasons),
        extractor=page.extractor,
        title=page.title,
        title_ok=None if label.title is None else page.title == label.title,
        language=page.quality.language,
        language_ok=None if label.language is None else page.quality.language == label.language,
        words=page.quality.word_count,
        link_density=page.quality.link_density,
        chunks=len(page.chunks),
        chunk_words_median=median(sizes) if sizes else None,
        chunk_words_max=max(sizes) if sizes else None,
        concepts=page.concepts[:5],
        facts_missing=[f for f in label.must_contain if _norm(f) not in text],
        facts_total=len(label.must_contain),
        leaks=[s for s in label.must_not_contain if _norm(s) in text],
    )


def _share(values: Iterable[bool | None]) -> float:
    items = list(values)
    return _ratio(sum(bool(v) for v in items), len(items))


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 1.0


# ------------------------------------------------------------------ output


def write_report(report: Report, out_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    """Write the .md and .json under a new name: an existing (reviewed) report is never
    overwritten; a second run on the same day gets extraction-<date>-2, and so on."""
    data = asdict(report)
    for page, result in zip(data["pages"], report.pages, strict=True):
        page["verdict_ok"] = result.verdict_ok
    md_path, json_path = write_new_files(
        out_dir,
        f"extraction-{report.date}",
        {
            ".md": render_markdown(report),
            ".json": json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        },
    )
    return md_path, json_path


def render_markdown(report: Report) -> str:
    chunking = report.config["chunking"]
    lines = [
        f"# AI-10 chunk quality report ({report.date})",
        "",
        f"**Automatic gates: {'PASS' if report.gates_passed else 'FAIL'}.** "
        f"**Human review: PENDING** until a person fills in the sample below "
        f"(AI-10 is done at {SAMPLE_PASS} or more good chunks out of {len(report.sample)}).",
        "",
        f"Chunk settings: {json.dumps(chunking)}. "
        f"Extraction mode: {report.config['extraction_mode']}. "
        "Site boilerplate removal: "
        + (
            "on (repeated sentences removed: "
            + ", ".join(f"{host} {n}" for host, n in report.site_boilerplate.items())
            + ")."
            if report.site_boilerplate
            else "off."
        ),
        "",
        "## Automatic checks",
        "",
        "| Check | Result | Gate |",
        "|---|---|---|",
    ]
    for name, floor in GATES.items():
        value = report.checks[name]
        mark = "✅" if value >= floor else "❌"
        lines.append(f"| {name} | {value:.1%} {mark} | ≥ {floor:.0%} |")
    lines.append(f"| leaks | {report.leaks} {'✅' if report.leaks == 0 else '❌'} | 0 |")
    lines += [
        "",
        "## Pages",
        "",
        "| Page | Expected | Got | Extractor | Words | Links | Chunks | Median / max words "
        "| Missing facts | Leaks | Top concepts |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report.pages:
        mark = "✅" if r.verdict_ok else "❌"
        sizes = f"{r.chunk_words_median:g} / {r.chunk_words_max}" if r.chunk_words_max else "–"
        lines.append(
            f"| {r.file} | {', '.join(r.expected) or 'ok'} | {', '.join(r.reasons) or 'ok'} {mark} "
            f"| {r.extractor} | {r.words} | {r.link_density:.2f} | {r.chunks} | {sizes} "
            f"| {', '.join(r.facts_missing) or '–'} | {', '.join(r.leaks) or '–'} "
            f"| {', '.join(r.concepts) or '–'} |"
        )
    lines += [
        "",
        f"## Human review: {len(report.sample)} sampled chunks",
        "",
        f"The sample is spread evenly over the {len({s.file for s in report.sample})} pages "
        "that have chunks: each page gets one chunk before any page gets a second "
        f"(seed {report.seed}).",
        "",
        "For each chunk, tick every box that holds, then mark it good only if all four do.",
        "- **Stands alone:** makes sense without the chunks around it.",
        "- **On topic:** about one subject, the one its section names.",
        "- **No boilerplate:** no menus, cookie text, footers or ads.",
        "- **Readable:** no broken sentences, glued words or stray markup.",
        "",
        "Reviewer: ________  Date: ________  Good chunks: ____ / "
        f"{len(report.sample)} (pass at {SAMPLE_PASS})",
        "",
    ]
    for i, item in enumerate(report.sample, 1):
        section = " › ".join(item.section) or "(no heading)"
        quoted = "\n".join(f"> {line}" for line in item.text.splitlines())
        lines += [
            f"### {i}. `{item.chunk_id}` ({item.file}, {item.words} words)",
            "",
            f"Section: {section}  ",
            f"Concepts: {', '.join(item.concepts) or '–'}",
            "",
            quoted,
            "",
            "- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  "
            "→ **good / bad**",
            "",
        ]
    return "\n".join(lines)
