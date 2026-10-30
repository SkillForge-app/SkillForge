"""Safety screening evaluation (AI-06) command line.

python -m evaluation.safety check-data
python -m evaluation.safety run --set all --live       # real model calls, costs money
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.safety run --set benign --limit 5   # smoke
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from core.analysis.safety import PROMPT_ID
from core.llm import load_config
from evaluation.common import live_guard, model_for
from evaluation.safety.data import (
    FILES,
    SAFETY_DIR,
    SafetyEvalItem,
    SetName,
    check_data,
    load_file,
    load_set,
)
from evaluation.safety.evaluate import render_markdown, run_eval, write_report

RUNS_DIR = SAFETY_DIR / "runs"
TOKENS_PER_CALL = (2000, 150)


def check_data_command() -> int:
    issues = check_data()
    for split in FILES:
        f = load_file(split)
        banner = "  <-- INCOMPLETE" if f.status == "incomplete" else ""
        print(f"{FILES[split].name}: {len(f.requests)} items, status {f.status}{banner}")
    print(f"normal (analyzer sets): {len(load_set('normal'))} items")
    for issue in issues:
        print(f"  {issue.severity:<7} {issue}")
    errors = [i for i in issues if i.severity == "error"]
    print("FAIL" if errors else ("OK, but INCOMPLETE" if issues else "OK"))
    return 1 if errors else 0


def estimate_cost(calls: int) -> float | None:
    model = model_for(PROMPT_ID)
    info = load_config().info_for(model)
    if not info:
        return None
    tokens_in, tokens_out = TOKENS_PER_CALL
    per_call = tokens_in * info["input_cost_per_token"] + tokens_out * info["output_cost_per_token"]
    return round(calls * float(per_call), 2)


def run_command(args: argparse.Namespace) -> int:
    refused = live_guard(args.live, PROMPT_ID)
    if refused is not None:
        return refused
    names: list[SetName] = ["redteam", "benign", "normal"] if args.set == "all" else [args.set]
    sets: dict[str, Sequence[SafetyEvalItem]] = {
        name: load_set(name)[: args.limit] if args.limit else load_set(name) for name in names
    }
    calls = sum(len(items) for items in sets.values())
    if args.live:
        cost = estimate_cost(calls)
        print(f"about to make ~{calls} live calls" + (f", estimated ${cost}" if cost else ""))
    report, outcomes = asyncio.run(run_eval(sets, live=args.live, concurrency=args.concurrency))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = write_report(report, outcomes, args.out or RUNS_DIR / stamp)
    print(render_markdown(report))
    print(f"report written to {out}")
    return 0 if report.passed in (None, True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.safety")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate the safety sets and show what is missing")
    run = commands.add_parser("run", help="evaluate the safety screen")
    run.add_argument("--set", choices=["redteam", "benign", "dev", "normal", "all"], default="all")
    run.add_argument("--limit", type=int, default=0, help="only the first N of each set")
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--live", action="store_true", help="call the real model (costs money)")
    run.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
