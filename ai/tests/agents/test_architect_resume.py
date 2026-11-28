"""The architect run folder (AI-07 pre-flight): outcomes saved as they finish, and resume.

A paid run that dies at request 60 must continue from request 60: the first 59 are never paid
for twice, and the resumed run scores exactly like one that never stopped.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from core.agents import ArchitectResult
from core.llm import FakeGateway, use_fake
from core.llm.gateway import BACKEND_ENV
from core.spec import Issue, load_spec
from evaluation.architect.__main__ import main
from evaluation.architect.data import ArchitectItem, load_items
from evaluation.architect.evaluate import run_eval
from evaluation.architect.runlog import MANIFEST, PREDICTIONS, ResumeError, RunLog
from evaluation.common import AI_ROOT

SPEC = load_spec(AI_ROOT / "examples" / "skillspec" / "ai-engineer.yaml")
ITEMS = load_items("all")


class Crash(BaseException):
    """Stands in for the process dying (not an Exception: run_all must not catch it)."""


def result_for(item: ArchitectItem) -> ArchitectResult:
    """A deterministic mix of outcomes: every 7th request fails validation with two codes."""
    n = ITEMS.index(item)
    if n % 7 == 3:
        issues = (Issue("/skill/name", "reserved_name", "m"), Issue("/x", "duplicate_id", "m"))
        return ArchitectResult(ok=False, spec=None, attempts=3, issues=issues)
    return ArchitectResult(ok=True, spec=SPEC, attempts=1 + n % 2, issues=())


def sets() -> dict[str, Sequence[ArchitectItem]]:
    return {"all": ITEMS}


async def test_crash_at_60_then_resume_pays_only_for_the_rest(tmp_path: Path) -> None:
    calls: list[str] = []

    async def dies_at_60(item: ArchitectItem) -> ArchitectResult:
        if ITEMS.index(item) >= 59:  # the process is gone: nothing from request 60 on finishes
            raise Crash
        calls.append(item.id)
        return result_for(item)

    run = tmp_path / "run"
    with pytest.raises(Crash):
        await run_eval(
            sets(), live=False, run_dir=run, label="all", concurrency=1, build=dies_at_60
        )
    assert len(calls) == 59
    assert len(RunLog(run, {}).rows()) == 59  # each saved the moment it finished

    resumed: list[str] = []

    async def build(item: ArchitectItem) -> ArchitectResult:
        resumed.append(item.id)
        return result_for(item)

    report, _ = await run_eval(
        sets(), live=False, run_dir=run, label="all", resume=True, build=build
    )
    assert resumed == [i.id for i in ITEMS[59:]]  # requests 1-59 are not called again
    assert len(report.segments) == 2 and not report.missing

    async def straight(item: ArchitectItem) -> ArchitectResult:
        return result_for(item)

    once, _ = await run_eval(
        sets(), live=False, run_dir=tmp_path / "once", label="all", build=straight
    )
    assert report.sets == once.sets  # the same metrics as a run that never stopped
    assert report.gate == once.gate


async def test_resume_refuses_another_measurement(tmp_path: Path) -> None:
    async def build(item: ArchitectItem) -> ArchitectResult:
        return result_for(item)

    run = tmp_path / "run"
    await run_eval({"all": ITEMS[:5]}, live=False, run_dir=run, label="all", build=build)
    with pytest.raises(ResumeError, match="ids"):
        await run_eval(
            {"all": ITEMS[:6]}, live=False, run_dir=run, label="all", resume=True, build=build
        )
    with pytest.raises(ResumeError, match="live"):
        await run_eval(
            {"all": ITEMS[:5]}, live=True, run_dir=run, label="all", resume=True, build=build
        )
    manifest = json.loads((run / MANIFEST).read_text(encoding="utf-8"))
    manifest["prompts"]["architect/generate"]["sha256"] = "0" * 64  # the prompt changed since
    (run / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ResumeError, match="prompts"):
        await run_eval(
            {"all": ITEMS[:5]}, live=False, run_dir=run, label="all", resume=True, build=build
        )
    with pytest.raises(ResumeError, match="not a run folder"):
        await run_eval(
            {"all": ITEMS[:5]}, live=False, run_dir=tmp_path / "x", resume=True, build=build
        )


async def test_a_new_run_never_writes_over_an_old_one(tmp_path: Path) -> None:
    async def build(item: ArchitectItem) -> ArchitectResult:
        return result_for(item)

    await run_eval({"all": ITEMS[:2]}, live=False, run_dir=tmp_path / "run", build=build)
    with pytest.raises(FileExistsError):
        await run_eval({"all": ITEMS[:2]}, live=False, run_dir=tmp_path / "run", build=build)


async def test_a_line_cut_off_by_a_crash_runs_again(tmp_path: Path) -> None:
    async def build(item: ArchitectItem) -> ArchitectResult:
        return result_for(item)

    run = tmp_path / "run"
    await run_eval({"all": ITEMS[:4]}, live=False, run_dir=run, label="all", build=build)
    lines = (run / PREDICTIONS).read_text(encoding="utf-8").splitlines()
    (run / PREDICTIONS).write_text("\n".join(lines[:3]) + "\n" + lines[3][:20], encoding="utf-8")

    again: list[str] = []

    async def counting(item: ArchitectItem) -> ArchitectResult:
        again.append(item.id)
        return result_for(item)

    report, _ = await run_eval(
        {"all": ITEMS[:4]}, live=False, run_dir=run, label="all", resume=True, build=counting
    )
    assert again == [ITEMS[3].id] and report.sets["all"]["n"] == 4


async def test_error_rows_are_outcomes_and_budget_refusals_are_not(tmp_path: Path) -> None:
    from core.agents.architect import ArchitectUnavailable
    from core.llm.errors import BudgetExceeded

    async def build(item: ArchitectItem) -> ArchitectResult:
        n = ITEMS.index(item)
        if n == 0:
            raise ArchitectUnavailable("down")
        if n == 1:
            raise BudgetExceeded("used up")
        return result_for(item)

    run = tmp_path / "run"
    report, _ = await run_eval(
        {"all": ITEMS[:3]}, live=False, run_dir=run, label="all", build=build
    )
    assert report.missing == {"all": 1}  # the budget refusal was never attempted
    assert report.sets["all"]["errors"] == {"ArchitectUnavailable": 1}
    assert not report.gate or not report.gate["passed"]

    again: list[str] = []

    async def ok(item: ArchitectItem) -> ArchitectResult:
        again.append(item.id)
        return result_for(item)

    await run_eval({"all": ITEMS[:3]}, live=False, run_dir=run, label="all", resume=True, build=ok)
    assert again == [ITEMS[1].id]  # a provider error is an outcome: the retry rule handles it


async def test_rows_carry_ids_labels_and_codes_for_tracking(tmp_path: Path) -> None:
    async def build(item: ArchitectItem) -> ArchitectResult:
        return result_for(item)

    run = tmp_path / "run"
    await run_eval({"all": ITEMS[:5]}, live=False, run_dir=run, label="all", build=build)
    rows = RunLog(run, {}).rows()
    failed = next(r for r in rows if not r["ok"])
    assert failed["codes"] == ["reserved_name", "duplicate_id"]
    assert failed["safety_ok"] is None and failed["expected"]["kind"] in (
        "role",
        "task",
        "workflow",
    )
    good = next(r for r in rows if r["ok"])
    assert good["safety_ok"] in (True, False) and good["codes"] == []
    assert len(list((run / "specs").glob("*.json"))) == sum(r["ok"] for r in rows)


async def test_usage_is_counted_per_request_and_summed(tmp_path: Path) -> None:
    from evaluation.architect.evaluate import _build

    with use_fake(FakeGateway(cost_usd=0.01)):
        report, _ = await run_eval(
            {"examples": load_items("examples")}, live=False, run_dir=tmp_path / "r", build=_build
        )
    rows = RunLog(tmp_path / "r", {}).rows()
    assert all(r["usage"]["calls"] >= 1 for r in rows)
    assert report.usage["calls"] == sum(r["usage"]["calls"] for r in rows)
    assert report.usage["cost_usd"] == pytest.approx(0.01 * report.usage["calls"])


def test_cli_resume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    assert main(["run", "--set", "examples", "--runs", str(tmp_path / "runs")]) == 0
    (run,) = list((tmp_path / "runs").iterdir())
    assert main(["run", "--set", "examples", "--resume", str(run)]) == 0
    assert len(list(run.glob("architect-examples-*.md"))) == 2  # a second report, nothing re-run
    assert len(RunLog(run, {}).rows()) == 3
    assert main(["run", "--set", "all", "--resume", str(run)]) == 2  # other items: refused
