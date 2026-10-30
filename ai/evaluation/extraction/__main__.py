"""AI-10 extraction tools. No network: every page is a saved fixture.

python -m evaluation.extraction check-data
python -m evaluation.extraction report [--sample 20] [--seed 7] [--out DIR] [--no-site-boilerplate]
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from evaluation.extraction.data import load_pages
from evaluation.extraction.report import GATES, REPORTS_DIR, SAMPLE_SIZE, evaluate, write_report


def check_data_command() -> int:
    pages = load_pages()
    expected = Counter(", ".join(p.expected) or "ok" for p in pages)
    real = sum(not p.synthetic for p in pages)
    facts = sum(len(p.must_contain) for p in pages)
    print(f"{len(pages)} pages ({real} real, {len(pages) - real} synthetic); {facts} facts")
    print("expected:", dict(sorted(expected.items())))
    print("OK")
    return 0


def report_command(args: argparse.Namespace) -> int:
    report = evaluate(
        sample_size=args.sample, seed=args.seed, site_boilerplate=args.site_boilerplate
    )
    md_path, json_path = write_report(report, args.out)
    for name, floor in GATES.items():
        value = report.checks[name]
        print(f"{name:15} {value:7.1%}  (gate {floor:.0%})  {'ok' if value >= floor else 'FAIL'}")
    print(f"{'leaks':15} {report.leaks:7d}  (gate 0)     {'ok' if report.leaks == 0 else 'FAIL'}")
    print(f"automatic gates: {'PASS' if report.gates_passed else 'FAIL'}")
    print(f"wrote {md_path} and {json_path}")
    print("Next: a person reviews the sampled chunks in the .md file.")
    return 0 if report.gates_passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.extraction")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate pages.yaml against the saved pages")
    report = commands.add_parser("report", help="run the checks and write the review sheet")
    report.add_argument("--sample", type=int, default=SAMPLE_SIZE, help="chunks to sample")
    report.add_argument("--seed", type=int, default=7, help="random seed for the sample")
    report.add_argument("--out", type=Path, default=REPORTS_DIR, help="output folder")
    report.add_argument(
        "--no-site-boilerplate",
        dest="site_boilerplate",
        action="store_false",
        help="keep sentences repeated across pages of one site (removed by default)",
    )
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    return report_command(args)


if __name__ == "__main__":
    sys.exit(main())
