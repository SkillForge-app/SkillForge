"""Safety screening evaluation (AI-06) command line.

python -m evaluation.safety check-data
python -m evaluation.safety run --set all --live       # real model calls, costs money
SKILLFORGE_LLM_BACKEND=fake python -m evaluation.safety run --set benign --limit 5   # smoke

Writing the red-team and dev block items (LABELLING.md):
python -m evaluation.safety plan-slots                 # the slots still to fill
python -m evaluation.safety seeds --datasets DIR       # dataset seeds for the adapted slots
python -m evaluation.safety generate --live            # non-Claude candidates, costs money
python -m evaluation.safety review --reviewer ziad     # accept, edit or reject each one
python -m evaluation.safety review --reviewer ziad --manual   # child_safety, by hand
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from core.analysis.safety import PROMPT_ID
from core.llm import load_config
from core.llm.config import key_env_for
from evaluation.common import AI_ROOT, live_guard, model_for, output_dirs
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
from evaluation.safety.slots import Split, plan_slots

REPORTS_DIR = SAFETY_DIR / "reports"  # tracked: one .md + .json per live run
RUNS_DIR = SAFETY_DIR / "runs"  # ignored by Git: predictions.jsonl per run
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
    reports_dir, run_dir = output_dirs(
        args.live, args.out, args.runs, reports_dir=REPORTS_DIR, runs_dir=RUNS_DIR
    )
    files = write_report(report, outcomes, label=args.set, reports_dir=reports_dir, run_dir=run_dir)
    print(render_markdown(report))
    print(f"report written to {files.md} and {files.json.name}; predictions in {files.run}")
    return 0 if report.passed in (None, True) else 1


def plan_slots_command() -> int:
    from evaluation.safety.generate import open_slots, read_candidates

    candidates = read_candidates()
    for split in ("redteam", "dev"):
        slots = plan_slots(split)
        still = {s.id for s in open_slots(split, candidates)}
        print(f"{FILES[split].name}: {len(slots)} slots, {len(still)} open")
        for s in slots:
            mark = "open" if s.id in still else "done or waiting for review"
            how = "by hand" if s.manual else s.origin
            print(f"  {s.id:<6} {s.category:<21} {s.attack:<18} {how:<10} {mark}")
    return 0


def seeds_command(args: argparse.Namespace) -> int:
    from evaluation.safety.seeds import load_seeds, select_seeds, write_seeds

    seeds = load_seeds(args.datasets)
    slots = plan_slots("redteam") + plan_slots("dev")
    picked = select_seeds(slots, seeds)
    write_seeds(picked)
    adapted = [s.id for s in slots if s.origin == "adapted"]
    missing = sorted(set(adapted) - {s.slot for s in picked if s.slot})
    print(
        f"{len(seeds)} usable rows in {args.datasets}; seeds for {len(picked)} of "
        f"{len(adapted)} adapted slots"
    )
    if missing:
        print("no seed in their category for: " + ", ".join(missing))
    return 0


def generate_command(args: argparse.Namespace) -> int:
    from evaluation.safety.generate import (
        GENERATOR_PROMPTS,
        ROLE,
        generate,
        generator_config,
        open_slots,
        read_candidates,
    )
    from evaluation.safety.seeds import read_seeds

    config = generator_config()  # refuses a Claude model anywhere in the chain
    splits: list[Split] = ["redteam", "dev"] if args.split == "all" else [args.split]
    existing = read_candidates()
    todo = len([s for split in splits for s in open_slots(split, existing) if not s.manual])
    model = config.role(ROLE).model
    if not args.live:
        print(f"refusing to call {model} without --live (it costs money): about {todo} calls")
        return 2
    load_dotenv(AI_ROOT / ".env", override=False)
    key = key_env_for(model)
    if key and not os.environ.get(key):
        print(f"--live needs {key} for {model} (env var or ai/.env)")
        return 2
    from core.llm.litellm_gateway import LiteLLMGateway

    gateway = LiteLLMGateway(config=config, prompts_root=GENERATOR_PROMPTS)
    seeds = read_seeds()
    for split in splits:
        result = asyncio.run(generate(split, gateway, seeds=seeds, limit=args.limit))
        kept = [c for c in result.candidates if c.status == "pending"]
        print(
            f"{split}: {result.calls} calls, {len(kept)} candidates to review, "
            f"{len(result.candidates) - len(kept)} filtered, ${result.cost_usd:.4f}"
        )
        for c in result.candidates:
            if c.status == "filtered":
                print(f"  filtered {c.slot}: {c.reason}")
        for note in result.skipped:
            print(f"  skipped {note}")
    return 0


def precheck_command(args: argparse.Namespace) -> int:
    from collections import Counter

    from evaluation.safety.generate import GENERATOR_PROMPTS, read_candidates
    from evaluation.safety.precheck import GUARD_ROLE, guard_config, precheck, read_results

    config = guard_config()  # refuses a Claude or Qwen model anywhere in the chain
    model = config.role(GUARD_ROLE).model
    done = read_results()
    todo = [
        c
        for c in read_candidates()
        if c.status == "pending" and c.cid not in done and c.category != "child_safety"
    ]
    if not args.live:
        print(f"refusing to call {model} without --live (it costs money): {len(todo)} candidates")
        return 2
    load_dotenv(AI_ROOT / ".env", override=False)
    key = key_env_for(model)
    if key and not os.environ.get(key):
        print(f"--live needs {key} for {model} (env var or ai/.env)")
        return 2
    from core.llm.litellm_gateway import LiteLLMGateway

    gateway = LiteLLMGateway(config=config, prompts_root=GENERATOR_PROMPTS)
    result = asyncio.run(precheck(gateway, limit=args.limit))
    verdicts = Counter(r.verdict for r in result.checked)
    flagged = [r for r in result.checked if r.flags]
    classifiers = ", ".join(sorted({str(r.classifier) for r in result.checked}))
    print(
        f"{result.calls} calls by {classifiers}: "
        f"{verdicts['unsafe']} unsafe, {verdicts['safe']} safe; {len(flagged)} flagged; "
        f"{len(result.skipped)} skipped; ${result.cost_usd:.4f}"
    )
    for note in result.skipped:
        print(f"  skipped {note}")
    return 0


def review_command(args: argparse.Namespace) -> int:
    from evaluation.safety.review import review

    counts = review(args.split, args.reviewer, manual=args.manual)
    print(", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "nothing to review")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.safety")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate the safety sets and show what is missing")
    run = commands.add_parser("run", help="evaluate the safety screen")
    run.add_argument("--set", choices=["redteam", "benign", "dev", "normal", "all"], default="all")
    run.add_argument("--limit", type=int, default=0, help="only the first N of each set")
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--live", action="store_true", help="call the real model (costs money)")
    run.add_argument(
        "--out", type=Path, default=None, help="report folder (default: reports/ for --live runs)"
    )
    run.add_argument("--runs", type=Path, default=None, help="raw outputs folder (default: runs/)")
    commands.add_parser("plan-slots", help="the red-team and dev block slots still to fill")
    seeds = commands.add_parser("seeds", help="pick dataset seeds for the adapted slots")
    seeds.add_argument("--datasets", type=Path, required=True, help="folder with the datasets")
    gen = commands.add_parser("generate", help="red-team candidates from a non-Claude model")
    gen.add_argument("--split", choices=["redteam", "dev", "all"], default="all")
    gen.add_argument("--limit", type=int, default=0, help="at most N model calls per split")
    gen.add_argument("--live", action="store_true", help="call the real model (costs money)")
    pre = commands.add_parser("precheck", help="flag-only Llama Guard check before review")
    pre.add_argument("--limit", type=int, default=0, help="at most N model calls")
    pre.add_argument("--live", action="store_true", help="call the real model (costs money)")
    rev = commands.add_parser("review", help="accept, edit or reject each candidate")
    rev.add_argument("--reviewer", choices=["ziad", "yousef"], required=True)
    rev.add_argument("--split", choices=["redteam", "dev"], default="redteam")
    rev.add_argument("--manual", action="store_true", help="write child_safety items by hand")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    if args.command == "plan-slots":
        return plan_slots_command()
    if args.command == "seeds":
        return seeds_command(args)
    if args.command == "generate":
        return generate_command(args)
    if args.command == "precheck":
        return precheck_command(args)
    if args.command == "review":
        return review_command(args)
    return run_command(args)


if __name__ == "__main__":
    sys.exit(main())
