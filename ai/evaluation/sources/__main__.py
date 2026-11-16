"""AI-09 source discovery tools. With SKILLFORGE_SEARCH=fake (the default) nothing is fetched.

python -m evaluation.sources check-data
python -m evaluation.sources review [--out DIR]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from core.knowledge.search import FakeSearchProvider, build_queries, load_registry
from evaluation.sources.review import REPORTS_DIR, build_review, seed_domains, write_review


def check_data_command() -> int:
    registry = load_registry()
    seeds = seed_domains()
    fake = FakeSearchProvider()
    missing = [
        q
        for domain, request in seeds.items()
        for q in build_queries(domain, request)
        if not fake.has(q)
    ]
    print(
        f"registry v{registry.version}: {len(registry.sources)} source rules, "
        f"{len(registry.blocked)} block rules; {len(seeds)} seed domains"
    )
    if missing:
        print(f"queries with no recorded results: {missing}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def review_command(args: argparse.Namespace) -> int:
    day, lists, checks = asyncio.run(build_review())
    md_path, json_path = write_review(day, lists, checks, args.out)
    for name, ok in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    print(f"wrote {md_path} and {json_path}")
    print("Next: a person judges the top 10 of each domain in the .md file.")
    return 0 if all(checks.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.sources")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate the registry and the recorded searches")
    review = commands.add_parser("review", help="write the review sheet for the 10 domains")
    review.add_argument("--out", type=Path, default=REPORTS_DIR, help="output folder")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    return review_command(args)


if __name__ == "__main__":
    sys.exit(main())
