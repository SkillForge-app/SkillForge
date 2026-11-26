"""Skill Architect evaluation (AI-07) command line.

python -m evaluation.architect check-data
python -m evaluation.architect estimate --set all [--tokens-from <pilot run folder>]   # no calls
python -m evaluation.architect run --set all --live --budget-usd 30 --retry-errors   # costs money
python -m evaluation.architect run --set all --live --budget-usd 30 --retry-errors \
    --resume evaluation/architect/runs/<id>                     # after exit 5 (paused) or a crash
python -m evaluation.architect run --set dev --ids d-02,d-03 --live --budget-usd 2   # a pilot
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.architect run --set examples   # smoke test

Exit codes: 0 passed (or no gate), 1 gate failed, 2 refused before any call, 3 stopped by the
budget, 4 invalid (validity rule), 5 paused on a provider outage (resume it).

Every outcome is saved in the run folder as it finishes. If a run dies, `--resume <run folder>`
runs only the requests that have no outcome yet (same prompts, model, data and items, or it
refuses) and writes the report from everything saved.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from core.agents.architect import GENERATE
from evaluation.architect.data import GATE_SIZE, ArchitectItem, load_items
from evaluation.architect.estimate import Estimate, estimate
from evaluation.architect.evaluate import (
    PAUSE_AFTER,
    exit_code,
    render_markdown,
    run_eval,
    write_report,
)
from evaluation.architect.runlog import ResumeError
from evaluation.common import AI_ROOT, live_guard, output_dirs

REPORTS_DIR = AI_ROOT / "evaluation" / "architect" / "reports"  # tracked: .md + .json per live run
RUNS_DIR = AI_ROOT / "evaluation" / "architect" / "runs"  # ignored by Git: predictions + specs


def check_data_command() -> int:
    items = load_items("all")
    print(f"{len(items)} test requests ({sum(i.source == 'example' for i in items)} examples)")
    ok = len(items) == GATE_SIZE and all(i.analyzed.safety is not None for i in items)
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def estimate_cost(items: Sequence[ArchitectItem], tokens_from: Path | None) -> Estimate | None:
    try:
        return estimate(items, tokens_from=tokens_from)
    except LookupError as exc:
        print(f"no estimate: {exc}", file=sys.stderr)
        return None


def items_for(args: argparse.Namespace) -> list[ArchitectItem] | None:
    items = load_items(args.set)
    if args.ids:
        chosen = select(items, args.ids)
        if chosen is None:
            print(f"--ids names a request that is not in the {args.set} set", file=sys.stderr)
            return None
        items = chosen
    return items[: args.limit] if args.limit else items


def estimate_command(args: argparse.Namespace) -> int:
    items = items_for(args)
    if items is None:
        return 2
    cost = estimate_cost(items, args.tokens_from)
    if cost is None:
        return 2
    print("\n".join(cost.lines()))
    return 0


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
    items = items_for(args)
    if items is None:
        return 2
    sets: dict[str, Sequence[ArchitectItem]] = {args.set: items}
    if args.live:
        # As AI-05: refuse when the expected cost is over the budget. The high and worst cases
        # are shown; the budget cap is what bounds them during the run.
        cost = estimate_cost(items, args.tokens_from)
        print(f"about to design {len(items)} skills with live calls, budget ${args.budget_usd}")
        if cost is not None:
            print("\n".join("  " + line for line in cost.lines()))
        if cost is None or cost.expected_usd > args.budget_usd:
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
    which = argparse.ArgumentParser(add_help=False)  # the requests, for run and estimate
    which.add_argument(
        "--set",
        choices=["examples", "gate", "all", "dev"],
        default="all",
        help="all = the 103 gate requests; dev = the analyzer's dev requests (pilots only)",
    )
    which.add_argument("--ids", default="", help="only these requests, e.g. d-02,d-03 (pilots)")
    which.add_argument("--limit", type=int, default=0)
    which.add_argument(
        "--tokens-from",
        type=Path,
        default=None,
        help="a pilot's run folder: estimate from its measured tokens per call (calls.jsonl)",
    )
    commands.add_parser("estimate", parents=[which], help="what a run would cost (no model call)")
    run = commands.add_parser("run", parents=[which], help="evaluate the Skill Architect")
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
        "refuses to start when the expected estimate is over it, and stops calling once reached",
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
    if args.command == "estimate":
        return estimate_command(args)
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
