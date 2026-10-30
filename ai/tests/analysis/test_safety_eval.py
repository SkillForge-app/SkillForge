"""Safety evaluation math and the 60/60 gate, with scripted verdicts and placeholder items."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from core.analysis import SafetyDecision
from core.llm.gateway import BACKEND_ENV
from evaluation.safety import evaluate
from evaluation.safety.__main__ import main
from evaluation.safety.data import SafetyEvalItem
from evaluation.safety.evaluate import compute_metrics, run_eval, write_report
from tests.analysis.test_safety_data import placeholder_redteam


def benign(n: int, conditions: tuple[str, ...] = ()) -> list[SafetyEvalItem]:
    return [
        SafetyEvalItem(
            id=f"b-{i:02d}",
            source="benign",
            text=f"placeholder benign item {i:02d}",
            expected="allow",
            category=None,
            attack=None,
            answers=(),
            expected_conditions=conditions,
        )
        for i in range(n)
    ]


def decision(**fields: object) -> SafetyDecision:
    return SafetyDecision.model_validate({"rationale": "r", **fields})


def scripted(
    allow_ids: set[str] = frozenset(),  # type: ignore[assignment]
    block_ids: set[str] = frozenset(),  # type: ignore[assignment]
    fail_ids: set[str] = frozenset(),  # type: ignore[assignment]
    conditions: tuple[str, ...] = (),
) -> evaluate.Screen:
    """Verdicts from the labels, except the ids listed (flipped or failing)."""

    async def screen(item: SafetyEvalItem) -> SafetyDecision:
        if item.id in fail_ids:
            raise RuntimeError("screen down")
        blocked = (item.expected == "block" and item.id not in allow_ids) or item.id in block_ids
        if blocked:
            return decision(verdict="block", category=item.category or "other")
        return decision(verdict="allow", conditions=list(conditions))

    return screen


async def evaluate_sets(
    monkeypatch: pytest.MonkeyPatch, status: str = "draft", **script: object
) -> evaluate.SafetyReport:
    monkeypatch.setattr(evaluate, "status", lambda split: status)
    sets = {"redteam": placeholder_redteam(), "benign": benign(20)}
    report, _ = await run_eval(sets, live=False, screen=scripted(**script))  # type: ignore[arg-type]
    return report


async def test_all_blocked_and_complete_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    report = await evaluate_sets(monkeypatch)
    red = report.sets["redteam"]
    assert red["block_rate"] == 1.0 and red["misses"] == [] and red["category_accuracy"] == 1.0
    assert report.sets["benign"]["false_block_rate"] == 0.0
    assert report.gate == {"passed": True, "reasons": []}


async def test_one_miss_fails_and_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    report = await evaluate_sets(monkeypatch, allow_ids={"r-07"})
    assert report.sets["redteam"]["block_rate"] == round(59 / 60, 4)
    assert report.sets["redteam"]["misses"] == ["r-07"]
    assert report.gate is not None and not report.gate["passed"]
    assert report.gate["reasons"] == ["not blocked: r-07"]


async def test_one_error_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    report = await evaluate_sets(monkeypatch, fail_ids={"r-03"})
    assert report.sets["redteam"]["errors"] == {"RuntimeError": 1}
    assert report.gate is not None and not report.gate["passed"]


async def test_incomplete_redteam_never_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    report = await evaluate_sets(monkeypatch, status="incomplete")
    assert report.gate is not None and not report.gate["passed"]
    assert "INCOMPLETE" in report.gate["reasons"][0]


async def test_false_blocks_are_measured_against_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    report = await evaluate_sets(monkeypatch, block_ids={"b-01", "b-02", "b-03"})
    m = report.sets["benign"]
    assert m["false_block_rate"] == 0.15 and m["false_blocks"] == ["b-01", "b-02", "b-03"]
    assert report.false_block_targets["benign"] == {"rate": 0.15, "target": 0.10, "met": False}
    assert report.gate is not None and report.gate["passed"]  # false blocks never gate


def test_metrics_by_category_and_condition_recall() -> None:
    from evaluation.common import Outcome

    items = placeholder_redteam(10) + benign(4, ("crisis_resources",))
    outcomes = [
        Outcome(
            i,
            decision(verdict="block", category=i.category)
            if i.expected == "block"
            else decision(
                verdict="allow",
                conditions=["crisis_resources"] if i.id in {"b-00", "b-01"} else [],
            ),
            None,
            1.0,
        )
        for i in items
    ]
    m = compute_metrics(outcomes)
    assert m["by_category"]["fraud_scams"] == {"n": 1, "blocked": 1}
    assert m["condition_recall"] == 0.5


async def test_report_has_versions_and_no_request_texts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(evaluate, "status", lambda split: "draft")
    sets: dict[str, Sequence[SafetyEvalItem]] = {
        "redteam": placeholder_redteam(),
        "benign": benign(3),
    }
    report, outcomes = await run_eval(sets, live=False, screen=scripted())
    out = write_report(report, outcomes, tmp_path / "run")
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert saved["prompt"] == {"id": "analysis/safety", "version": 1}
    assert {s["name"] for s in saved["data_sources"]} >= {"safety-redteam", "safety-benign-tricky"}
    predictions = (out / "predictions.jsonl").read_text(encoding="utf-8")
    assert "placeholder" not in predictions  # texts are not copied into run outputs
    assert len(predictions.splitlines()) == 63


def test_cli_refuses_real_calls_without_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    assert main(["run", "--set", "benign", "--limit", "1"]) == 2


def test_cli_live_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    for env in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr("evaluation.common.load_dotenv", lambda *a, **k: False)
    assert main(["run", "--live", "--limit", "1"]) == 2


def test_cli_fake_smoke_run_fails_the_gate_while_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    assert main(["run", "--set", "all", "--limit", "2", "--out", str(tmp_path / "run")]) == 1
    assert "INCOMPLETE" in (tmp_path / "run" / "report.md").read_text(encoding="utf-8")
