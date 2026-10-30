"""Request Analyzer evaluation (AI-05) command line.

python -m evaluation.analyzer check-data
python -m evaluation.analyzer run --set gate --live          # real model calls, costs money
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.analyzer run --set gate --limit 5   # smoke test
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from core.llm import load_config, load_prompt
from core.llm.config import key_env_for
from core.llm.gateway import BACKEND_ENV
from evaluation.analyzer.data import (
    ANALYZER_DIR,
    EvalItem,
    SetName,
    check_data,
    gate_coverage,
    load_set,
)
from evaluation.analyzer.evaluate import render_markdown, run_eval, write_report

RUNS_DIR = ANALYZER_DIR / "runs"
TOKENS_PER_CALL = (1500, 500)  # rough input/output size of one analysis call


def check_data_command() -> int:
    issues = check_data()
    for issue in issues:
        print(f"  {issue}")
    c = gate_coverage()
    print(
        f"gate: {c.size} requests; kinds {c.kinds}; risks {c.risks}; styles {c.styles}; "
        f"{c.with_targets} name a platform"
    )
    print(f"dev: {len(load_set('dev'))}; arabic: {len(load_set('arabic'))}")
    print("FAIL" if issues else "OK")
    return 1 if issues else 0


def _model_and_key() -> tuple[str, str | None]:
    model = load_config().role(load_prompt("analysis/request").meta.model_role).model
    return model, key_env_for(model)


def estimate_cost(calls: int) -> float | None:
    model, _ = _model_and_key()
    info = load_config().info_for(model)
    if not info:
        return None
    tokens_in, tokens_out = TOKENS_PER_CALL
    per_call = tokens_in * info["input_cost_per_token"] + tokens_out * info["output_cost_per_token"]
    return round(calls * float(per_call), 2)


def run_command(args: argparse.Namespace) -> int:
    backend = os.environ.get(BACKEND_ENV, "litellm").strip().lower()
    if args.live:
        load_dotenv(ANALYZER_DIR.parents[1] / ".env", override=False)
        model, key = _model_and_key()
        if key and not os.environ.get(key):
            print(f"--live needs {key} for {model} (env var or ai/.env)", file=sys.stderr)
            return 2
        if backend == "fake":
            print(f"--live cannot be used with {BACKEND_ENV}=fake", file=sys.stderr)
            return 2
    elif backend != "fake":
        print(
            "refusing to call a real model without --live (it costs money). "
            f"For a smoke test set {BACKEND_ENV}=fake.",
            file=sys.stderr,
        )
        return 2

    names: list[SetName] = ["gate", "dev", "arabic"] if args.set == "all" else [args.set]
    sets: dict[str, Sequence[EvalItem]] = {
        name: load_set(name)[: args.limit] if args.limit else load_set(name) for name in names
    }
    calls = sum(len(items) for items in sets.values())
    if args.live:
        cost = estimate_cost(calls)
        print(f"about to make ~{calls} live calls" + (f", estimated ${cost}" if cost else ""))

    report, predictions = asyncio.run(run_eval(sets, live=args.live, concurrency=args.concurrency))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = write_report(report, predictions, args.out or RUNS_DIR / stamp)
    print(render_markdown(report))
    print(f"report written to {out}")
    return 0 if report.passed in (None, True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.analyzer")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate the labelled requests and show coverage")
    run = commands.add_parser("run", help="evaluate the analyzer")
    run.add_argument("--set", choices=["gate", "dev", "arabic", "all"], default="gate")
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
