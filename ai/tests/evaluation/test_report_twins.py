"""AI-25 review fix 2: a live report's .md must be what its .json renders to."""

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from evaluation.analyzer.evaluate import EvalReport, render_markdown
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


def today_pair(into: Path, markdown: str | None = None) -> tuple[Path, str]:
    """ANALYZER's report as today's `analyzer run --live` would write it, under `into` (no git
    history there, so only today's renderer can match). The committed 2 Nov .json predates fields
    EvalReport has gained since (validity_rule, ...): they get their defaults. Returns the root
    and the generated .md; `markdown` replaces the .md written."""
    data: dict[str, Any] = json.loads((REPO / (ANALYZER + ".json")).read_text(encoding="utf-8"))
    fields: dict[str, Any] = {}
    for f in dataclasses.fields(EvalReport):
        if f.name in data:
            fields[f.name] = data[f.name]
        elif f.default is not dataclasses.MISSING:
            fields[f.name] = f.default
        else:
            assert f.default_factory is not dataclasses.MISSING, f.name
            fields[f.name] = f.default_factory()
    generated = render_markdown(EvalReport(**fields))
    target = into / ANALYZER
    target.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps({**fields, "run": data["run"]}, indent=2) + "\n"
    target.with_suffix(".json").write_text(json_text, encoding="utf-8", newline="\n")
    md = generated if markdown is None else markdown
    target.with_suffix(".md").write_text(md, encoding="utf-8", newline="\n")
    return into, generated


def test_every_live_report_md_is_what_its_json_renders_to() -> None:
    checked = 0
    for entry in load_registry().experiments:
        if entry.kind == "live" and (REPO / entry.report).is_file():
            assert markdown_issues(entry, REPO) == [], entry.id
            checked += 1
    assert checked == 10  # E7 x3, E9 x5, E12 x2


def test_the_synthetic_pair_renders_with_todays_renderer(tmp_path: Path) -> None:
    root, _ = today_pair(tmp_path)
    assert markdown_issues(entry_for(ANALYZER), root) == []


def test_an_edited_number_in_the_md_fails(tmp_path: Path) -> None:
    _, md = today_pair(tmp_path / "probe")
    edited = md.replace("joint", "joint (edited)", 1)
    assert edited != md
    root, _ = today_pair(tmp_path, edited)
    assert [i.code for i in markdown_issues(entry_for(ANALYZER), root)] == ["markdown_mismatch"]


def test_an_appended_section_needs_md_addendum(tmp_path: Path) -> None:
    _, generated = today_pair(tmp_path / "probe")
    md = generated + "\n## Note (added 2026-11-26)\n\nGate PASSED after all.\n"
    root, _ = today_pair(tmp_path / "1", md)
    entry = entry_for(ANALYZER)
    assert [i.code for i in markdown_issues(entry, root)] == ["markdown_mismatch"]
    declared = entry.model_copy(update={"md_addendum": "a note added after the run, by hand"})
    assert markdown_issues(declared, root) == []
    # ... but an addendum may only follow the generated part, never change it
    changed = md.replace("joint", "joint (edited)", 1)
    root, _ = today_pair(tmp_path / "2", changed)
    assert [i.code for i in markdown_issues(declared, root)] == ["markdown_mismatch"]


def test_a_declared_addendum_must_exist(tmp_path: Path) -> None:
    entry = entry_for(ANALYZER).model_copy(update={"md_addendum": "a note added by hand"})
    root, _ = today_pair(tmp_path)
    assert [i.code for i in markdown_issues(entry, root)] == ["markdown_mismatch"]


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
