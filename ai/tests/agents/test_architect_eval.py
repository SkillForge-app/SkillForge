"""Skill Architect evaluation: the 103 test requests (AI-07), the seed set (AI-12), the math,
the verdicts and the CLI."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from core.agents import ArchitectResult
from core.knowledge import FakeRetriever, Passage
from core.llm.gateway import BACKEND_ENV
from core.spec import HIGH_RISK_AREAS, SkillSpec, load_spec
from core.spec.models import Knowledge
from evaluation.architect.__main__ import main
from evaluation.architect.data import GATE_SIZE, SEED_SET_SIZE, ArchitectItem, load_items
from evaluation.architect.evaluate import (
    compute_metrics,
    gate_verdict,
    run_eval,
    seed_verdict,
    write_report,
)
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
    files = write_report(
        report,
        results,
        label="examples",
        reports_dir=tmp_path / "reports",
        run_dir=tmp_path / "run",
    )
    assert files.md.name == f"architect-examples-{report.created[:10]}.md"
    assert len(list((tmp_path / "run" / "specs").glob("*.json"))) == 3  # specs stay out of Git
    assert not list((tmp_path / "reports").glob("**/specs"))
    assert "does NOT count" not in files.md.read_text(encoding="utf-8")  # no gate here
    assert report.sets["examples"]["valid_rate"] == 1.0


def test_cli_check_data_and_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["check-data"]) == 0
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    assert main(["run", "--set", "examples"]) == 2


def test_cli_fake_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    monkeypatch.setattr("evaluation.architect.__main__.REPORTS_DIR", tmp_path / "tracked")
    assert main(["run", "--set", "examples", "--runs", str(tmp_path / "runs")]) == 0
    assert not (tmp_path / "tracked").exists()  # a fake run is never a tracked result
    assert len(list((tmp_path / "runs").glob("*/specs/*.json"))) == 3
    assert len(list((tmp_path / "runs").glob("*/architect-examples-*.json"))) == 1


# ---------------------------------------------------------------- AI-12: the seed set


def test_seed_set_is_one_clear_screened_request_per_seed_skill() -> None:
    items = load_items("seed")
    assert len(items) == SEED_SET_SIZE == 10
    assert len({i.id.split(":")[1].split("/")[0] for i in items}) == 10  # one per skill
    assert all(i.id.endswith("/req-1") and i.source == "seed" for i in items)
    assert all(i.analyzed.safety is not None and not i.analyzed.needs_clarification for i in items)


def _passages_for(spec: SkillSpec) -> tuple[Passage, ...]:
    """Fixture passages from the pages the example spec cites (it cites fixture pages)."""
    urls = {str(s.url) for s in spec.sources}
    return tuple(e.passage for e in FakeRetriever().entries if str(e.passage.source_url) in urls)


def seed_outcomes(
    *, traced: bool = True, cited: bool = True, total: int = 10
) -> list[Outcome[ArchitectItem, ArchitectResult]]:
    spec = SPEC if cited else SPEC.model_copy(update={"sources": [], "knowledge": Knowledge()})
    passages = _passages_for(SPEC) if traced else ()
    return [
        Outcome(item, ArchitectResult(True, spec, 1, (), passages=passages), None, 1.0)
        for item in load_items("seed")[:total]
    ]


def test_seed_verdict_passes_when_every_skill_cites_retrieved_pages() -> None:
    assert _passages_for(SPEC)  # the example's sources are fixture pages
    metrics = compute_metrics(seed_outcomes())
    assert metrics["knowledge"]["with_sources"] == metrics["knowledge"]["sources_traced"] == 10
    assert seed_verdict(metrics) == {"passed": True, "counts": True, "reasons": []}


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"traced": False}, "cite a page not retrieved"),
        ({"cited": False}, "have no cited sources"),
        ({"total": 9}, "exactly 10"),
    ],
)
def test_seed_verdict_fails(kwargs: dict[str, Any], reason: str) -> None:
    verdict = seed_verdict(compute_metrics(seed_outcomes(**kwargs)))
    assert not verdict["passed"] and any(reason in r for r in verdict["reasons"])


def test_cli_fake_seed_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    assert main(["run", "--set", "seed", "--runs", str(tmp_path / "runs")]) == 0
    [report] = list((tmp_path / "runs").glob("*/architect-seed-*.json"))
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["seed"]["counts"] is False  # a fake run never counts for AI-12
    assert saved["knowledge"]["backend"] == "fake" and saved["knowledge"]["fixtures"]
    assert saved["sets"]["seed"]["knowledge"]["with_passages"] == 10  # every seed domain
    assert len(list((tmp_path / "runs").glob("*/specs/*.json"))) == 10
