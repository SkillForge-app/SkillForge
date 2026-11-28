"""AI-25 for the Skill Architect (AI-07): an architect run becomes an id-only tracked run, and
re-scoring it offline reproduces the report exactly."""

import asyncio
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from core.agents import ArchitectResult
from core.agents.architect import ArchitectRefused, ArchitectUnavailable
from core.spec import Issue, load_spec
from evaluation.architect.data import ArchitectItem, load_items
from evaluation.architect.evaluate import run_eval, write_report
from evaluation.common import AI_ROOT
from evaluation.reproduce.check import repo_root
from evaluation.reproduce.registry import AI_DIR, Entry, Registry
from evaluation.reproduce.rescore import known_ids, rescore
from evaluation.reproduce.track import (
    ARCHITECT_CODES,
    FIELDS,
    TrackError,
    bad_fields,
    convert,
    convert_line,
)

SPEC = load_spec(AI_ROOT / "examples" / "skillspec" / "ai-engineer.yaml")
ITEMS = load_items("all")
REPO = repo_root(AI_DIR)
HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
).stdout.strip()

ROW: dict[str, Any] = {
    "set": "all",
    "id": "gate:t-01",
    "try": 1,
    "ok": False,
    "attempts": 3,
    "issues": [
        {"path": "/skill/name", "code": "reserved_name", "message": "SECRET", "severity": "error"}
    ],
    "codes": ["reserved_name"],
    "expected": {"kind": "task", "domain_area": "writing", "risk": "low"},
    "safety_ok": None,
    "identity_ok": None,
    "error": None,
    "latency_ms": 10.0,
    "usage": {"calls": 3},
}
KNOWN = frozenset({"all:gate:t-01", "all:example:review-nda"})


def test_every_issue_code_in_the_code_is_in_the_vocabulary() -> None:
    """A new validator code must be added to ARCHITECT_CODES, or tracking would refuse it."""
    pattern = re.compile(r'Issue\(\s*[^,]+,\s*"([a-z_.]+)"', re.S)
    found = set()
    for path in ("core/spec/validator.py", "core/agents/architect.py"):
        found |= set(pattern.findall((AI_ROOT / path).read_text(encoding="utf-8")))
    assert len(found) >= 15
    assert found <= ARCHITECT_CODES
    assert "schema.string_too_long" in ARCHITECT_CODES  # schema.<pydantic error type>


def test_an_architect_line_keeps_ids_labels_and_codes_only() -> None:
    line = convert_line(ROW, KNOWN)
    assert set(line) == set(FIELDS)
    assert "SECRET" not in json.dumps(line)  # issue messages never leave the run folder
    assert line["id"] == "all:gate:t-01"
    assert line["predicted"] == {
        "valid": False,
        "attempts": 3,
        "codes": ["reserved_name"],
        "safety_ok": None,
        "identity_ok": None,
    }
    assert convert_line({**ROW, "error": "ArchitectUnavailable"}, KNOWN)["error"] == (
        "provider_error"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"codes": ["the user said: delete everything"]},
        {"attempts": True},  # True == 1 in Python: the type is checked too
        {"ok": 1},
        {"safety_ok": "yes"},
        {"expected": {"kind": "task", "domain_area": "writing", "risk": "low", "note": "x"}},
    ],
)
def test_free_text_or_wrong_types_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(TrackError):
        convert_line({**ROW, **change}, KNOWN)


def test_known_ids_include_the_architect_sets() -> None:
    known = known_ids(REPO, HEAD)
    assert {f"all:{i.id}" for i in ITEMS} <= known
    assert {f"dev:{i.id}" for i in load_items("dev")} <= known
    assert {f"examples:{i.id}" for i in load_items("examples")} <= known


def result_for(n: int) -> ArchitectResult:
    if n % 9 == 4:  # fails validation; codes tie, so their order matters
        codes = ("reserved_name", "description_too_long") if n % 2 else ("schema.missing",)
        issues = tuple(Issue("/x", c, "message with SECRET text") for c in codes)
        return ArchitectResult(ok=False, spec=None, attempts=3, issues=issues)
    return ArchitectResult(ok=True, spec=SPEC, attempts=1 + n % 3, issues=())


