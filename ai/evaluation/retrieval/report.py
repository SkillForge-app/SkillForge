"""The AI-11 recall report: .md for people, .json for tools. Never overwrites an earlier one."""

import json
from dataclasses import asdict
from pathlib import Path

from evaluation.common import AI_ROOT, write_new_files
from evaluation.retrieval.data import QuestionSet
from evaluation.retrieval.evaluate import BASELINE, MODEL_MARGIN, SIZE_MARGIN, RecallReport

REPORTS_DIR = AI_ROOT / "evaluation" / "retrieval" / "reports"


def write_report(
    report: RecallReport, question_set: QuestionSet, out_dir: Path = REPORTS_DIR
) -> tuple[Path, Path]:
    md_path, json_path = write_new_files(
        out_dir,
        f"recall-{report.date}",
        {
            ".md": render_markdown(report, question_set),
            ".json": json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n",
        },
    )
    return md_path, json_path


def render_markdown(report: RecallReport, question_set: QuestionSet) -> str:
    k, n = report.k, report.questions
    decision = report.decision
    chosen = next(
        r
        for r in report.results
        if r.system == decision.model and r.chunk_words == decision.chunk_words
    )
    baseline = next(
        r for r in report.results if r.system == BASELINE and r.chunk_words == decision.chunk_words
    )
    sizes = sorted({r.chunk_words for r in report.results})
    systems = [*report.candidates, BASELINE]
    dims = report.candidates[decision.model]["dimensions"]
    lines = [
        f"# AI-11 recall report ({report.date})",
        "",
        f"**Decision: `{report.candidates[decision.model]['model']}` with "
        f"{decision.chunk_words}-word chunks: recall@{k} {chosen.recall(k):.0%} "
        f"({chosen.hits(k)}/{n}). Vector dimension: {dims}.**",
        "",
        *(
            [
                f"**Chosen by {decision.chosen_by}, not by the decision rule.** The rule alone "
                f"picked `{decision.rule_model}` with {decision.rule_chunk_words}-word chunks. "
                f"Why: {decision.why}",
                "",
                "What the rule found:",
            ]
            if decision.chosen_by != "rule"
            else []
        ),
        *[f"- {reason}" for reason in decision.reasons],
        "",
        f"{n} test questions (questions.yaml v{report.question_set_version}) over the AI-10 "
        f"fixture pages; k = {k}. A hit is a top-{k} passage from the question's page that "
        "contains its evidence phrase.",
        "",
        f"## Recall@{k} by model and chunk size",
        "",
        "Each cell: recall@5 (recall@1, MRR@5). Chunk sizes are target words.",
        "",
        "| System | Dims | " + " | ".join(f"{s} words" for s in sizes) + " |",
        "|---|---|" + "---|" * len(sizes),
    ]
    for system in systems:
        cells = []
        for size in sizes:
            run = next(
                (r for r in report.results if r.system == system and r.chunk_words == size), None
            )
            mark = " ✅" if run is chosen else ""
            cells.append(
                f"{run.recall(k):.0%} ({run.recall(1):.0%}, {run.mrr:.2f}){mark}" if run else "–"
            )
        dim = report.candidates[system]["dimensions"] if system in report.candidates else "–"
        lines.append(f"| {system} | {dim} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Index size and speed",
        "",
        "| System | Chunk words | Chunks | Index time (s) | Query (ms) |",
        "|---|---|---|---|---|",
    ]
    for r in report.results:
        if r.system != BASELINE:
            lines.append(
                f"| {r.system} | {r.chunk_words} | {r.chunks} | {r.index_seconds} | {r.query_ms} |"
            )
    lines += [
        "",
        "Index time covers extraction (spaCy) plus embedding, on this laptop's CPU.",
        "",
        "## Candidates",
        "",
        "| Name | Model | Dims | Max tokens | Size (MB) | Licence | Files |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, c in report.candidates.items():
        lines.append(
            f"| {name} | `{c['model']}` | {c['dimensions']} | {c['max_tokens']} | "
            f"{c['size_mb']} | {c['licence']} | `{c['repo']}` |"
        )
    questions = {q.id: q for q in question_set.questions}
    lines += [
        "",
        f"## Questions: {decision.model}, {decision.chunk_words} words",
        "",
        f"Hit rank within the top {k}, or miss; the word-overlap baseline on the same chunks.",
        "",
        "| Id | Question | Page | Rank | Baseline |",
        "|---|---|---|---|---|",
    ]
    for qid, rank in chosen.ranks.items():
        q = questions[qid]
        base = baseline.ranks[qid]
        lines.append(
            f"| {qid} | {q.question} | {q.page.removesuffix('.html')} | "
            f"{rank if rank else '**miss**'} | {base if base else 'miss'} |"
        )
    lines += [
        "",
        "## How to read this",
        "",
        f"- With {n} questions, one question is {100 / n:.1f} points. Differences under about "
        "5 points are noise, which is why the decision rule needs a model to lead by more "
        f"than {MODEL_MARGIN} question and another chunk size to lead 180 by {SIZE_MARGIN}.",
        "- The questions were written by the AI lead's assistant from the pages, as paraphrases. "
        "They may still be easier than real users' queries; review questions.yaml before "
        "relying on small differences.",
        "- Every query searches its whole domain: in marketing, 6 pages (including a synthetic "
        "one) compete; in technology/ai, 3.",
        "- all-MiniLM-L6-v2 reads at most 256 tokens, so the end of a long chunk (250 words is "
        "about 330 tokens) does not count toward its vector.",
        "",
    ]
    return "\n".join(lines)
