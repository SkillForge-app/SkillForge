"""The live-run rules of the architect evaluation (AI-07 pre-flight), on the fake gateway.

Budget (refuse before the first call, stop at the cap, count every segment), one retry for
provider errors, a pause after 5 provider errors in a row (then resume), the 95% validity
rule, and the call log that says which provider failed how. No model is called.
"""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

from core.agents import ArchitectResult
from core.agents.architect import ArchitectRefused, ArchitectUnavailable
from core.llm import FakeGateway, load_config, use_fake
from core.llm.config import key_env_for
from core.llm.gateway import BACKEND_ENV
from core.llm.usage import CallRecord
from core.spec import load_spec
from evaluation.architect.__main__ import main
from evaluation.architect.data import ArchitectItem, load_items
from evaluation.architect.evaluate import _build, exit_code, run_eval
from evaluation.architect.runlog import RunLog
from evaluation.common import AI_ROOT

SPEC = load_spec(AI_ROOT / "examples" / "skillspec" / "ai-engineer.yaml")
ITEMS = load_items("all")
OK = ArchitectResult(ok=True, spec=SPEC, attempts=1, issues=())


def all_sets() -> dict[str, Sequence[ArchitectItem]]:
    return {"all": ITEMS}


async def test_a_fallback_answers_and_the_call_log_says_so(tmp_path: Path) -> None:
    fake = FakeGateway()
    fake.fail_model(load_config().role("architect").model)  # the primary is down
    with use_fake(fake):
        report, _ = await run_eval(
            {"examples": load_items("examples")}, live=False, run_dir=tmp_path / "r", build=_build
        )
    assert report.sets["examples"]["valid"] == 3
    calls = RunLog(tmp_path / "r", {}).calls()
    assert {c["fallback"] for c in calls if c["status"] == "ok"} == {1}
    assert report.provider_errors == [
        {"error": "LLMUnavailable", "status": None, "provider": None, "fallback": 0, "count": 3}
    ]
    assert all(set(c) <= set(CallRecord.model_fields) for c in calls)  # metadata only
    assert report.usage["calls"] == 6 and report.usage["errors"] == 3


async def test_provider_errors_get_one_retry_at_the_end(tmp_path: Path) -> None:
    seen: Counter[str] = Counter()

    async def build(item: ArchitectItem) -> ArchitectResult:
        seen[item.id] += 1
        n = ITEMS.index(item)
        if n == 1 and seen[item.id] == 1:
            raise ArchitectUnavailable("down once")
        if n == 2:
            raise ArchitectUnavailable("down twice")
        if n == 3:
            raise ArchitectRefused("refused")  # not a provider error: never retried
        return OK

    report, _ = await run_eval(
        {"all": ITEMS[:5]}, live=False, run_dir=tmp_path / "r", retry_errors=True, build=build
    )
    retries = sorted(report.retries, key=lambda r: r["id"])
    assert retries == sorted(
        [
            {"set": "all", "id": ITEMS[1].id, "first_error": "ArchitectUnavailable", "retry": "ok"},
            {
                "set": "all",
                "id": ITEMS[2].id,
                "first_error": "ArchitectUnavailable",
                "retry": "ArchitectUnavailable",
            },
        ],
        key=lambda r: r["id"],
    )
    assert seen[ITEMS[2].id] == 2 and seen[ITEMS[3].id] == 1 and seen[ITEMS[0].id] == 1
    assert report.sets["all"]["valid"] == 3
    assert report.sets["all"]["errors"] == {"ArchitectUnavailable": 1, "ArchitectRefused": 1}
    assert report.retry_rule is not None and "ONCE" in report.retry_rule


async def test_five_provider_errors_in_a_row_pause_the_run_then_resume(tmp_path: Path) -> None:
    async def outage(item: ArchitectItem) -> ArchitectResult:
        if ITEMS.index(item) >= 10:
            raise ArchitectUnavailable("down")
        return OK

    run = tmp_path / "r"
    kw = {"live": False, "run_dir": run, "label": "all", "concurrency": 1, "retry_errors": True}
    report, _ = await run_eval(all_sets(), build=outage, **kw)  # type: ignore[arg-type]
    assert report.paused and exit_code(report) == 5
    assert len(RunLog(run, {}).rows()) == 15  # 10 answered + the 5 errors in a row; no retry
    assert report.missing == {"all": 103 - 15} and report.retries == []
    assert report.gate is not None and not report.gate["passed"]

    called: list[str] = []

    async def back(item: ArchitectItem) -> ArchitectResult:
        called.append(item.id)
        return OK

    report, _ = await run_eval(all_sets(), build=back, resume=True, **kw)  # type: ignore[arg-type]
    # the requests that never started, then the one retry of the 5 that hit the outage
    assert called == [i.id for i in ITEMS[15:]] + [i.id for i in ITEMS[10:15]]
    assert not report.paused and not report.missing and len(report.retries) == 5
    assert report.gate is not None and report.gate["passed"] and exit_code(report) == 0


