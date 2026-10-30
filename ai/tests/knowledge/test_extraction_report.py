"""The AI-10 quality report tool (evaluation/extraction), on a small slice of the pages."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from pydantic import HttpUrl

from core.knowledge import Chunk
from core.knowledge.chunking import content_hash
from evaluation.extraction.__main__ import main
from evaluation.extraction.data import PageLabel, load_pages
from evaluation.extraction.report import (
    GATES,
    evaluate,
    render_markdown,
    spread_sample,
    write_report,
)

SLICE = [p for p in load_pages() if p.file in {"nist-ai-rmf.html", "synthetic-stub.html"}]


def test_labels_are_complete_and_consistent() -> None:
    pages = load_pages()
    assert len(pages) >= 18
    assert sum(not p.synthetic for p in pages) >= 8
    assert {r for p in pages for r in p.expected} == {
        "empty", "paywall_or_login", "boilerplate", "wrong_language", "too_short",
    }  # fmt: skip
    assert all(p.must_contain for p in pages if not p.expected)
    assert all(not p.synthetic or ".example" in str(p.url) for p in pages)


def test_a_label_with_reasons_out_of_order_is_rejected() -> None:
    base = SLICE[1].model_dump(mode="json")
    with pytest.raises(ValueError):
        PageLabel.model_validate({**base, "expected": ["too_short", "empty"]})


def test_report_on_a_slice_passes_and_samples_deterministically() -> None:
    report = evaluate(SLICE, sample_size=2, seed=3, today=date(2026, 10, 25))
    assert report.gates_passed, report.checks
    assert set(report.checks) == set(GATES) and report.leaks == 0
    again = evaluate(SLICE, sample_size=2, seed=3, today=date(2026, 10, 25))
    assert [s.chunk_id for s in report.sample] == [s.chunk_id for s in again.sample]
    assert {s.file for s in report.sample} == {"nist-ai-rmf.html"}  # rejected pages: no chunks


def test_a_wrong_label_fails_the_gate() -> None:
    wrong = SLICE[1].model_copy(update={"expected": []})
    report = evaluate([SLICE[0], wrong], sample_size=1)
    assert report.checks["verdicts"] == 0.5 and not report.gates_passed


def test_markdown_has_the_review_sheet(tmp_path: Path) -> None:
    report = evaluate(SLICE, sample_size=2, today=date(2026, 10, 25))
    md = render_markdown(report)
    assert "Human review: PENDING" in md and "Reviewer: ________" in md
    assert f"(seed {report.seed})" in md
    assert md.count("- [ ] stands alone") == 2
    md_path, json_path = write_report(report, tmp_path)
    assert md_path.name == "extraction-2026-10-25.md" and json_path.exists()


def test_a_report_never_overwrites_an_earlier_one(tmp_path: Path) -> None:
    report = evaluate(SLICE, sample_size=2, today=date(2026, 10, 25))
    first_md, first_json = write_report(report, tmp_path)
    first_md.write_text("reviewed by a person", encoding="utf-8")  # e.g. a filled-in sheet
    second_md, second_json = write_report(report, tmp_path)
    third_md, _ = write_report(report, tmp_path)
    assert first_md.read_text(encoding="utf-8") == "reviewed by a person"
    assert (second_md.name, second_json.name) == (
        "extraction-2026-10-25-2.md",
        "extraction-2026-10-25-2.json",
    )
    assert third_md.name == "extraction-2026-10-25-3.md"
    # A stray .json alone also blocks its name, so the pair always matches.
    (tmp_path / "extraction-2026-10-25-4.json").write_text("{}", encoding="utf-8")
    assert write_report(report, tmp_path)[0].name == "extraction-2026-10-25-5.md"


def chunk(n: int) -> Chunk:
    text = f"Chunk number {n} says one thing clearly."
    return Chunk(
        chunk_id=f"example.org-0000000{n % 10}-{n:08d}",
        source_url=HttpUrl("https://example.org/"),
        title="Example",
        retrieved=date(2026, 10, 25),
        text=text,
        section=[],
        position=n,
        word_count=len(text.split()),
        concepts=[],
        content_hash=content_hash(text),
    )


def test_the_sample_is_spread_evenly_over_pages() -> None:
    chunks = [("big.html", chunk(i)) for i in range(100)]
    chunks += [("small.html", chunk(100)), ("mid.html", chunk(101)), ("mid.html", chunk(102))]
    picked = spread_sample(chunks, 7, seed=1)
    files = Counter(file for file, _ in picked)
    assert files == {"big.html": 4, "mid.html": 2, "small.html": 1}
    assert spread_sample(chunks, 7, seed=1) == picked  # same seed, same sample
    assert len({c.chunk_id for _, c in picked}) == 7


def test_site_boilerplate_switch_decides_whether_ftc_template_text_leaks() -> None:
    ftc = [p for p in load_pages() if p.file in {"ftc-can-spam.html", "ftc-endorsement-faq.html"}]
    on = evaluate(ftc, sample_size=2)
    off = evaluate(ftc, sample_size=2, site_boilerplate=False)
    assert on.site_boilerplate == {"www.ftc.gov": 9} and on.leaks == 0 and on.gates_passed
    assert off.site_boilerplate == {} and off.leaks > 0 and not off.gates_passed
    assert "Site boilerplate removal: on" in render_markdown(on)


def test_cli_check_data(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-data"]) == 0
    assert "OK" in capsys.readouterr().out
