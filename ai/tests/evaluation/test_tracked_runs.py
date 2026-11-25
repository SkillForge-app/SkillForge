"""AI-25 step 4: id-only tracked runs and offline re-scoring of live results."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from evaluation.analyzer.evaluate import Prediction, write_report
from evaluation.common import text_sha256
from evaluation.reproduce.check import check, repo_root
from evaluation.reproduce.registry import AI_DIR, Registry, load_registry
from evaluation.reproduce.rescore import _compare, analyzer_metrics, known_ids, safety_metrics
from evaluation.reproduce.track import FIELDS, TrackError, bad_fields, convert, convert_line

KNOWN = frozenset({"gate:t-01", "gate:t-02", "gate:t-03", "redteam:r-31"})
TEXT = "How do I write a cover letter for a nursing job"

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
    line = convert_line(ANALYZER_ROW, KNOWN)
    assert set(line) == set(FIELDS)
    assert "SECRET" not in json.dumps(line)
    assert line["id"] == "gate:t-01" and line["predicted"]["kind"] == "role"
    assert set(convert_line(SAFETY_ROW, KNOWN)) == set(FIELDS)


def test_free_text_cannot_enter_a_label() -> None:
    with pytest.raises(TrackError):
        convert_line(
            {**ANALYZER_ROW, "predicted": {**ANALYZER_ROW["predicted"], "kind": "a role"}}, KNOWN
        )
    with pytest.raises(TrackError):
        convert_line({**SAFETY_ROW, "conditions": ["call 911 and say this"]}, KNOWN)
    with pytest.raises(TrackError):
        convert_line({**SAFETY_ROW, "category": "explanation: the user wants…"}, KNOWN)


# Ids that would carry text: free text in the id or the set, a slug of the text that is
# well-formed but in no label file, and a known id with a newline (or more) after it.
TEXT_IDS = [
    {"id": TEXT},
    {"set": TEXT},
    {"id": "how-do-i-write-a-cover-letter-for-a-nursing-job"},
    {"id": "t-01\n" + TEXT},
    {"id": "t-01\n"},
]


@pytest.mark.parametrize("change", TEXT_IDS)
def test_an_id_that_could_carry_text_is_refused_and_never_echoed(
    change: dict[str, str], tmp_path: Path
) -> None:
    with pytest.raises(TrackError) as caught:
        convert_line({**ANALYZER_ROW, **change}, KNOWN)
    assert "cover" not in str(caught.value) and "t-01" not in str(caught.value)
    source = tmp_path / "runs" / "x" / "predictions.jsonl"
    source.parent.mkdir(parents=True)
    rows = [ANALYZER_ROW, {**ANALYZER_ROW, **change}]
    source.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    target = tmp_path / "tracked" / "predictions.jsonl"
    with pytest.raises(TrackError, match="line 2"):
        convert(source, target, KNOWN)
    assert not target.exists()  # nothing written


def test_an_unknown_but_well_formed_id_is_refused() -> None:
    with pytest.raises(TrackError, match="not in the label files"):
        convert_line({**ANALYZER_ROW, "id": "t-99"}, KNOWN)
    with pytest.raises(TrackError, match="not in the label files"):
        convert_line({**SAFETY_ROW, "set": "benign"}, KNOWN)  # right id, wrong set


def test_errors_become_classes_never_messages() -> None:
    def error(row: dict[str, Any], name: str) -> Any:
        return convert_line({**row, "error": name}, KNOWN)["error"]

    assert error(ANALYZER_ROW, "LLMUnavailable") == "provider_error"
    assert error(SAFETY_ROW, "SafetyUnavailable") == "provider_error"
    assert error(ANALYZER_ROW, "LLMOutputInvalid") == "parse_error"
    assert error(ANALYZER_ROW, "SomethingElse") == "other"


def test_the_allowlist_test_fails_on_any_other_field() -> None:
    clean = convert_line(ANALYZER_ROW, KNOWN)
    assert bad_fields([clean], KNOWN) == []
    assert bad_fields([{**clean, "text": "x"}], KNOWN) != []
    assert bad_fields([{**clean, "rationale": "because"}], KNOWN) != []
    assert bad_fields([{**clean, "error": "Provider said: …"}], KNOWN) != []
    leaky = {**clean, "predicted": {**clean["predicted"], "summary": "free text"}}
    assert bad_fields([leaky], KNOWN) != []


def test_bad_fields_checks_every_id() -> None:
    clean = convert_line(ANALYZER_ROW, KNOWN)
    for bad in (f"gate:{TEXT}", TEXT, "gate:t-01\n", None, 7):
        problems = bad_fields([{**clean, "id": bad}], KNOWN)
        assert problems == ["line 1: the id is not well-formed (value not shown)"]
        assert bad_fields([{**clean, "id": bad}], None) == problems  # format: no history needed
    unknown = {**clean, "id": "gate:how-do-i-write-a-cover-letter"}
    assert bad_fields([unknown], KNOWN) == [
        "line 1: the id is not in the label files at recorded_at (value not shown)"
    ]


def test_new_runs_keep_targets_and_the_question_rule_as_labels() -> None:
    row = {
        **ANALYZER_ROW,
        "mentioned_targets": {"expected": ["claude"], "predicted": ["claude", "codex"]},
        "question_rule_kept": True,
    }
    line = convert_line(row, KNOWN)
    assert line["expected"]["mentioned_targets"] == ["claude"]
    assert line["predicted"] == {
        "kind": "role",
        "domain_area": "writing",
        "risk": "low",
        "needs_clarification": False,
        "mentioned_targets": ["claude", "codex"],
        "question_rule_kept": True,
    }
    assert bad_fields([line], KNOWN) == []
    with pytest.raises(TrackError):
        convert_line({**row, "mentioned_targets": {"expected": [], "predicted": ["gemini"]}}, KNOWN)


def test_convert_reads_the_source_and_records_both_hashes(tmp_path: Path) -> None:
    source = tmp_path / "runs" / "x" / "predictions.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(ANALYZER_ROW) + "\n", encoding="utf-8")
    before = source.read_bytes()
    record = convert(source, tmp_path / "tracked" / "predictions.jsonl", KNOWN)
    assert source.read_bytes() == before  # read only
    assert record["lines"] == 1 and record["source_sha256"] != record["sha256"]


def test_the_committed_tracked_runs_are_clean() -> None:
    """All 8 tracked files: allowlisted fields, and every id in the label files at recorded_at."""
    repo = repo_root(AI_DIR)
    files = set()
    for entry in load_registry().experiments:
        if entry.tracked_run is None:
            continue
        lines = [
            json.loads(line)
            for line in (repo / entry.tracked_run.path).read_text(encoding="utf-8").splitlines()
        ]
        known = known_ids(repo, entry.recorded_at)
        assert known, entry.id
        assert bad_fields(lines, known) == [], entry.id
        assert all(set(line) <= set(FIELDS) for line in lines)
        files.add(entry.tracked_run.path)
    assert len(files) == 8


# ------------------------------------------------------------------ `reproduce check`

REPORT = "ai/evaluation/analyzer/reports/analyzer-dev-2026-11-25.json"
RUN = "ai/evaluation/analyzer/reports/runs/20261125T000000Z/predictions.jsonl"
LABELS = "ai/evaluation/analyzer/requests-test.yaml"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def live_repo(tmp_path: Path, tracked_id: str) -> tuple[Path, Registry]:
    """A throwaway repo: labels for gate:t-01, a live report of n=1, and its tracked run."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "core.autocrlf", "false")
    line = {**convert_line(ANALYZER_ROW, KNOWN), "id": tracked_id}
    run = json.dumps(line, sort_keys=True) + "\n"
    files = {
        LABELS: (
            "requests:\n  - {id: t-01, kind: task, domain: writing/cv, risk: low,"
            " needs_clarification: false}\n"
        ),
        REPORT: json.dumps({"sets": {"gate": {"n": 1}}}),
        REPORT[: -len(".json")] + ".md": "# demo",
        RUN: run,
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content, encoding="utf-8", newline="\n")
        git(tmp_path, "add", rel)
    git(tmp_path, "commit", "-q", "-m", "live run")
    entry = {
        "id": "E7:demo",
        "experiment": "E7",
        "task": "AI-05",
        "question": "Does the demo work?",
        "kind": "live",
        "role": "final",
        "report": REPORT,
        "recorded_at": git(tmp_path, "rev-parse", "HEAD"),
        "tracked_run": {
            "path": RUN,
            "source_sha256": hashlib.sha256(b"source").hexdigest(),
            "sha256": text_sha256(run.encode()),
            "lines": 1,
        },
    }
    reg = Registry.model_validate({"version": 1, "ignore": [], "experiments": [entry]})
    return tmp_path, reg


def test_check_passes_a_tracked_run_whose_ids_are_in_the_labels(tmp_path: Path) -> None:
    repo, reg = live_repo(tmp_path, "gate:t-01")
    assert check(reg, repo).issues == []


@pytest.mark.parametrize(
    ("tracked_id", "problem"),
    [
        (f"gate:{TEXT}", "not well-formed"),
        ("gate:how-do-i-write-a-cover-letter", "not in the label files"),
        ("gate:t-02", "not in the label files"),
    ],
)
def test_check_fails_an_id_that_is_text_or_unknown(
    tmp_path: Path, tracked_id: str, problem: str
) -> None:
    repo, reg = live_repo(tmp_path, tracked_id)
    issues = check(reg, repo).issues
    assert [i.code for i in issues] == ["tracked_run_field"]
    assert problem in issues[0].message and "cover" not in issues[0].message
    # without git history only the format is checked
    format_only = check(reg, repo, history=False).issues
    assert [i.code for i in format_only] == (
        ["tracked_run_field"] if problem == "not well-formed" else []
    )


# ------------------------------------------------------------------ re-scoring


def tracked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [convert_line(r, KNOWN) for r in rows]


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
