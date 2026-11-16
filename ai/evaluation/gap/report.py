"""Tuning on dev and the one-time test report for the Gap Checker (AI-08).

tune: score every text variant on dev, pick the `exists` threshold by F0.5 (precision first)
and the `similar` threshold by F1 on related pairs, keep the best variant, write the dev
report and core/analysis/gap_checker.yaml. report: with those frozen settings, run the test
split once and write the test report. Neither overwrites an earlier report.
"""

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.analysis import FixtureSkillIndex, GapSettings, SkillCard, check_gap
from core.analysis.gap_checker import SETTINGS_PATH
from core.llm import load_config
from evaluation.common import wilson_interval, write_new_files
from evaluation.gap.data import DATA_DIR, PairSet
from evaluation.gap.evaluate import (
    EXISTS_BETA,
    RELATED_BETA,
    VARIANTS,
    Counts,
    RequestOutcome,
    best_threshold,
    card_vectors,
    confusion,
    pair_counts,
    request_outcomes,
    score_table,
)

REPORTS_DIR = DATA_DIR / "reports"


@dataclass(frozen=True)
class VariantResult:
    name: str
    choice: dict[str, Any]
    exists_threshold: float
    exists: Counts
    similar_threshold: float
    related: Counts

    @property
    def key(self) -> tuple[float, float]:
        return (self.exists.f_beta(EXISTS_BETA), self.related.f_beta(RELATED_BETA))


async def tune(dev: PairSet, cards: list[SkillCard]) -> list[VariantResult]:
    vectors = await card_vectors(cards)
    results = []
    for name, choice in VARIANTS.items():
        table = await score_table(
            dev.requests,
            cards,
            vectors,
            variant=choice["request_text"],
            query_prefix=choice["query_prefix"],
        )
        t1, exists = best_threshold(
            table,
            positive=["match"],
            beta=EXISTS_BETA,
            area_gate=choice["same_area_for_exists"],
        )
        t2, related = best_threshold(
            table, positive=["match", "near_miss"], beta=RELATED_BETA, below=t1
        )
        results.append(VariantResult(name, choice, t1, exists, t2, related))
    return results


def winner(results: list[VariantResult]) -> VariantResult:
    """Best F0.5 of `exists`, then best F1 of `related`, then the earlier (simpler) variant."""
    return max(results, key=lambda r: (*r.key, -list(VARIANTS).index(r.name)))


def settings_text(best: VariantResult, *, version: str, tuned_on: str) -> str:
    c = best.choice
    return (
        "# Gap Checker (AI-08) settings: which request text is embedded, and the two thresholds\n"
        "# on the top cosine score. Tuned on evaluation/gap/pairs-dev.yaml only\n"
        "# (python -m evaluation.gap tune); change by pull request together with the report.\n"
        "#   exists   top score at or above: an existing skill already does it (FE-09: use it)\n"
        "#   similar  top score at or above (below exists): a related skill to customize\n"
        "#   below    generate a new skill\n"
        f'version: "{version}"\n'
        f"request_text: {c['request_text']}\n"
        f"query_prefix: {str(c['query_prefix']).lower()}\n"
        f"same_area_for_exists: {str(c['same_area_for_exists']).lower()}\n"
        f"exists: {best.exists_threshold}\n"
        f"similar: {best.similar_threshold}\n"
        f'tuned_on: "{tuned_on}"\n'
    )


def _pr(c: Counts) -> str:
    return f"{c.precision:.1%} / {c.recall:.1%} (tp {c.tp}, fp {c.fp}, fn {c.fn})"


