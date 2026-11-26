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
from evaluation.reproduce.registry import AI_DIR, Registry, RegistryError, load_registry
from evaluation.reproduce.rescore import _compare, analyzer_metrics, known_ids, safety_metrics
from evaluation.reproduce.strict import DuplicateKeyError, loads_unique, yaml_unique
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


# Text in a label value, a label key, a top-level key or the error: each problem names the known
# field (or says a name is hidden) and never contains the text itself.
TEXT_IN_A_LINE: list[tuple[str, Any, str]] = [
    ("predicted", {"kind": TEXT}, "line 1 predicted: kind: the value is outside the vocabulary"),
    ("expected", {"risk": [TEXT]}, "line 1 expected: risk: the value is outside the vocabulary"),
    ("predicted", {"mentioned_targets": [TEXT]}, "mentioned_targets: the value is outside"),
    ("predicted", {"mentioned_targets": TEXT}, "mentioned_targets: the value is outside"),
    ("predicted", {TEXT: "task"}, "a label field outside the allowlist (name not shown)"),
    ("predicted", TEXT, "line 1 predicted: the labels are not an object (value not shown)"),
    ("error", TEXT, "line 1: error is not an error class (value not shown)"),
    (TEXT, "x", "line 1: 1 field(s) outside the allowlist (names not shown)"),
]


@pytest.mark.parametrize(("field", "value", "message"), TEXT_IN_A_LINE)
def test_a_label_problem_never_shows_the_value(field: str, value: Any, message: str) -> None:
    clean = convert_line(ANALYZER_ROW, KNOWN)
    problems = bad_fields([{**clean, field: value}], KNOWN)
    assert len(problems) == 1 and message in problems[0]
    assert "cover letter" not in problems[0] and "not shown" in problems[0]