async def test_the_budget_stops_the_run_and_counts_every_segment(tmp_path: Path) -> None:
    run = tmp_path / "r"
    sets = {"examples": load_items("examples")}
    with use_fake(FakeGateway(cost_usd=0.4)):  # one call per request here
        report, _ = await run_eval(
            sets, live=False, run_dir=run, budget_usd=0.5, concurrency=1, build=_build
        )
        assert report.stopped and exit_code(report) == 3
        assert report.sets["examples"]["n"] == 2 and report.missing == {"examples": 1}
        assert report.usage["cost_usd"] == pytest.approx(0.8)  # the call already running ends

        # A resume with the same budget: the $0.80 already spent counts, so no call is made.
        report, _ = await run_eval(
            sets, live=False, run_dir=run, budget_usd=0.5, resume=True, build=_build
        )
        assert report.stopped and report.usage["cost_usd"] == pytest.approx(0.8)

        report, _ = await run_eval(
            sets, live=False, run_dir=run, budget_usd=2.0, resume=True, build=_build
        )
    assert not report.stopped and not report.missing and exit_code(report) == 0
    assert report.usage["cost_usd"] == pytest.approx(1.2)


@pytest.mark.parametrize(("failing", "invalid"), [(5, False), (6, True)])
async def test_validity_rule_at_95_percent(tmp_path: Path, failing: int, invalid: bool) -> None:
    down = {ITEMS[10 * k].id for k in range(failing)}  # spread out: no pause

    async def build(item: ArchitectItem) -> ArchitectResult:
        if item.id in down:
            raise ArchitectUnavailable("down")
        return OK

    report, _ = await run_eval(
        all_sets(),
        live=False,
        run_dir=tmp_path / "r",
        label="all",
        retry_errors=True,
        pause_after=0,  # this test is about the validity rule alone
        build=build,
    )
    assert bool(report.invalid) is invalid
    assert report.gate is not None
    if invalid:
        assert exit_code(report) == 4 and "6 of 103" in (report.invalid or "")
        assert "invalid run (validity rule): repeat it" in report.gate["reasons"]
    else:  # 98 of 103 predicted: a valid run, measured (and here 98 valid: passes)
        assert report.gate["passed"] and exit_code(report) == 0


async def test_retries_that_keep_failing_pause_and_the_rest_wait(tmp_path: Path) -> None:
    """6 requests hit by an outage that lasts through their retries: the pause stops the 6th
    retry, which waits for --resume; no INVALID verdict while it waits."""
    down = {ITEMS[10 * k].id for k in range(6)}

    async def build(item: ArchitectItem) -> ArchitectResult:
        if item.id in down:
            raise ArchitectUnavailable("down")
        return OK

    run = tmp_path / "r"
    kw = {"live": False, "run_dir": run, "label": "all", "retry_errors": True, "concurrency": 1}
    report, _ = await run_eval(all_sets(), build=build, **kw)  # type: ignore[arg-type]
    assert report.paused and report.invalid is None and exit_code(report) == 5
    assert len(report.retries) == 5

    async def back(item: ArchitectItem) -> ArchitectResult:
        return OK

    report, _ = await run_eval(all_sets(), build=back, resume=True, **kw)  # type: ignore[arg-type]
    assert not report.paused and len(report.retries) == 6
    assert report.sets["all"]["valid"] == 98 and exit_code(report) == 0


# ------------------------------------------------------------------ the command line


def live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass live_guard without a real key: these runs must refuse before any call."""
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    key = key_env_for(load_config().role("architect").model)
    if key:
        monkeypatch.setenv(key, "placeholder")


def test_live_needs_a_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    live_env(monkeypatch)
    runs = tmp_path / "runs"
    assert main(["run", "--set", "all", "--live", "--runs", str(runs)]) == 2
    assert main(["run", "--set", "all", "--live", "--budget-usd", "0", "--runs", str(runs)]) == 2
    assert not runs.exists()


def test_live_refuses_when_the_estimate_is_over_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live_env(monkeypatch)
    runs = tmp_path / "runs"
    argv = ["run", "--set", "all", "--live", "--budget-usd", "0.01", "--runs", str(runs)]
    assert main(argv) == 2
    assert "no call was made" in capsys.readouterr().err
    assert not runs.exists()  # refused before the run folder, before any call


def test_cli_dev_pilot_ids(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    runs = tmp_path / "runs"
    assert main(["run", "--set", "dev", "--ids", "d-02,dev:d-07", "--runs", str(runs)]) == 0
    (run,) = list(runs.iterdir())
    rows = RunLog(run, {}).rows()
    assert sorted(r["id"] for r in rows) == ["dev:d-02", "dev:d-07"]
    assert main(["run", "--set", "dev", "--ids", "d-999", "--runs", str(runs)]) == 2
    assert main(["run", "--set", "all", "--ids", "d-02", "--runs", str(runs)]) == 2
