"""Skill Architect evaluation (AI-07) command line.

python -m evaluation.architect check-data
python -m evaluation.architect run --set all --live --budget-usd 30 --retry-errors   # costs money
python -m evaluation.architect run --set all --live --budget-usd 30 --retry-errors \
    --resume evaluation/architect/runs/<id>                     # after exit 5 (paused) or a crash
python -m evaluation.architect run --set dev --ids d-02,d-03 --live --budget-usd 2   # a pilot

Exit codes: 0 passed (or no gate), 1 gate failed, 2 refused before any call, 3 stopped by the
budget, 4 invalid (validity rule), 5 paused on a provider outage (resume it).
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.architect run --set examples   # smoke test

Every outcome is saved in the run folder as it finishes. If a run dies, `--resume <run folder>`
runs only the requests that have no outcome yet (same prompts, model, data and items, or it
refuses) and writes the report from everything saved.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from core.agents.architect import GENERATE, MAX_ATTEMPTS
from core.llm import load_config
from evaluation.architect.data import GATE_SIZE, ArchitectItem, load_items
from evaluation.architect.evaluate import (
    PAUSE_AFTER,
    exit_code,
    render_markdown,
    run_eval,
    write_report,
)
from evaluation.architect.runlog import ResumeError
from evaluation.common import AI_ROOT, live_guard, model_for, output_dirs

REPORTS_DIR = AI_ROOT / "evaluation" / "architect" / "reports"  # tracked: .md + .json per live run
RUNS_DIR = AI_ROOT / "evaluation" / "architect" / "runs"  # ignored by Git: predictions + specs
TOKENS_PER_CALL = (6000, 8000)  # rough input/output of one Architect call (spec + thinking)


def check_data_command() -> int:
    items = load_items("all")
    print(f"{len(items)} test requests ({sum(i.source == 'example' for i in items)} examples)")
    ok = len(items) == GATE_SIZE and all(i.analyzed.safety is not None for i in items)
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def estimate_cost(requests: int) -> tuple[float, float] | None:
    info = load_config().info_for(model_for(GENERATE))
    if not info:
        return None
    tokens_in, tokens_out = TOKENS_PER_CALL
    per_call = float(
        tokens_in * info["input_cost_per_token"] + tokens_out * info["output_cost_per_token"]
    )
    return round(requests * per_call, 2), round(requests * MAX_ATTEMPTS * per_call, 2)


def select(items: list[ArchitectItem], ids: str) -> list[ArchitectItem] | None:
    """The items named in `ids` ("dev:d-02,d-03": with or without the set prefix), in the
    set's order; None when a name matches no item."""
    wanted = [x.strip() for x in ids.split(",") if x.strip()]
    by_name = {i.id: i for i in items} | {i.id.split(":", 1)[1]: i for i in items}
    if any(w not in by_name for w in wanted):
        return None
    chosen = {by_name[w].id for w in wanted}
    return [i for i in items if i.id in chosen]


def run_command(args: argparse.Namespace) -> int:
    refused = live_guard(args.live, GENERATE)
    if refused is not None:
        return refused
    if args.budget_usd is not None and args.budget_usd <= 0:
        print("--budget-usd must be more than 0", file=sys.stderr)
        return 2
    if args.live and args.budget_usd is None:
        print("--live needs --budget-usd (the most this run may spend)", file=sys.stderr)
        return 2
    items = load_items(args.set)
    if args.ids:
        chosen = select(items, args.ids)
        if chosen is None:
            print(f"--ids names a request that is not in the {args.set} set", file=sys.stderr)
            return 2
        items = chosen
    if args.limit:
        items = items[: args.limit]
    sets: dict[str, Sequence[ArchitectItem]] = {args.set: items}
    if args.live:
        cost = estimate_cost(len(items))
        shown = "unknown" if cost is None else f"${cost[0]} expected, ${cost[1]} high"
        print(
            f"about to design {len(items)} skills with live calls, estimated {shown}, "
            f"budget ${args.budget_usd}"
        )
        if cost is None or cost[1] > args.budget_usd:
            print("the estimate is unknown or over the budget: no call was made", file=sys.stderr)
            return 2
    if args.resume is not None:
        run_dir = args.resume
        reports_dir = args.out or (REPORTS_DIR if args.live else run_dir)
    else:  # the run folder exists before the first call: nothing paid for is kept only in memory
        reports_dir, run_dir = output_dirs(
            args.live, args.out, args.runs, reports_dir=REPORTS_DIR, runs_dir=RUNS_DIR
        )
    print(f"run folder: {run_dir} (if the run dies: --resume {run_dir})")
    try:
        report, _ = asyncio.run(
            run_eval(
                sets,
                live=args.live,
                run_dir=run_dir,
                label=args.set,
                resume=args.resume is not None,
                end_to_end=args.end_to_end,
                concurrency=args.concurrency,
                budget_usd=args.budget_usd,
                retry_errors=args.retry_errors,
                pause_after=args.pause_after,
            )
        )
    except ResumeError as exc:
        print(exc, file=sys.stderr)
        return 2
    files = write_report(report, label=args.set, reports_dir=reports_dir, run_dir=run_dir)
    print(render_markdown(report))
    print(f"report written to {files.md} and {files.json.name}; generated specs in {files.run}")
    if report.paused or report.missing:
        print(f"to continue: --resume {run_dir}")
    return exit_code(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.architect")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="build the 103 test requests and check them")
    run = commands.add_parser("run", help="evaluate the Skill Architect")
    run.add_argument(
        "--set",
        choices=["examples", "gate", "all", "dev"],
        default="all",
        help="all = the 103 gate requests; dev = the analyzer's dev requests (pilots only)",
    )
    run.add_argument("--ids", default="", help="only these requests, e.g. d-02,d-03 (pilots)")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--end-to-end", action="store_true", help="run analyzer + screen first")
    run.add_argument("--live", action="store_true", help="call the real model (costs money)")
    run.add_argument(
        "--out", type=Path, default=None, help="report folder (default: reports/ for --live runs)"
    )
    run.add_argument("--runs", type=Path, default=None, help="raw outputs folder (default: runs/)")
    run.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="continue this run folder: only requests with no saved outcome are run",
    )
    run.add_argument(
        "--budget-usd",
        type=float,
        default=None,
        help="the most this run may spend (all segments); required with --live. The run "
        "refuses to start when the high estimate is over it, and stops calling once reached",
    )
    run.add_argument(
        "--retry-errors",
        action="store_true",
        help="retry each request that ended in a provider error once, at the end of the "
        "segment; the report records the rule and every retry",
    )
    run.add_argument(
        "--pause-after",
        type=int,
        default=PAUSE_AFTER,
        help=f"pause the run after this many provider errors in a row (default {PAUSE_AFTER}; "
        "0: never)",
    )
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
