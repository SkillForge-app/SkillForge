"""Skill Architect evaluation (AI-07) command line.

python -m evaluation.architect check-data
python -m evaluation.architect run --set all --live              # real model calls, costs money
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.architect run --set examples   # smoke test
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from core.agents.architect import GENERATE, MAX_ATTEMPTS
from core.llm import load_config
from evaluation.architect.data import GATE_SIZE, ArchitectItem, load_items
from evaluation.architect.evaluate import render_markdown, run_eval, write_report
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


def run_command(args: argparse.Namespace) -> int:
    refused = live_guard(args.live, GENERATE)
    if refused is not None:
        return refused
    items = load_items(args.set)
    if args.limit:
        items = items[: args.limit]
    sets: dict[str, Sequence[ArchitectItem]] = {args.set: items}
    if args.live:
        cost = estimate_cost(len(items))
        span = f", estimated ${cost[0]} to ${cost[1]}" if cost else ""
        print(f"about to design {len(items)} skills with live calls{span}")
    report, outcomes = asyncio.run(
        run_eval(sets, live=args.live, end_to_end=args.end_to_end, concurrency=args.concurrency)
    )
    reports_dir, run_dir = output_dirs(
        args.live, args.out, args.runs, reports_dir=REPORTS_DIR, runs_dir=RUNS_DIR
    )
    files = write_report(report, outcomes, label=args.set, reports_dir=reports_dir, run_dir=run_dir)
    print(render_markdown(report))
    print(f"report written to {files.md} and {files.json.name}; generated specs in {files.run}")
    return 0 if report.passed in (None, True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.architect")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="build the 103 test requests and check them")
    run = commands.add_parser("run", help="evaluate the Skill Architect")
    run.add_argument("--set", choices=["examples", "gate", "all"], default="all")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--end-to-end", action="store_true", help="run analyzer + screen first")
    run.add_argument("--live", action="store_true", help="call the real model (costs money)")
    run.add_argument(
        "--out", type=Path, default=None, help="report folder (default: reports/ for --live runs)"
    )
    run.add_argument("--runs", type=Path, default=None, help="raw outputs folder (default: runs/)")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