@pytest.mark.parametrize(
    "row",
    [
        {**ANALYZER_ROW, "predicted": {**ANALYZER_ROW["predicted"], "kind": TEXT}},
        {**ANALYZER_ROW, "predicted": {**ANALYZER_ROW["predicted"], TEXT: "task"}},
        {**ANALYZER_ROW, "mentioned_targets": {"expected": [], "predicted": [TEXT]}},
        {**SAFETY_ROW, "category": TEXT},
        {**SAFETY_ROW, "conditions": [TEXT]},
        {"set": "gate", "id": "t-01", TEXT: 1},  # unknown format: its keys are not shown either
    ],
)
def test_the_converter_never_shows_a_refused_value(row: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(TrackError) as caught:
        convert_line(row, KNOWN)
    assert "cover letter" not in str(caught.value) and "not shown" in str(caught.value)
    source = tmp_path / "predictions.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(TrackError) as caught:
        convert(source, tmp_path / "tracked.jsonl", KNOWN)
    assert "cover letter" not in str(caught.value)
    assert not (tmp_path / "tracked.jsonl").exists()


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


def live_repo(
    tmp_path: Path, tracked_id: str, *, run: str | None = None, report: str | None = None
) -> tuple[Path, Registry]:
    """A throwaway repo: labels for gate:t-01, a live report of n=1, and its tracked run (or the
    raw `run` / `report` text given)."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "core.autocrlf", "false")
    line = {**convert_line(ANALYZER_ROW, KNOWN), "id": tracked_id}
    run = run if run is not None else json.dumps(line, sort_keys=True) + "\n"
    files = {
        LABELS: (
            "requests:\n  - {id: t-01, kind: task, domain: writing/cv, risk: low,"
            " needs_clarification: false}\n"
        ),
        REPORT: report if report is not None else json.dumps({"sets": {"gate": {"n": 1}}}),
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


# ------------------------------------------------------------------ duplicate keys
# json.loads keeps the LAST of two equal keys: text could sit under a first `id` while a check
# sees only the allowed second one. Every parse in `reproduce` refuses duplicates at any depth.

CLEAN = json.dumps(convert_line(ANALYZER_ROW, KNOWN), sort_keys=True)
QUOTED = json.dumps(TEXT)


def first(key_and_value: str, line: str = CLEAN, at: str = "{") -> str:
    """`line` with `key_and_value` inserted right after `at`: before the real key, so the
    real (allowed) value is the one json.loads would keep."""
    head, tail = line.split(at, 1)
    return f"{head}{at}{key_and_value}, {tail}"


DUPLICATE_LINES = {
    "id: text first, allowed id second": (first(f'"id": "gate:{TEXT}"'), "'id'"),
    "id: free text first": (first(f'"id": {QUOTED}'), "'id'"),
    "a nested label key": (first(f'"kind": {QUOTED}', at='"predicted": {'), "'kind'"),
    "a top-level key": (first(f'"error": {QUOTED}'), "'error'"),
    "an unknown key, twice": (first(f"{QUOTED}: 1, {QUOTED}: 2"), "(name not shown)"),
}


@pytest.mark.parametrize("case", DUPLICATE_LINES)
def test_a_duplicate_key_fails_check_and_never_shows_the_text(tmp_path: Path, case: str) -> None:
    line, named = DUPLICATE_LINES[case]
    assert json.loads(line)["id"] == "gate:t-01"  # the hole: plain json.loads sees the allowed id
    repo, reg = live_repo(tmp_path, "gate:t-01", run=line + "\n")
    issues = check(reg, repo).issues
    assert [i.code for i in issues] == ["tracked_run_json"]
    assert f"duplicate key {named}" in issues[0].message
    assert "cover letter" not in issues[0].message and "values not shown" in issues[0].message


@pytest.mark.parametrize("case", DUPLICATE_LINES)
def test_a_duplicate_key_is_refused_by_the_converter(tmp_path: Path, case: str) -> None:
    line, named = DUPLICATE_LINES[case]
    source = tmp_path / "predictions.jsonl"
    source.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(TrackError) as caught:
        convert(source, tmp_path / "tracked.jsonl", KNOWN)
    assert f"line 1: duplicate key {named}" in str(caught.value)
    assert "cover letter" not in str(caught.value)
    assert not (tmp_path / "tracked.jsonl").exists()


def test_a_duplicate_key_in_a_source_row_is_refused(tmp_path: Path) -> None:
    raw = json.dumps(ANALYZER_ROW)
    source = tmp_path / "predictions.jsonl"
    for line in (
        first(f'"id": {QUOTED}', raw),  # the source id: text first, the real one second
        first(f'"kind": {QUOTED}', raw, at='"predicted": {'),
        first(f'"text": {QUOTED}', raw),  # even a field the converter drops
    ):
        source.write_text(line + "\n", encoding="utf-8")
        with pytest.raises(TrackError, match="duplicate key") as caught:
            convert(source, tmp_path / "tracked.jsonl", KNOWN)
        assert "cover letter" not in str(caught.value) and "SECRET" not in str(caught.value)
        assert not (tmp_path / "tracked.jsonl").exists()


def test_a_report_with_a_duplicate_key_fails_check(tmp_path: Path) -> None:
    report = '{"sets": {"gate": {"n": 2, "n": 1}}}'  # a changed count, hidden by the second `n`
    repo, reg = live_repo(tmp_path, "gate:t-01", report=report)
    issues = check(reg, repo).issues
    assert [(i.code, i.message) for i in issues] == [
        ("report_duplicate_key", "duplicate key 'n' in one object (values not shown)")
    ]


def test_the_registry_and_label_yaml_refuse_duplicate_keys(tmp_path: Path) -> None:
    registry = (AI_DIR / "evaluation" / "experiments.yaml").read_text(encoding="utf-8")
    path = tmp_path / "experiments.yaml"
    path.write_text(registry.replace("version: 1\n", "version: 1\nversion: 1\n", 1), "utf-8")
    with pytest.raises(RegistryError) as caught:
        load_registry(path)
    assert caught.value.issues[0].code == "duplicate_key"
    with pytest.raises(DuplicateKeyError, match="'reproduces'"):
        yaml_unique("- {id: E1, reproduces: false, reproduces: true}\n")
    with pytest.raises(DuplicateKeyError, match=r"\(name not shown\)"):
        yaml_unique(f"{QUOTED}: 1\n{QUOTED}: 2\n")
    merged = yaml_unique("base: &b {x: 1}\nother:\n  <<: *b\n  x: 2\n")  # an override is fine
    assert merged["other"] == {"x": 2}


def test_loads_unique_refuses_duplicates_at_any_depth() -> None:
    assert loads_unique('{"a": [{"b": 1}, {"b": 2}]}') == {"a": [{"b": 1}, {"b": 2}]}
    with pytest.raises(DuplicateKeyError, match="'b'"):
        loads_unique('{"a": [{"c": {"b": 1, "b": 1}}]}')  # even with equal values
