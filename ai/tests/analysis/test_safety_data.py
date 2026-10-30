"""The safety sets: valid, complete where written, and clearly INCOMPLETE where not."""

import re
from pathlib import Path

import pytest

from core.analysis.safety import CATEGORY_DESCRIPTIONS, CONDITION_DESCRIPTIONS
from core.analysis.types import HARM_CATEGORIES, SAFETY_CONDITIONS
from core.llm import load_prompt
from evaluation.safety import data
from evaluation.safety.__main__ import main
from evaluation.safety.data import ATTACK_STYLES, SafetyEvalItem


def placeholder_redteam(n: int = 60) -> list[SafetyEvalItem]:
    """A synthetic, complete red-team set with neutral text, to test the coverage rules."""
    categories = [c for c in HARM_CATEGORIES if c != "other"]
    return [
        SafetyEvalItem(
            id=f"r-{i:02d}",
            source="redteam",
            text=f"placeholder red-team item {i:02d}",
            expected="block",
            category=categories[i % len(categories)],
            attack=ATTACK_STYLES[i % len(ATTACK_STYLES)],
            answers=(("q", "a"),) if ATTACK_STYLES[i % len(ATTACK_STYLES)] == "two_turn" else (),
            expected_conditions=(),
        )
        for i in range(n)
    ]


def test_no_errors_only_incomplete_warnings() -> None:
    issues = data.check_data()
    assert [str(i) for i in issues if i.severity == "error"] == []
    assert {i.code for i in issues} <= {"incomplete"}


def test_redteam_is_an_empty_template_marked_incomplete() -> None:
    assert data.status("redteam") == "incomplete"
    assert data.load_set("redteam") == []
    header = data.FILES["redteam"].read_text(encoding="utf-8")
    assert "INCOMPLETE" in header and "Do NOT generate them with an AI assistant" in header
    gaps = data.coverage_gaps("redteam", [])
    assert "0 of 60 items" in gaps


def test_dev_block_half_is_incomplete() -> None:
    assert data.status("dev") == "incomplete"
    assert data.coverage_gaps("dev", data.load_set("dev")) == ["block items: 0 of 10"]


def test_benign_set_is_complete() -> None:
    items = data.load_set("benign")
    assert data.coverage_gaps("benign", items) == []
    assert len(items) == 60 and all(i.expected == "allow" for i in items)
    assert sum(bool(data.ARABIC.search(i.text)) for i in items) >= 5


def test_normal_set_reuses_the_analyzer_sets() -> None:
    items = data.load_set("normal")
    assert len(items) == 130 and all(i.expected == "allow" for i in items)


def test_coverage_rules_accept_a_complete_redteam_set() -> None:
    assert data.coverage_gaps("redteam", placeholder_redteam()) == []


@pytest.mark.parametrize(
    ("items", "gap"),
    [
        (placeholder_redteam(59), "59 of 60 items"),
        (
            [i for i in placeholder_redteam(70) if i.category != "weapons"][:60],
            "category weapons: 0 of 5",
        ),
    ],
)
def test_coverage_rules_find_gaps(items: list[SafetyEvalItem], gap: str) -> None:
    assert gap in data.coverage_gaps("redteam", items)


def test_two_turn_items_need_answers() -> None:
    items = [
        SafetyEvalItem(**{**i.__dict__, "answers": ()}) if i.attack == "two_turn" else i
        for i in placeholder_redteam()
    ]
    assert "two_turn items need answers" in data.coverage_gaps("redteam", items)


def test_gaps_become_errors_once_status_is_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = (
        data.FILES["redteam"]
        .read_text(encoding="utf-8")
        .replace("status: incomplete", "status: draft")
    )
    draft = tmp_path / "redteam.yaml"
    draft.write_text(text, encoding="utf-8")
    monkeypatch.setitem(data.FILES, "redteam", draft)
    errors = [i for i in data.check_data() if i.severity == "error"]
    assert errors and all(i.code == "coverage" for i in errors)


def test_few_shot_examples_come_from_the_dev_allow_half() -> None:
    inputs = {
        "request_text": "x",
        "answers": [],
        "categories": [
            {"name": n, "description": CATEGORY_DESCRIPTIONS[n]} for n in HARM_CATEGORIES
        ],
        "conditions": [
            {"name": n, "description": CONDITION_DESCRIPTIONS[n]} for n in SAFETY_CONDITIONS
        ],
    }
    system = load_prompt("analysis/safety").render(inputs)[0]["content"]
    shots = re.findall(r'Request: "(.*?)"\n\{', system, flags=re.DOTALL)
    assert len(shots) == 3

    def norm(text: str) -> str:
        return " ".join(text.lower().split())

    dev_allow = {norm(i.text) for i in data.load_set("dev") if i.expected == "allow"}
    measured = {norm(i.text) for name in ("benign", "normal") for i in data.load_set(name)}
    for shot in shots:
        assert norm(shot) in dev_allow
        assert norm(shot) not in measured


def test_cli_check_data_reports_incomplete(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-data"]) == 0
    out = capsys.readouterr().out
    assert "redteam.yaml: 0 items, status incomplete  <-- INCOMPLETE" in out
    assert "OK, but INCOMPLETE" in out
