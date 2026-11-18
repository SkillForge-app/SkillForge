"""AI-11 retrieval tools. Models run locally; the first run downloads the pinned model files.

python -m evaluation.retrieval check-data
python -m evaluation.retrieval run [--models NAMES|all] [--sizes 120,180,250] [--k 5]
python -m evaluation.retrieval build-index [--path DIR]   # the dev index: the 8 real pages
"""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from core.knowledge.ingest import Page, ingest_pages
from core.knowledge.store import LocalStore, VectorStore, store_from_env
from core.llm import load_config
from core.llm.local_embed import ensure_model
from evaluation.retrieval.data import indexed_pages, load_candidates, load_questions
from evaluation.retrieval.evaluate import CHUNK_SIZES, evaluate
from evaluation.retrieval.report import REPORTS_DIR, write_report


def check_data_command() -> int:
    question_set = load_questions()
    candidates = load_candidates()
    per_page = Counter(q.page for q in question_set.questions)
    print(f"{len(question_set.questions)} questions over {len(question_set.pages)} pages")
    print("per page:", dict(sorted(per_page.items())))
    print("candidates:", ", ".join(f"{n} ({c.dimensions}d)" for n, c in candidates.items()))
    print("OK")
    return 0


def run_command(args: argparse.Namespace) -> int:
    question_set = load_questions()
    candidates = load_candidates()
    if args.models != "all":
        names = args.models.split(",")
        unknown = sorted(set(names) - set(candidates))
        if unknown:
            print(f"unknown models: {unknown}; known: {sorted(candidates)}", file=sys.stderr)
            return 2
        candidates = {n: candidates[n] for n in names}
    sizes = [int(s) for s in args.sizes.split(",")]
    if not set(sizes) <= set(CHUNK_SIZES):
        print(f"sizes must be from {sorted(CHUNK_SIZES)}", file=sys.stderr)
        return 2
    for candidate in candidates.values():
        ensure_model(candidate.local)  # download (once) and check before timing anything
    choose = None
    if args.choose:
        name, _, words = args.choose.partition(":")
        choose = (name, int(words))
    report = asyncio.run(
        evaluate(
            question_set,
            candidates,
            sizes=sizes,
            k=args.k,
            choose=choose,
            chosen_by=args.chosen_by,
            why=args.why,
        )
    )
    md_path, json_path = write_report(report, question_set, args.out)
    for r in report.results:
        print(f"{r.system:13} {r.chunk_words:>3} words: recall@{args.k} {r.recall(args.k):.0%}")
    print("decision:", report.decision.model, report.decision.chunk_words, "words")
    print(f"wrote {md_path} and {json_path}")
    return 0


def build_index_command(args: argparse.Namespace) -> int:
    question_set = load_questions()
    role = load_config().role("embedding")
    if role.local is not None:
        ensure_model(role.local)
    store: VectorStore = LocalStore(args.path) if args.path else store_from_env()
    pages = [
        Page(
            label.path.read_bytes(), str(label.url), label.retrieved, question_set.pages[label.file]
        )
        for label in indexed_pages(question_set, real_only=True)
    ]
    report = asyncio.run(ingest_pages(pages, store=store))
    print(f"indexed {report.total_chunks} chunks from {len(report.chunks)} pages with {role.model}")
    for url, reasons in report.rejected.items():
        print(f"rejected {url}: {', '.join(reasons)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.retrieval")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-data", help="validate questions.yaml and candidates.yaml")
    run = commands.add_parser("run", help="measure recall for models x chunk sizes")
    run.add_argument("--models", default="all", help="comma-separated candidate names, or all")
    run.add_argument("--sizes", default="120,180,250", help="chunk target words to compare")
    run.add_argument("--k", type=int, default=5, help="passages per question")
    run.add_argument("--out", type=Path, default=REPORTS_DIR, help="output folder")
    run.add_argument("--choose", default="", help="NAME:WORDS, a person's decision over the rule's")
    run.add_argument("--chosen-by", default="", help="who made that decision")
    run.add_argument("--why", default="", help="the reason, shown in the report")
    build = commands.add_parser("build-index", help="index the 8 real fixture pages")
    build.add_argument("--path", type=Path, default=None, help="local index folder")
    args = parser.parse_args(argv)
    if args.command == "check-data":
        return check_data_command()
    if args.command == "run":
        return run_command(args)
    return build_index_command(args)


if __name__ == "__main__":
    sys.exit(main())
