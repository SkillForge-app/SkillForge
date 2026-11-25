"""The safety sets: valid, complete where written, and clearly INCOMPLETE where not."""

import re
import textwrap
from pathlib import Path

import pytest
import yaml

from core.analysis.safety import CATEGORY_DESCRIPTIONS, CONDITION_DESCRIPTIONS
from core.analysis.types import HARM_CATEGORIES, SAFETY_CONDITIONS
from core.llm import load_prompt
from evaluation.safety import data
from evaluation.safety.__main__ import main
from evaluation.safety.data import ATTACK_STYLES, SafetyEvalItem
from tests.analysis.safety_files import install_empty_copies


@pytest.fixture(autouse=True)
def _empty_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests here describe the rules, not the state of the real (filling) files."""
    install_empty_copies(tmp_path, monkeypatch)


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
    assert "INCOMPLETE" in header and "non-Claude model" in header and "reviewer" in header
    gaps = data.coverage_gaps("redteam", [])
    assert "0 of 60 items" in gaps


def write_redteam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, items: list[dict[str, object]], status: str
) -> None:
    text = data.FILES["redteam"].read_text(encoding="utf-8")
    text = text.replace("status: incomplete", f"status: {status}")
    text = text.replace(
        "requests: []", "requests:\n" + textwrap.indent(yaml.safe_dump(items), "  ")
    )
    path = tmp_path / "redteam.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setitem(data.FILES, "redteam", path)


def block_item(**fields: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "r-01",
        "text": "placeholder red-team request alpha bravo charlie",
        "expected": "block",
        "category": "fraud_scams",
        "attack": "direct",
        "origin": "generated",
        "generator": "openrouter/qwen/qwen3.8-flash",
        "reviewer": "ziad",
        "reviewed_on": "2026-11-16",
    }
    return {**item, **fields}


def codes_of(severity: str) -> set[str]:
    return {i.code for i in data.check_data() if i.severity == severity}


def test_a_complete_provenance_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_redteam(tmp_path, monkeypatch, [block_item()], "incomplete")
    assert codes_of("error") == set()
    assert "provenance" not in codes_of("warning")


@pytest.mark.parametrize(
    ("change", "status", "code", "severity"),
    [
        ({"reviewer": None}, "incomplete", "provenance", "warning"),
        ({"reviewer": None}, "draft", "provenance", "error"),
        ({"generator": None}, "draft", "provenance", "error"),
        ({"origin": "adapted", "generator": None}, "draft", "provenance", "error"),
        (
            {"generator": "openrouter/anthropic/claude-sonnet-5.5"},
            "incomplete",
            "claude_generator",
            "error",
        ),
        ({"category": "child_safety"}, "incomplete", "child_safety", "error"),
    ],
)
def test_provenance_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, object],
    status: str,
    code: str,
    severity: str,
) -> None:
    item = {k: v for k, v in block_item(**change).items() if v is not None}
    write_redteam(tmp_path, monkeypatch, [item], status)
    assert code in codes_of(severity)


def test_a_near_copy_of_a_benign_item_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benign = data.load_set("benign")[0]
    words = benign.text.split()
    near = " ".join([*words[:-1], "please"])  # one word changed: the same request
    assert data.similarity(near, benign.text) >= data.NEAR_DUPLICATE
    write_redteam(tmp_path, monkeypatch, [block_item(text=near)], "incomplete")
    [issue] = [i for i in data.check_data() if i.code == "near_duplicate"]
    assert issue.severity == "error" and f"benign:{benign.id}" in issue.message
    assert "can't be both block and allow" in issue.message


def test_different_requests_are_not_near_duplicates() -> None:
    assert data.similarity("a skill for phishing emails", "a skill for garden planning") < 0.5
    assert data.is_claude("anthropic/claude-sonnet-5-5") and data.is_claude("x/Claude-3")
    assert not data.is_claude("openrouter/qwen/qwen3.8-flash")


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
    assert len(items) == 160 and all(i.expected == "allow" for i in items)


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
