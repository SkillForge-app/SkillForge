"""AI-25 step 4: id-only tracked runs and offline re-scoring of live results."""

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation.analyzer.evaluate import Prediction, write_report
from evaluation.reproduce.check import repo_root
from evaluation.reproduce.registry import AI_DIR, load_registry
from evaluation.reproduce.rescore import _compare, analyzer_metrics, safety_metrics
from evaluation.reproduce.track import FIELDS, TrackError, bad_fields, convert, convert_line

ANALYZER_ROW: dict[str, Any] = {
    "set": "gate",
    "id": "t-01",
    "text": "SECRET REQUEST TEXT",
    "expected": {"kind": "task", "domain_area": "writing", "risk": "low"},
    "predicted": {"kind": "role", "domain_area": "writing", "risk": "low"},
    "needs_clarification": {"expected": False, "predicted": False},
    "error": None,
}
SAFETY_ROW: dict[str, Any] = {
    "set": "redteam",
    "id": "r-31",
    "expected": "block",
    "verdict": "block",
    "category": "child_safety",
    "conditions": [],
    "error": None,
}


def test_the_text_is_dropped_and_only_allowed_fields_remain() -> None:
    line = convert_line(ANALYZER_ROW)
    assert set(line) == set(FIELDS)
    assert "SECRET" not in json.dumps(line)
    assert line["id"] == "gate:t-01" and line["predicted"]["kind"] == "role"
    assert set(convert_line(SAFETY_ROW)) == set(FIELDS)


def test_free_text_cannot_enter_a_label() -> None:
    with pytest.raises(TrackError):
        convert_line({**ANALYZER_ROW, "predicted": {**ANALYZER_ROW["predicted"], "kind": "a role"}})
    with pytest.raises(TrackError):
        convert_line({**SAFETY_ROW, "conditions": ["call 911 and say this"]})
    with pytest.raises(TrackError):
        convert_line({**SAFETY_ROW, "category": "explanation: the user wants…"})


def test_errors_become_classes_never_messages() -> None:
    assert convert_line({**ANALYZER_ROW, "error": "LLMUnavailable"})["error"] == "provider_error"
    assert convert_line({**SAFETY_ROW, "error": "SafetyUnavailable"})["error"] == "provider_error"
    assert convert_line({**ANALYZER_ROW, "error": "LLMOutputInvalid"})["error"] == "parse_error"
    assert convert_line({**ANALYZER_ROW, "error": "SomethingElse"})["error"] == "other"


def test_the_allowlist_test_fails_on_any_other_field() -> None:
    clean = convert_line(ANALYZER_ROW)
    assert bad_fields([clean]) == []
    assert bad_fields([{**clean, "text": "x"}]) != []
    assert bad_fields([{**clean, "rationale": "because"}]) != []
    assert bad_fields([{**clean, "error": "Provider said: …"}]) != []
    leaky = {**clean, "predicted": {**clean["predicted"], "summary": "free text"}}
    assert bad_fields([leaky]) != []


def test_new_runs_keep_targets_and_the_question_rule_as_labels() -> None:
    row = {
        **ANALYZER_ROW,
        "mentioned_targets": {"expected": ["claude"], "predicted": ["claude", "codex"]},
        "question_rule_kept": True,
    }
    line = convert_line(row)
    assert line["expected"]["mentioned_targets"] == ["claude"]
    assert line["predicted"] == {
        "kind": "role",
        "domain_area": "writing",
        "risk": "low",
        "needs_clarification": False,
        "mentioned_targets": ["claude", "codex"],
        "question_rule_kept": True,
    }
    assert bad_fields([line]) == []
    with pytest.raises(TrackError):
        convert_line({**row, "mentioned_targets": {"expected": [], "predicted": ["gemini"]}})


def test_convert_reads_the_source_and_records_both_hashes(tmp_path: Path) -> None:
    source = tmp_path / "runs" / "x" / "predictions.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(ANALYZER_ROW) + "\n", encoding="utf-8")
    before = source.read_bytes()
    record = convert(source, tmp_path / "tracked" / "predictions.jsonl")
    assert source.read_bytes() == before  # read only
    assert record["lines"] == 1 and record["source_sha256"] != record["sha256"]


