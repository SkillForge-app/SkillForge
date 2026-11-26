"""python -m evaluation.contract export [--gap] | check   (see evaluation/contract/__init__.py)"""

import argparse
import asyncio
import sys

from core.llm import load_config
from core.llm.local_embed import ensure_model
from evaluation.contract.build import (
    OUT_DIR,
    build,
    check_ai16,
    check_gap_files,
    gap_examples,
    stale,
    write,
)


def _export(gap: bool) -> int:
    if gap:
        role = load_config().role("embedding")
        if role.local is not None:
            ensure_model(role.local)
        files = asyncio.run(gap_examples())
    else:
        files = asyncio.run(build())
        problems = check_ai16(files)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
    for path in write(files):
        print(path.relative_to(OUT_DIR.parent).as_posix())
    return 0


def _check() -> int:
    files = asyncio.run(build())
    problems = stale(files) + check_ai16(files) + check_gap_files()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print("run: python -m evaluation.contract export (and export --gap)", file=sys.stderr)
        return 1
    print(f"OK: {len(files)} generated files are current; gap examples valid")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.contract")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write the generated files")
    export.add_argument(
        "--gap", action="store_true", help="only the gap examples (local embedding model)"
    )
    commands.add_parser("check", help="exit 1 when a generated file is out of date")
    args = parser.parse_args(argv)
    if args.command == "export":
        return _export(args.gap)
    return _check()


if __name__ == "__main__":
    sys.exit(main())