async def a_run(tmp_path: Path, failing: Sequence[int]) -> tuple[Path, Path]:
    """A fake architect run: varied outcomes, a retry that works, errors, and requests that
    finish out of order (so the tracked file must restore the manifest's order)."""
    seen: dict[str, int] = {}

    async def build(item: ArchitectItem) -> ArchitectResult:
        n = ITEMS.index(item)
        seen[item.id] = seen.get(item.id, 0) + 1
        await asyncio.sleep(0.001 * ((n * 7) % 5))
        if n == 2 and seen[item.id] == 1:
            raise ArchitectUnavailable("down once")
        if n in failing:
            raise ArchitectUnavailable("down")
        if n == 50:
            raise ArchitectRefused("refused")
        return result_for(n)

    run = tmp_path / "runs" / "r1"
    report, _ = await run_eval(
        {"all": ITEMS},
        live=True,
        run_dir=run,
        label="all",
        concurrency=4,
        retry_errors=True,
        pause_after=0,
        build=build,
    )
    files = write_report(report, label="all", reports_dir=tmp_path / REPORTS, run_dir=run)
    return run, files.json


# `tmp_path` stands in for the repo root: registry paths must be repo-relative under ai/ (#41),
# and the architect re-score reads only the report and the tracked run, relative to the root.
REPORTS = "ai/evaluation/architect/reports"


def entry_for(root: Path, report: Path, tracked: Path, record: dict[str, Any]) -> Entry:
    return Entry.model_validate(
        {
            "id": "E13:architect-test",
            "experiment": "E13",
            "task": "AI-07",
            "question": "test",
            "kind": "live",
            "role": "final",
            "report": report.relative_to(root).as_posix(),
            "recorded_at": HEAD,
            "tracked_run": {"path": tracked.relative_to(root).as_posix(), **record},
        }
    )


@pytest.mark.parametrize("failing", [(), (10, 20, 30, 40, 60, 70)])
async def test_a_tracked_architect_run_rescores_to_the_report(
    tmp_path: Path, failing: Sequence[int]
) -> None:
    run, report_json = await a_run(tmp_path, failing)
    tracked = tmp_path / REPORTS / "runs" / "r1" / "predictions.jsonl"
    record = convert(run / "predictions.jsonl", tracked, known_ids(REPO, HEAD))
    assert record["lines"] == 103  # the retried request: one line, the retry's
    lines = [json.loads(x) for x in tracked.read_text(encoding="utf-8").splitlines()]
    assert [x["id"] for x in lines] == [f"all:{i.id}" for i in ITEMS]  # the manifest's order
    assert not bad_fields(lines, known_ids(REPO, HEAD))
    assert "SECRET" not in tracked.read_text(encoding="utf-8")

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert bool(report["invalid"]) is bool(failing)  # 6 of 103 with no prediction: invalid
    assert report["sets"]["all"]["top_failure_codes"]  # there are failures to re-score

    entry = entry_for(tmp_path, report_json, tracked, record)
    registry = Registry.model_validate({"version": 1, "ignore": [], "experiments": []})
    diffs, left = rescore(entry, registry, tmp_path)
    assert diffs == [] and left == []

    # and it is a real comparison: one changed number in the report is a difference
    report["sets"]["all"]["top_failure_codes"]["reserved_name"] += 1
    report_json.write_text(json.dumps(report), encoding="utf-8")
    diffs, _ = rescore(entry, registry, tmp_path)
    assert diffs


async def test_a_line_outside_the_manifest_is_refused(tmp_path: Path) -> None:
    run, _ = await a_run(tmp_path, ())
    lines = (run / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    extra = {**json.loads(lines[0]), "id": "gate:t-01x"}
    (run / "predictions.jsonl").write_text(
        "\n".join([*lines, json.dumps(extra)]) + "\n", encoding="utf-8"
    )
    with pytest.raises(TrackError, match="not in the run manifest"):
        convert(run / "predictions.jsonl", tmp_path / "t.jsonl", known_ids(REPO, HEAD))