def test_the_committed_tracked_runs_are_clean() -> None:
    repo = repo_root(AI_DIR)
    for entry in load_registry().experiments:
        if entry.tracked_run is None:
            continue
        lines = [
            json.loads(line)
            for line in (repo / entry.tracked_run.path).read_text(encoding="utf-8").splitlines()
        ]
        assert bad_fields(lines) == [], entry.id
        assert all(set(line) <= set(FIELDS) for line in lines)


# ------------------------------------------------------------------ re-scoring


def tracked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [convert_line(r) for r in rows]


def test_analyzer_rescore_matches_the_evaluation_formulas() -> None:
    rows = tracked(
        [
            ANALYZER_ROW,
            {**ANALYZER_ROW, "id": "t-02", "predicted": dict(ANALYZER_ROW["expected"])},
            {**ANALYZER_ROW, "id": "t-03", "error": "LLMUnavailable"},
        ]
    )
    m = analyzer_metrics(rows, {}, relabel=False)
    assert m["n"] == 3 and m["fields"]["kind"]["correct"] == 1
    assert m["fields"]["kind"]["confusion"] == {"task": {"role": 1, "task": 1, "<error>": 1}}
    assert m["joint_accuracy"] == round(1 / 3, 4) and m["errors"] == {"provider_error": 1}
    assert "exact_match" not in m["mentioned_targets"]  # the run never saved targets


def test_safety_rescore_uses_the_item_facts() -> None:
    items = {
        "redteam:r-31": {"category": "child_safety", "attack": "direct", "expected_conditions": []}
    }
    m = safety_metrics(tracked([SAFETY_ROW]), items)
    assert m["block_rate"] == 1.0 and m["by_category"] == {"child_safety": {"n": 1, "blocked": 1}}
    assert m["category_accuracy"] == 1.0 and m["misses"] == []


def test_a_metric_left_out_must_be_listed() -> None:
    report = {"sets": {"gate": {"n": 3, "mentioned_targets": {"n": 1, "exact_match": 1.0}}}}
    rescored = {"sets": {"gate": {"n": 3, "mentioned_targets": {"n": 1}}}}
    diffs: list[str] = []
    left: list[str] = []
    _compare(report, rescored, "", set(), diffs, left)
    assert diffs and "not listed in not_recomputable" in diffs[0] and left == []
    diffs, left = [], []
    _compare(report, rescored, "", {"mentioned_targets.exact_match"}, diffs, left)
    assert diffs == [] and left == [
        "sets.gate.mentioned_targets.exact_match: in the report, not re-scored"
    ]


def test_a_changed_number_is_never_hidden() -> None:
    diffs: list[str] = []
    _compare({"sets": {"gate": {"n": 3}}}, {"sets": {"gate": {"n": 4}}}, "", {"n"}, diffs, [])
    assert diffs == ["sets.gate.n: report 3 | re-score 4"]


def test_the_analyzer_run_file_keeps_targets_and_the_rule_but_no_question_text(
    tmp_path: Path,
) -> None:
    from evaluation.analyzer.data import load_set
    from evaluation.analyzer.evaluate import EvalReport

    item = next(i for i in load_set("gate") if i.mentioned_targets is not None)

    class Result:
        kind, domain_area, risk = item.kind, item.domain_area, item.risk
        needs_clarification = True
        targets = ["claude"]
        questions = [object()] * 3

    report = EvalReport(
        created="2026-11-25T00:00:00Z",
        live=False,
        prompt={"id": "analysis/request", "version": 1},
        model="m",
        data_sources=[],
        usage={"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    )
    pred = Prediction(item, Result(), None, 1.0)  # type: ignore[arg-type]
    write_report(
        report, {"gate": [pred]}, label="gate", reports_dir=tmp_path, run_dir=tmp_path / "run"
    )
    row = json.loads((tmp_path / "run" / "predictions.jsonl").read_text(encoding="utf-8"))
    assert row["mentioned_targets"]["predicted"] == ["claude"]
    assert row["question_rule_kept"] is True
    assert "questions" not in row
