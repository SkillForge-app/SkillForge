"""AI-25: experiments reproducible from tracked runs.

python -m evaluation.reproduce check   # registry vs committed reports and inputs (seconds; CI)
python -m evaluation.reproduce list    # live experiments: command, model, prompt, cost (no calls)
"""

import argparse
import sys

from evaluation.reproduce.check import check, repo_root
from evaluation.reproduce.registry import AI_DIR, RegistryError, load_registry


def check_command() -> int:
    try:
        registry = load_registry()
    except RegistryError as exc:
        print(exc, file=sys.stderr)
        return 1
    result = check(registry, repo_root(AI_DIR))
    for issue in result.issues:
        print(f"  {issue}")
    print(
        f"{len(result.checked)} entries checked; {len(result.pending_skipped)} pending-merge "
        f"skipped (report not on this branch): {', '.join(result.pending_skipped) or '-'}"
    )
    print("FAIL" if result.issues else "OK")
    return 1 if result.issues else 0


def list_command() -> int:
    registry = load_registry()
    print("Live experiments (paid model calls; never re-run by this tool):")
    for e in registry.experiments:
        if e.kind != "live":
            continue
        cost = "n/a" if e.cost_usd is None else f"${e.cost_usd}"
        status = "" if e.status == "active" else f" [pending-merge: {e.branch}]"
        print(f"- {e.id}{status}: {e.prompt or '-'}, {e.model or '-'}, {cost}")
        print(f"    {' '.join(e.command or [])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.reproduce")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="the registry agrees with the committed reports")
    commands.add_parser("list", help="the live experiments, with command and cost")
    args = parser.parse_args(argv)
    return check_command() if args.command == "check" else list_command()


if __name__ == "__main__":
    sys.exit(main())
