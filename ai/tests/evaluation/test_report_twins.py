"""AI-25 review fix 2: a live report's .md must be what its .json renders to."""

import shutil
from pathlib import Path

import pytest

from evaluation.reproduce.check import repo_root
from evaluation.reproduce.registry import AI_DIR, Entry, load_registry
from evaluation.reproduce.twins import markdown_issues

REPO = repo_root(AI_DIR)
ANALYZER = "ai/evaluation/analyzer/reports/analyzer-dev-2026-11-02"
SAFETY_ALL = "ai/evaluation/safety/reports/safety-all-2026-11-17"


def entry_for(stem: str) -> Entry:
    return next(e for e in load_registry().experiments if e.report == stem + ".json")


def copy_pair(stem: str, into: Path, markdown: str | None = None) -> Path:
    for suffix in (".json", ".md"):
        target = into / (stem + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / (stem + suffix), target)
    if markdown is not None:
        (into / (stem + ".md")).write_text(markdown, encoding="utf-8", newline="\n")
    return into


def committed_md(stem: str) -> str:
    return (REPO / (stem + ".md")).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_every_live_report_md_is_what_its_json_renders_to() -> None:
    checked = 0
    for entry in load_registry().experiments:
        if entry.kind == "live" and (REPO / entry.report).is_file():
            assert markdown_issues(entry, REPO) == [], entry.id
            checked += 1
    assert checked == 8  # E7 x3, E9 x5


def test_an_edited_number_in_the_md_fails(tmp_path: Path) -> None:
    md = committed_md(ANALYZER)
    edited = md.replace("joint", "joint (edited)", 1)
    assert edited != md
    root = copy_pair(ANALYZER, tmp_path, edited)
    assert [i.code for i in markdown_issues(entry_for(ANALYZER), root)] == ["markdown_mismatch"]


def test_an_appended_section_needs_md_addendum(tmp_path: Path) -> None:
    md = committed_md(ANALYZER) + "\n## Note (added 2026-11-26)\n\nGate PASSED after all.\n"
    root = copy_pair(ANALYZER, tmp_path, md)
    entry = entry_for(ANALYZER)
    assert [i.code for i in markdown_issues(entry, root)] == ["markdown_mismatch"]
    declared = entry.model_copy(update={"md_addendum": "a note added after the run, by hand"})
    assert markdown_issues(declared, root) == []
    # ... but an addendum may only follow the generated part, never change it
    changed = md.replace("joint", "joint (edited)", 1)
    root = copy_pair(ANALYZER, tmp_path / "2", changed)
    assert [i.code for i in markdown_issues(declared, root)] == ["markdown_mismatch"]


def test_a_declared_addendum_must_exist(tmp_path: Path) -> None:
    entry = entry_for(ANALYZER).model_copy(update={"md_addendum": "a note added by hand"})
    assert [i.code for i in markdown_issues(entry, copy_pair(ANALYZER, tmp_path))] == [
        "markdown_mismatch"
    ]


def test_the_safety_all_report_declares_its_completion_section() -> None:
    entry = entry_for(SAFETY_ALL)
    assert entry.md_addendum and markdown_issues(entry, REPO) == []
    undeclared = entry.model_copy(update={"md_addendum": None})
    assert [i.code for i in markdown_issues(undeclared, REPO)] == ["markdown_mismatch"]


def test_a_changed_renderer_falls_back_to_the_one_at_recorded_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import evaluation.reproduce.twins as twins

    monkeypatch.setattr(twins, "render_current", lambda area, data: "# a newer layout\n")
    assert markdown_issues(entry_for(ANALYZER), REPO) == []  # rendered at recorded_at instead
