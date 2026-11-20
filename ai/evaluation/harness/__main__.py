"""AI-16 paired benchmark and judge-calibration commands.

python -m evaluation.harness run --release <release-dir> --skill <name> --instructions <file> --live
python -m evaluation.harness calibrate --release <release-dir> --skill <name> \
  --labels <jsonl> --live
"""

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from core.llm import load_prompt, track_usage
from evaluation.common import AI_ROOT, model_for
from evaluation.harness.data import load_calibration, load_skill
from evaluation.harness.evaluate import calibrate_judge, run_benchmark, write_report

RUNS_DIR = AI_ROOT / "evaluation" / "harness" / "runs"


def _reserve_output_dir(requested: Path | None, *, suffix: str = "") -> Path:
    if requested is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        requested = RUNS_DIR / f"{stamp}{suffix}"
    requested.mkdir(parents=True, exist_ok=False)
    return requested


def _run(args: argparse.Namespace) -> int:
    if args.limit < 0:
        print("--limit must be zero (all prompts) or a positive integer", file=sys.stderr)
        return 2
    benchmark = load_skill(args.release, args.skill)
    if args.limit:
        benchmark = replace(benchmark, prompts=benchmark.prompts[: args.limit])
    try:
        instructions = args.instructions.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read compiled skill instructions: {exc}", file=sys.stderr)
        return 2
    out = _reserve_output_dir(args.out)
    print(
        f"Starting {len(benchmark.prompts)} prompts: "
        f"{2 * len(benchmark.prompts)} answers and up to "
        f"{2 * len(benchmark.prompts)} judge calls. Live calls incur provider cost."
    )
    report, results = asyncio.run(
        run_benchmark(
            benchmark,
            instructions,
            live=args.live,
            concurrency=args.concurrency,
        )
    )
    write_report(report, results, out, reserved=True)
    print(f"report and answers written to {out}")
    print("judge-human agreement is pending calibration against reviewed human labels")
    return 0 if report.metrics["completed"] == report.metrics["n"] else 1


def _calibrate(args: argparse.Namespace) -> int:
    benchmark = load_skill(args.release, args.skill)
    labels = load_calibration(args.labels)
    out = _reserve_output_dir(args.out, suffix="-calibration")
    with track_usage() as usage:
        result, rows = asyncio.run(
            calibrate_judge(benchmark, labels, live=args.live, concurrency=args.concurrency)
        )
    report = {
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": benchmark.dataset,
        "dataset_version": benchmark.version,
        "dataset_sha256": benchmark.dataset_sha256,
        "skill": benchmark.skill.name,
        "live": args.live,
        "human_labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
        "judge_prompt_version": load_prompt("evaluation/judge").version,
        "judge_model": model_for("evaluation/judge"),
        "usage": {
            "calls": usage.calls,
            "errors": usage.errors,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(usage.cost_usd, 4),
        },
        "result": asdict(result),
    }
    with (out / "calibration.json").open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    with (out / "comparisons.jsonl").open("x", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        f"judge-human agreement: "
        f"{'n/a' if result.agreement is None else f'{result.agreement:.1%}'} "
        f"({result.matches}/{result.n}); "
        f"{'PASSED' if result.passed else 'NOT PASSED'}"
    )
    print(f"calibration results written to {out}")
    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.harness")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser(
        "run", help="run every test prompt with and without skill instructions"
    )
    run.add_argument(
        "--release", type=Path, required=True, help="verified immutable benchmark release"
    )
    run.add_argument("--skill", required=True)
    run.add_argument(
        "--instructions", type=Path, required=True, help="compiled Claude or Codex instruction file"
    )
    run.add_argument(
        "--limit", type=int, default=0, help="run only the first N prompts (smoke test)"
    )
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--live", action="store_true", help="make real model calls (costs money)")
    run.add_argument("--out", type=Path)

    calibration = commands.add_parser("calibrate", help="measure judge agreement with human labels")
    calibration.add_argument("--release", type=Path, required=True)
    calibration.add_argument("--skill", required=True)
    calibration.add_argument(
        "--labels", type=Path, required=True, help="reviewed human-label JSONL"
    )
    calibration.add_argument("--concurrency", type=int, default=2)
    calibration.add_argument(
        "--live", action="store_true", help="make real judge calls (costs money)"
    )
    calibration.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        return _calibrate(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