def write_tuning(
    dev: PairSet,
    cards: list[SkillCard],
    results: list[VariantResult],
    *,
    out_dir: Path = REPORTS_DIR,
    settings_path: Path = SETTINGS_PATH,
    today: date | None = None,
) -> tuple[Path, Path]:
    day = (today or date.today()).isoformat()
    best = winner(results)
    model = load_config().role("embedding").model
    lines = [
        f"# AI-08 Gap Checker tuning on dev ({day})",
        "",
        f"Dev split: {len(dev.requests)} requests x {len(cards)} skill cards = "
        f"{len(dev.requests) * len(cards)} pairs; labels `{dev.review.status}`. Model `{model}`.",
        f"`exists` threshold: best F{EXISTS_BETA} on pairs labelled `match`. `similar` "
        f"threshold: best F{RELATED_BETA:g} on `match` or `near_miss` pairs, below `exists`.",
        "",
        "| Variant | exists t | exists P / R | F0.5 | similar t | related P / R | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = " **(chosen)**" if r is best else ""
        lines.append(
            f"| {r.name}{mark} | {r.exists_threshold} | {_pr(r.exists)} | "
            f"{r.exists.f_beta(EXISTS_BETA):.3f} | {r.similar_threshold} | {_pr(r.related)} | "
            f"{r.related.f_beta(RELATED_BETA):.3f} |"
        )
    data = {
        "date": day,
        "split": "dev",
        "labels": dev.review.model_dump(mode="json"),
        "model": model,
        "variants": [
            {
                "name": r.name,
                "choice": r.choice,
                "exists_threshold": r.exists_threshold,
                "exists": r.exists.__dict__,
                "similar_threshold": r.similar_threshold,
                "related": r.related.__dict__,
            }
            for r in results
        ],
        "chosen": best.name,
    }
    md, js = write_new_files(
        out_dir,
        f"gap-dev-{day}",
        {".md": "\n".join(lines) + "\n", ".json": json.dumps(data, indent=2) + "\n"},
    )
    settings_path.write_text(
        settings_text(best, version=day, tuned_on=f"evaluation/gap/reports/{md.name}"),
        encoding="utf-8",
        newline="\n",
    )
    return md, js


@dataclass(frozen=True)
class TestResult:
    settings: GapSettings
    exists: Counts
    related: Counts
    outcomes: list[RequestOutcome]
    mean_ms: float
    agree: int  # requests where check_gap's verdict equals the table's (a consistency check)


async def run_test(test: PairSet, cards: list[SkillCard], settings: GapSettings) -> TestResult:
    vectors = await card_vectors(cards)
    table = await score_table(
        test.requests,
        cards,
        vectors,
        variant=settings.request_text,
        query_prefix=settings.query_prefix,
    )
    exists = pair_counts(
        table, settings.exists, positive=["match"], area_gate=settings.same_area_for_exists
    )
    related = pair_counts(table, settings.similar, positive=["match", "near_miss"])
    outcomes = request_outcomes(table, settings)
    # The real call, over two indexes (registry and corpus), as the pipeline would make it.
    indexes = [
        FixtureSkillIndex(cards=[c for c in cards if c.source == s]) for s in ("registry", "corpus")
    ]
    await check_gap(test.requests[0].analyzed(), indexes=indexes, settings=settings)  # warm up
    agree, start = 0, time.perf_counter()
    for r, o in zip(test.requests, outcomes, strict=True):
        result = await check_gap(r.analyzed(), indexes=indexes, settings=settings)
        agree += result.verdict == o.verdict
    mean_ms = (time.perf_counter() - start) * 1000 / len(test.requests)
    return TestResult(settings, exists, related, outcomes, round(mean_ms, 1), agree)


def _with_ci(c: Counts) -> str:
    p_low, p_high = wilson_interval(c.tp, c.tp + c.fp)
    r_low, r_high = wilson_interval(c.tp, c.tp + c.fn)
    return (
        f"precision **{c.precision:.1%}** (95% CI {p_low:.0%}–{p_high:.0%}, {c.tp} of "
        f"{c.tp + c.fp}); recall **{c.recall:.1%}** (95% CI {r_low:.0%}–{r_high:.0%}, "
        f"{c.tp} of {c.tp + c.fn})"
    )


def write_test_report(
    test: PairSet,
    cards: list[SkillCard],
    result: TestResult,
    *,
    out_dir: Path = REPORTS_DIR,
    today: date | None = None,
) -> tuple[Path, Path]:
    day = (today or date.today()).isoformat()
    s = result.settings
    model = load_config().role("embedding").model
    correct = sum(o.correct for o in result.outcomes)
    with_match = [o for o in result.outcomes if o.request.match]
    top1 = sum(o.top.id in o.request.match for o in with_match)
    table = confusion(result.outcomes)
    lines = [
        f"# AI-08 Gap Checker test report ({day})",
        "",
        f"Test split: {len(test.requests)} requests x {len(cards)} skill cards = "
        f"{len(test.requests) * len(cards)} pairs; labels `{test.review.status}` "
        f"(reviewer {test.review.reviewer}, {test.review.date}). Run once, after tuning on dev.",
        f"Settings `{s.version}` from `{s.tuned_on}`: request text `{s.request_text}`, query "
        f"prefix {s.query_prefix}, area gate {s.same_area_for_exists}, `exists` >= {s.exists}, "
        f"`similar` >= {s.similar}. Model `{model}`.",
        "",
        "## Done-when: precision on labelled pairs",
        f"- **exists** (pairs labelled `match`): {_with_ci(result.exists)}",
        f"- **related** (`match` or `near_miss`, `similar` threshold): {_with_ci(result.related)}",
        "",
        "## Per request (the verdict FE-09 would show)",
        f"- Verdict correct for {correct} of {len(result.outcomes)} requests "
        "(an `exists` verdict must also name a matching skill).",
        f"- Top-ranked skill is a match for {top1} of {len(with_match)} requests that have one.",
        f"- check_gap over two indexes (registry + corpus) gave the same verdict for "
        f"{result.agree} of {len(result.outcomes)}; mean {result.mean_ms} ms per request.",
        "",
        "| Gold \\ verdict | exists | similar | new |",
        "|---|---|---|---|",
        *[f"| {g} | {r['exists']} | {r['similar']} | {r['new']} |" for g, r in table.items()],
        "",
        "## Wrong verdicts",
        "",
        *[
            f"- `{o.request.id}` gold `{o.gold}`, got `{o.verdict}`: top `{o.top.id}` "
            f"({o.top_score:.3f}). {o.request.analysis.summary}"
            for o in result.outcomes
            if not o.correct
        ],
    ]
    data = {
        "date": day,
        "split": "test",
        "labels": test.review.model_dump(mode="json"),
        "model": model,
        "settings": s.model_dump(mode="json"),
        "exists": result.exists.__dict__,
        "related": result.related.__dict__,
        "requests_correct": correct,
        "requests": len(result.outcomes),
        "top1_match": [top1, len(with_match)],
        "confusion": table,
        "mean_ms": result.mean_ms,
        "outcomes": [
            {
                "id": o.request.id,
                "gold": o.gold,
                "verdict": o.verdict,
                "top": o.top.id,
                "score": o.top_score,
            }
            for o in result.outcomes
        ],
    }
    return write_new_files(
        out_dir,
        f"gap-test-{day}",
        {".md": "\n".join(lines) + "\n", ".json": json.dumps(data, indent=2) + "\n"},
    )  # type: ignore[return-value]
