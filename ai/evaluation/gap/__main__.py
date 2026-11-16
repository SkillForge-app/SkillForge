"""AI-08 Gap Checker tools. The model runs locally (no key); the first run downloads it.

python -m evaluation.gap check-data
python -m evaluation.gap tune      # dev only: picks the text variant and both thresholds
python -m evaluation.gap report    # test, once: refuses draft labels or untuned settings
"""

import argparse
import asyncio
import sys
from collections import Counter

from core.analysis import load_settings
from core.llm import load_config
from core.llm.local_embed import ensure_model
from evaluation.gap.data import check_data, load_fixture_cards, load_pairs
from evaluation.gap.report import run_test, tune, winner, write_test_report, write_tuning


def check_data_command() -> int:
    cards = load_fixture_cards()
    sets = [load_pairs("dev"), load_pairs("test")]
    print(f"{len(cards)} skill cards ({Counter(c.source for c in cards)})")
    for s in sets:
        labels = Counter(r.best_label for r in s.requests)
        print(f"{s.split}: {len(s.requests)} requests {dict(labels)}; labels {s.review.status}")
    problems = check_data(cards, sets)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    print("OK")
    return 0


def _model_ready() -> None:
    role = load_config().role("embedding")
    if role.local is not None:
        ensure_model(role.local)


def tune_command() -> int:
    _model_ready()
    dev, cards = load_pairs("dev"), load_fixture_cards()
    results = asyncio.run(tune(dev, cards))
    for r in results:
        print(
            f"{r.name:22} exists>={r.exists_threshold} P {r.exists.precision:.2f} "
            f"R {r.exists.recall:.2f} | similar>={r.similar_threshold} "
            f"P {r.related.precision:.2f} R {r.related.recall:.2f}"
        )
    md, _ = write_tuning(dev, cards, results)
    print(f"chosen: {winner(results).name}; wrote {md} and core/analysis/gap_checker.yaml")
    return 0


def report_command() -> int:
    load_settings.cache_clear()
    settings = load_settings()
    test = load_pairs("test")
    if settings.tuned_on.startswith("not tuned"):
        print("the settings are not tuned yet: run `tune` on dev first", file=sys.stderr)
        return 2
    if test.review.status != "reviewed":
        print("the test labels are still draft: a person must review them first", file=sys.stderr)
        return 2
    _model_ready()
    cards = load_fixture_cards()
    result = asyncio.run(run_test(test, cards, settings))
    md, _ = write_test_report(test, cards, result)
    e = result.exists
    print(f"exists: precision {e.precision:.1%} recall {e.recall:.1%}; wrote {md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.gap")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate the cards and the labelled pairs")
    commands.add_parser("tune", help="choose the text variant and thresholds on dev")
    commands.add_parser("report", help="run the test split once with the tuned settings")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    if args.command == "tune":
        return tune_command()
    return report_command()


if __name__ == "__main__":
    sys.exit(main())
