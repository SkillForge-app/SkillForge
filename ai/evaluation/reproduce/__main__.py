"""AI-25: experiments reproducible from tracked runs.

python -m evaluation.reproduce check   # registry vs committed reports and inputs (seconds; CI)
python -m evaluation.reproduce list    # live experiments: command, model, prompt, cost (no calls)
python -m evaluation.reproduce run [--only E1,E5] [--no-model]   # offline re-runs, compared exactly
"""

import argparse
import json
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
    finals = sum(e.role == "final" for e in registry.experiments)
    not_run = [i for i in result.final_not_run if i not in result.final_pending]
    which = [f"pending-merge: {', '.join(result.final_pending)}"] if result.final_pending else []
    which += [f"not run: {', '.join(not_run)}"] if not_run else []
    print(
        f"done-when: {finals} final entries: {len(result.final_reproduces)} reproduce, "
        f"{len(result.final_not_run)} not run yet ({'; '.join(which) or '-'})"
    )
    if result.pending_arrived:
        print(
            "pending-merge entries whose report is here (checked fully; set status: active): "
            + ", ".join(result.pending_arrived)
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


def run_command(only: list[str], no_model: bool) -> int:
    from evaluation.reproduce.run import TEMP_ROOT, reproduce

    registry = load_registry()
    rows = []
    for outcome, lock in reproduce(registry, repo_root(AI_DIR), only=only, no_model=no_model):
        rows.append({**outcome.__dict__, "lock": lock})
        print(
            f"{outcome.status.upper():8} {outcome.entry} ({outcome.seconds:.0f}s) {outcome.detail}"
        )
        for d in outcome.diffs:
            print(f"           {d}")
        if outcome.report_sha256:
            print(f"           report_sha256: {outcome.report_sha256}")
    summary = TEMP_ROOT / "last-run.json"
    summary.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    bad = [r for r in rows if r["status"] in ("differs", "error")]
    print(
        f"{len(rows)} entries: {sum(r['status'] == 'match' for r in rows)} match, "
        f"{len(bad)} differ or fail, {sum(r['status'] == 'skipped' for r in rows)} skipped. "
        f"Summary: {summary}"
    )
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.reproduce")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="the registry agrees with the committed reports")
    commands.add_parser("list", help="the live experiments, with command and cost")
    run = commands.add_parser("run", help="re-run offline experiments at their recorded commit")
    run.add_argument("--only", default="", help="comma-separated entry ids or experiments (E1)")
    run.add_argument("--no-model", action="store_true", help="skip entries that need a model")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command([x for x in args.only.split(",") if x], args.no_model)
    return check_command() if args.command == "check" else list_command()


if __name__ == "__main__":
    sys.exit(main())
