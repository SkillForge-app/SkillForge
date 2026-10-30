"""The evaluation math, the 90% gate and the reports, with a scripted 'oracle' gateway."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from core.llm import LLMUnavailable, load_prompt, use_fake
from core.llm.gateway import BACKEND_ENV
from evaluation.analyzer import data
from evaluation.analyzer.__main__ import main
from evaluation.analyzer.data import EvalItem
from evaluation.analyzer.evaluate import compute_metrics, gate_verdict, run_eval, write_report

T = TypeVar("T", bound=BaseModel)
QUESTIONS = [
    {"id": "q1", "text": "Who is it for?", "about": "audience"},
    {"id": "q2", "text": "What should it produce?", "about": "outputs"},
    {"id": "q3", "text": "Which platforms?", "about": "platforms"},
]


class OracleGateway:
    """Answers from the labels, with chosen mistakes. Implements the LLMGateway protocol."""

    def __init__(
        self,
        items: Sequence[EvalItem],
        wrong: Mapping[str, Mapping[str, Any]] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.by_text = {i.text: i for i in items}
        self.wrong = dict(wrong or {})
        self.fail = fail or set()

    async def complete(
        self,
        prompt_id: str,
        inputs: Mapping[str, Any],
        output_model: type[T],
        *,
        model_role: str | None = None,
    ) -> T:
        load_prompt(prompt_id).render(inputs)  # the real prompt must accept the inputs
        item = self.by_text[inputs["request_text"]]
        if item.id in self.fail:
            raise LLMUnavailable("provider down")
        answer: dict[str, Any] = {
            "kind": item.kind,
            "domain": item.domain,
            "risk": item.risk,
            "mentioned_targets": list(item.mentioned_targets or ()),
            "summary": "s",
            "needs_clarification": item.needs_clarification,
            "questions": QUESTIONS if item.needs_clarification else [],
        }
        answer.update(self.wrong.get(item.id, {}))
        return output_model.model_validate_json(json.dumps(answer))

    async def embed(
        self, texts: Sequence[str], *, model_role: str = "embedding"
    ) -> list[list[float]]:
        raise NotImplementedError


def gate_items() -> list[EvalItem]:
    return data.load_set("gate")


async def evaluate(items: list[EvalItem], **oracle: Any) -> dict[str, Any]:
    with use_fake(OracleGateway(items, **oracle)):  # type: ignore[arg-type]
        report, _ = await run_eval({"gate": items}, live=False)
    return {"metrics": report.sets["gate"], "gate": report.gate, "report": report}


async def test_perfect_answers_pass_the_gate() -> None:
    result = await evaluate(gate_items())
    m = result["metrics"]
    assert m["n"] == 100
    assert {f: m["fields"][f]["accuracy"] for f in ("kind", "domain_area", "risk")} == {
        "kind": 1.0,
        "domain_area": 1.0,
        "risk": 1.0,
    }
    assert m["needs_clarification"]["accuracy"] == 1.0
    assert m["mentioned_targets"] == {"n": 70, "exact_match": 1.0}
    assert result["gate"]["passed"]


async def test_exactly_90_percent_passes_and_89_fails() -> None:
    items = gate_items()
    non_design = [i for i in items if i.domain_area != "design"]
    ten = {i.id: {"domain": "design/wrong"} for i in non_design[:10]}
    result = await evaluate(items, wrong=ten)
    assert result["metrics"]["fields"]["domain_area"]["accuracy"] == 0.90
    assert result["gate"]["passed"]

    eleven = {i.id: {"domain": "design/wrong"} for i in non_design[:11]}
    result = await evaluate(items, wrong=eleven)
    assert not result["gate"]["passed"]
    assert result["gate"]["reasons"] == ["domain_area accuracy 0.89 < 0.90"]


async def test_each_field_is_gated_on_its_own() -> None:
    items = gate_items()
    wrong_kind = {
        i.id: {"kind": "workflow" if i.kind != "workflow" else "role"} for i in items[:15]
    }
    result = await evaluate(items, wrong=wrong_kind)
    m = result["metrics"]
    assert m["fields"]["kind"]["accuracy"] == 0.85
    assert m["fields"]["domain_area"]["accuracy"] == 1.0
    assert m["joint_accuracy"] == 0.85
    assert not result["gate"]["passed"]


async def test_errors_count_as_wrong_and_are_listed() -> None:
    items = gate_items()
    result = await evaluate(items, fail={i.id for i in items[:3]})
    m = result["metrics"]
    assert m["errors"] == {"LLMUnavailable": 3}
    assert all(m["fields"][f]["accuracy"] == 0.97 for f in ("kind", "domain_area", "risk"))
    first = items[0]
    assert m["fields"]["kind"]["confusion"][first.kind]["<error>"] >= 1


def test_gate_needs_exactly_100_requests() -> None:
    metrics = compute_metrics([])
    verdict = gate_verdict(metrics)
    assert not verdict["passed"]
    assert "exactly 100" in verdict["reasons"][0]


async def test_report_files_record_versions_and_hashes(tmp_path: Path) -> None:
    items = gate_items()[:5]
    with use_fake(OracleGateway(items)):  # type: ignore[arg-type]
        report, predictions = await run_eval({"gate": items, "arabic": []}, live=False)
    out = write_report(report, predictions, tmp_path / "run")
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert saved["prompt"] == {"id": "analysis/request", "version": 1}
    assert [s["name"] for s in saved["data_sources"]][0] == "skillforge-seed-benchmark"
    assert all(len(s["sha256"]) == 64 for s in saved["data_sources"])
    rows = (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 5
    assert "Gate" in (out / "report.md").read_text(encoding="utf-8")


def test_cli_refuses_real_calls_without_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    assert main(["run", "--set", "gate", "--limit", "1"]) == 2


def test_cli_live_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    for env in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr("evaluation.analyzer.__main__.load_dotenv", lambda *a, **k: False)
    assert main(["run", "--live", "--limit", "1"]) == 2


def test_cli_fake_smoke_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    code = main(["run", "--set", "gate", "--limit", "3", "--out", str(tmp_path / "run")])
    assert code == 1  # the fake gives every request the same answer, so the gate fails
    assert (tmp_path / "run" / "report.json").exists()
