"""Benchmark command line.

python -m evaluation.benchmarks validate [seed]
python -m evaluation.benchmarks release seed --version 0.1.0
python -m evaluation.benchmarks verify [seed]       # check committed releases are untouched
"""

import argparse
import sys

from evaluation.benchmarks.dataset import (
    BENCHMARKS_DIR,
    BenchmarkError,
    load_benchmark,
    verify_release,
    write_release,
)


def validate(name: str) -> int:
    skills, issues = load_benchmark(BENCHMARKS_DIR / name)
    for issue in issues:
        print(f"  {issue.severity:<7} {issue}")
    if issues:
        print(f"FAIL  {name}: {len(issues)} issue(s)")
        return 1
    print(
        f"OK  {name}: {len(skills)} skills, "
        f"{sum(len(s.test_prompts) for s in skills)} test prompts, "
        f"{sum(len(s.should_not_trigger) for s in skills)} should-not-trigger, "
        f"{sum(len(s.rubric) for s in skills)} rubric items, "
        f"{sum(len(s.requests) for s in skills)} labelled requests, "
        f"{sum(s.review.status == 'reviewed' for s in skills)} reviewed"
    )
    return 0


def release(name: str, version: str) -> int:
    try:
        result = write_release(BENCHMARKS_DIR / name, version)
    except BenchmarkError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"released {result.path}  dataset_sha256={result.manifest['dataset_sha256']}")
    return 0


def verify(name: str) -> int:
    releases = sorted((BENCHMARKS_DIR / name / "releases").glob("*/manifest.json"))
    failed = False
    for manifest in releases:
        issues = verify_release(manifest.parent)
        failed |= bool(issues)
        print(f"{'FAIL' if issues else 'OK'}  {manifest.parent.name}")
        for issue in issues:
            print(f"  {issue}")
    if not releases:
        print(f"no releases in {name}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.benchmarks")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("name", nargs="?", default="seed")
    rel = commands.add_parser("release")
    rel.add_argument("name")
    rel.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate(args.name)
    if args.command == "verify":
        return verify(args.name)
    return release(args.name, args.version)


if __name__ == "__main__":
    sys.exit(main())
