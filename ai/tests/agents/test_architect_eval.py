"""Skill Architect evaluation: the 103 test requests, the valid-rate math, the gate, the CLI."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from core.agents import ArchitectResult
from core.llm.gateway import BACKEND_ENV
from core.spec import HIGH_RISK_AREAS, load_spec
from evaluation.architect.__main__ import main
from evaluation.architect.data import GATE_SIZE, ArchitectItem, load_items
from evaluation.architect.evaluate import compute_metrics, gate_verdict, run_eval, write_report
from evaluation.common import AI_ROOT, Outcome

SPEC = load_spec(AI_ROOT / "examples" / "skillspec" / "ai-engineer.yaml")


def test_103_screened_test_requests() -> None:
    items = load_items("all")
    assert len(items) == GATE_SIZE == 103
    assert sum(i.source == "example" for i in items) == 3
    for item in items:
        a = item.analyzed
        assert a.safety is not None and not a.needs_clarification
        assert len(a.summary) <= 200
        if a.domain_area in HIGH_RISK_AREAS:
            assert "professional_disclaimer" in a.safety.conditions


def outcomes(valid: int, total: int = 103) -> list[Outcome[ArchitectItem, ArchitectResult]]:
    items = load_items("all")[:total]
    return [
        Outcome(
            item,
            ArchitectResult(ok=n < valid, spec=SPEC if n < valid else None, attempts=1, issues=()),
            None,
            1.0,
        )
        for n, item in enumerate(items)
    ]


@pytest.mark.parametrize(("valid", "passed"), [(103, True), (93, True), (92, False)])
def test_gate_at_90_percent(valid: int, passed: bool) -> None:
    metrics = compute_metrics(outcomes(valid))
    assert metrics["valid"] == valid
    assert gate_verdict(metrics)["passed"] is passed


def test_gate_needs_all_103() -> None:
    verdict = gate_verdict(compute_metrics(outcomes(10, total=10)))
    assert not verdict["passed"] and "exactly 103" in verdict["reasons"][0]


def test_fake_runs_never_count() -> None:
    verdict = gate_verdict(compute_metrics(outcomes(103)), live=False)
    assert verdict["passed"] and verdict["counts"] is False


async def test_report_writes_specs(tmp_path: Path) -> None:
    async def build(item: ArchitectItem) -> ArchitectResult:
        return ArchitectResult(ok=True, spec=SPEC, attempts=1, issues=())

    sets: dict[str, Sequence[ArchitectItem]] = {"examples": load_items("examples")}
    report, results = await run_eval(sets, live=False, build=build)
    out = write_report(report, results, tmp_path / "run")
    assert len(list((out / "specs").glob("*.json"))) == 3
    assert "does NOT count" not in (out / "report.md").read_text(encoding="utf-8")  # no gate here
    assert report.sets["examples"]["valid_rate"] == 1.0


def test_cli_check_data_and_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["check-data"]) == 0
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    assert main(["run", "--set", "examples"]) == 2


def test_cli_fake_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    assert main(["run", "--set", "examples", "--out", str(tmp_path / "run")]) == 0
    assert len(list((tmp_path / "run" / "specs").glob("*.json"))) == 3
