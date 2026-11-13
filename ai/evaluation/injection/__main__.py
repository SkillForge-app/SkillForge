"""AI-19 prompt-injection evaluation. No network unless --llm --live is given.

python -m evaluation.injection check-data            # also checks every item attacks (slow)
python -m evaluation.injection check-data --quick    # the file checks only
python -m evaluation.injection report --split dev     # tune the rules on dev
python -m evaluation.injection report --split test    # once, after tuning: (a) and (b)
python -m evaluation.injection llm-plan --split test  # chunks and cost of the LLM screen; no calls
python -m evaluation.injection report --split test --llm --live    # adds (c): paid LLM calls
python -m evaluation.injection report --split test --llm --verdicts reports/llm-verdicts-....json
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from core.knowledge.injection_guard import (
    LLM_PROMPT_ID,
    InjectionVerdict,
    llm_flagged,
    screen_passages_llm,
)
from evaluation.common import live_guard
from evaluation.injection.data import check_data, load_set
from evaluation.injection.evaluate import Evaluator, check_items
from evaluation.injection.report import (
    HAIKU_PRICE_IN,
    HAIKU_PRICE_OUT,
    OUTPUT_TOKENS,
    gates,
    llm_plan,
    llm_summary,
    verdict,
    write_report,
    write_verdicts,
)


def check_data_command(args: argparse.Namespace) -> int:
    data = load_set()
    for split in ("dev", "test"):
        part = data.split(split)
        techniques = Counter(i.technique for i in part.injections)
        print(
            f"{split}: {len(part.injections)} injections over {len(techniques)} techniques, "
            f"{len(part.controls)} controls"
        )
    problems = check_data(data)
    if not problems and not args.quick:
        print("checking that every item attacks or reaches the chunks (extracts pages)...")
        problems = check_items(Evaluator(data))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("OK")
    return 0


def llm_plan_command(args: argparse.Namespace) -> int:
    """Print what the live LLM screen would cost. Never calls a model."""
    data = load_set()
    plan = llm_plan(Evaluator(data), data.split(args.split))
    low, high = plan.cost(args.price_in, args.price_out)
    calls = len(plan.passages)
    print(f"LLM screen on split {args.split}: {calls} calls, one per distinct chunk")
    print(f"  {plan.clean} chunks of the clean pages, {calls - plan.clean} only on injected pages")
    print(f"  input: about {plan.input_tokens:,} tokens (prompt + wrapped passage, chars / 3)")
    print(
        f"  output: {OUTPUT_TOKENS[0]} to {OUTPUT_TOKENS[1]} tokens per call "
        "(the JSON verdict alone; with adaptive thinking)"
    )
    print(
        f"  cost at ${args.price_in:.2f} / ${args.price_out:.2f} per million tokens: "
        f"${low:.2f} to ${high:.2f}"
    )
    print("no model was called. Run it with: report --split test --llm --live")
    return 0


def report_command(args: argparse.Namespace) -> int:
    if args.llm and args.verdicts is None and (code := live_guard(args.live, LLM_PROMPT_ID)):
        return code
    data = load_set()
    part = data.split(args.split)
    evaluator = Evaluator(data)
    llm = None
    if args.llm:
        plan = llm_plan(evaluator, part)
        if args.verdicts is not None:
            raw = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
            verdicts = {cid: InjectionVerdict.model_validate(v) for cid, v in raw.items()}
            missing = {p.chunk_id for p in plan.passages} - set(verdicts)
            if missing:
                print(f"{len(missing)} chunks have no saved verdict", file=sys.stderr)
                return 2
        else:
            verdicts = asyncio.run(screen_passages_llm(plan.passages, flagged_only=False))
            print(f"wrote {write_verdicts(args.split, verdicts)}")
        evaluator.llm_flags = {cid for cid, v in verdicts.items() if llm_flagged(v)}
        llm = llm_summary(evaluator, plan, verdicts)
    results = evaluator.run(part)
    paths = write_report(part, args.split, results, llm=llm)
    rows = gates(results)
    for gate in rows:
        mark = "    " if gate.passed is None else ("ok  " if gate.passed else "FAIL")
        print(f"{mark} [{gate.kind}] {gate.name}: {gate.value} (target {gate.target})")
    print(verdict(rows))
    print(f"wrote {paths[0]}")
    return 0 if rows[0].passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.injection")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-data", help="validate injections.yaml")
    check.add_argument("--quick", action="store_true", help="skip the checks that extract pages")
    plan = commands.add_parser("llm-plan", help="chunks and cost of the LLM screen (no calls)")
    plan.add_argument("--split", choices=["dev", "test"], required=True)
    plan.add_argument("--price-in", type=float, default=HAIKU_PRICE_IN, help="$ per 1M tokens")
    plan.add_argument("--price-out", type=float, default=HAIKU_PRICE_OUT, help="$ per 1M tokens")
    report = commands.add_parser("report", help="measure the defence and write the report")
    report.add_argument("--split", choices=["dev", "test"], required=True)
    report.add_argument("--llm", action="store_true", help="add the LLM screen: (c)")
    report.add_argument("--live", action="store_true", help="allow paid model calls (--llm)")
    report.add_argument("--verdicts", help="reuse a saved llm-verdicts JSON instead of calling")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command(args)
    if args.command == "llm-plan":
        return llm_plan_command(args)
    return report_command(args)


if __name__ == "__main__":
    sys.exit(main())
