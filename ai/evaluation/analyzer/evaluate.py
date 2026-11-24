"""Measure the Request Analyzer against labelled requests (AI-05 done-when).

The gate: on the 100 gate requests, kind, domain area and risk must EACH be >= 90% correct.
The joint score (all three right) is reported but does not gate. Dev and Arabic results are
reported, never gated. A request whose analysis failed (an LLM error) counts as wrong.
"""

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.analysis import PROMPT_ID, AnalyzedRequest, analyze_request
from core.llm import load_config, load_prompt, skill_run, track_usage
from evaluation.analyzer.data import GATE_SIZE, EvalItem, sources
from evaluation.common import ReportFiles, run_all, write_eval_report

THRESHOLD = 0.90
GATED_FIELDS = ("kind", "domain_area", "risk")
ERROR = "<error>"
BUDGET_STOP = "BudgetExceeded"  # the error name of a call refused by the run's cost budget
# Decided by Ziad on 2026-11-25, before the gate run of prompt v3 (written into each report that
# uses it). Not tuning: no prompt or data change.
# Decided by Ziad on 2026-11-25, AFTER the invalid v3 gate run of 2026-11-24T23:41Z (48 of 100
# requests got no prediction) and before any rerun. Written into every report.
MIN_PREDICTED = 0.95
VALIDITY_RULE = (
    "A run is valid only if at least 95% of its requests get a prediction (after the one retry). "
    "Otherwise the run is invalid and is repeated with the same prompt and data. (Rule added "
    "2026-11-25, after the invalid gate run of 2026-11-24T23:41Z.)"
)
RETRY_RULE = (
    "A request that fails with a provider error (no prediction at all) is retried ONCE at the end "
    "of the run, with the same prompt and settings. If it fails again, it counts as wrong."
)

Analyze = Callable[[str], Awaitable[AnalyzedRequest]]


@dataclass(frozen=True)
class Prediction:
    item: EvalItem
    result: AnalyzedRequest | None
    error: str | None
    latency_ms: float

    def value(self, name: str) -> str:
        if self.result is None:
            return ERROR
        return str(getattr(self.result, name))


async def predict_all(
    items: Sequence[EvalItem], *, concurrency: int = 4, analyze: Analyze = analyze_request
) -> list[Prediction]:
    """Analyze every item, at most `concurrency` at a time. Errors are recorded, not raised."""
    outcomes = await run_all(items, lambda item: analyze(item.text), concurrency=concurrency)
    return [Prediction(o.item, o.result, o.error, o.latency_ms) for o in outcomes]


def compute_metrics(predictions: Sequence[Prediction]) -> dict[str, Any]:
    n = len(predictions)
    out: dict[str, Any] = {"n": n, "fields": {}}
    for name in GATED_FIELDS:
        confusion: dict[str, Counter[str]] = defaultdict(Counter)
        correct = 0
        for p in predictions:
            label = getattr(p.item, name)
            got = p.value(name)
            confusion[label][got] += 1
            correct += got == label
        out["fields"][name] = {
            "correct": correct,
            "accuracy": _ratio(correct, n),
            "confusion": {k: dict(v) for k, v in sorted(confusion.items())},
        }
    joint = sum(all(p.value(f) == getattr(p.item, f) for f in GATED_FIELDS) for p in predictions)
    out["joint_accuracy"] = _ratio(joint, n)

    tp = fp = fn = tn = 0
    rule_ok = rule_total = 0
    for p in predictions:
        want = p.item.needs_clarification
        asked = p.result is not None and p.result.needs_clarification
        tp += want and asked
        fp += asked and not want
        fn += want and not asked
        tn += not want and not asked
        if p.result is not None and p.result.needs_clarification:
            rule_total += 1
            rule_ok += 3 <= len(p.result.questions) <= 5
    out["needs_clarification"] = {
        "accuracy": _ratio(tp + tn, n),
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "question_rule_kept": _ratio(rule_ok, rule_total),
    }

    labelled = [p for p in predictions if p.item.mentioned_targets is not None]
    exact = sum(
        p.result is not None and set(p.result.targets) == set(p.item.mentioned_targets or ())
        for p in labelled
    )
    out["mentioned_targets"] = {"n": len(labelled), "exact_match": _ratio(exact, len(labelled))}
    out["errors"] = dict(Counter(p.error for p in predictions if p.error))
    latencies = [p.latency_ms for p in predictions]
    out["latency_ms"] = {
        "p50": round(statistics.median(latencies), 1) if latencies else None,
        "max": round(max(latencies), 1) if latencies else None,
    }
    return out


def gate_verdict(metrics: dict[str, Any]) -> dict[str, Any]:
    accuracies = {f: metrics["fields"][f]["accuracy"] for f in GATED_FIELDS}
    reasons = []
    if metrics["n"] != GATE_SIZE:
        reasons.append(f"the gate needs exactly {GATE_SIZE} requests, got {metrics['n']}")
    reasons += [
        f"{f} accuracy {'n/a' if a is None else f'{a:.2f}'} < {THRESHOLD:.2f}"
        for f, a in accuracies.items()
        if a is None or a < THRESHOLD
    ]
    return {
        "passed": not reasons,
        "threshold": THRESHOLD,
        "accuracy": accuracies,
        "reasons": reasons,
    }


@dataclass
class EvalReport:
    created: str
    live: bool
    prompt: dict[str, Any]
    model: str
    data_sources: list[dict[str, str]]
    sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    budget_usd: float | None = None
    stopped: str | None = None  # set when the cost budget stopped the run: it does not count
    retry_rule: str | None = None  # RETRY_RULE when the run used it
    retries: list[dict[str, Any]] = field(default_factory=list)  # one row per retried request
    validity_rule: str = VALIDITY_RULE
    invalid: str | None = None  # set when under MIN_PREDICTED of a set got a prediction

    @property
    def passed(self) -> bool | None:
        return None if self.gate is None else bool(self.gate["passed"])


async def run_eval(
    sets: dict[str, Sequence[EvalItem]],
    *,
    live: bool,
    concurrency: int = 4,
    analyze: Analyze = analyze_request,
    budget_usd: float | None = None,
    retry_errors: bool = False,
) -> tuple[EvalReport, dict[str, list[Prediction]]]:
    """Run every set. With `budget_usd`, the calls run inside a skill budget (AI-21): once the
    spend reaches it, every further call is refused before it is made (at most the calls already
    running finish), and the report is marked stopped. With `retry_errors`, RETRY_RULE applies:
    after all sets, each request with no prediction (budget refusals excepted) is run once more."""
    report = EvalReport(
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        live=live,
        prompt={"id": PROMPT_ID, "version": load_prompt(PROMPT_ID).version},
        model=load_config().role(load_prompt(PROMPT_ID).meta.model_role).model,
        data_sources=[asdict(s) for s in sources()],
        budget_usd=budget_usd,
        retry_rule=RETRY_RULE if retry_errors else None,
    )
    predictions: dict[str, list[Prediction]] = {}
    with skill_run(None, budget_usd=budget_usd), track_usage() as usage:
        for name, items in sets.items():
            predictions[name] = await predict_all(items, concurrency=concurrency, analyze=analyze)
        if retry_errors:
            await _retry_failed_once(predictions, report, concurrency=concurrency, analyze=analyze)
    for name, preds in predictions.items():
        report.sets[name] = compute_metrics(preds)
    refused = sum(p.error == BUDGET_STOP for preds in predictions.values() for p in preds)
    if refused:
        report.stopped = (
            f"the ${budget_usd} budget was used up; {refused} requests were not analysed. "
            "This run does not count."
        )
    report.invalid = _invalid(predictions)
    if "gate" in report.sets:
        report.gate = gate_verdict(report.sets["gate"])
        if report.stopped:
            report.gate["passed"] = False
            report.gate["reasons"].append("stopped by the cost budget")
        if report.invalid:
            report.gate["passed"] = False
            report.gate["reasons"].append("invalid run (validity rule): repeat it")
    report.usage = {
        "calls": usage.calls,
        "errors": usage.errors,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 4),
    }
    return report, predictions


def _invalid(predictions: dict[str, list[Prediction]]) -> str | None:
    """VALIDITY_RULE: the run is invalid when any set has under 95% of requests predicted."""
    missing = {
        name: sum(p.result is None for p in preds) for name, preds in predictions.items() if preds
    }
    bad = {
        name: n
        for name, n in missing.items()
        if (len(predictions[name]) - n) / len(predictions[name]) < MIN_PREDICTED
    }
    if not bad:
        return None
    counts = "; ".join(f"{name}: {n} of {len(predictions[name])}" for name, n in bad.items())
    return (
        f"INVALID: provider failure (requests with no prediction, {counts}). "
        "Not a measurement of the prompt."
    )


async def _retry_failed_once(
    predictions: dict[str, list[Prediction]],
    report: EvalReport,
    *,
    concurrency: int,
    analyze: Analyze,
) -> None:
    """RETRY_RULE: run each request that has no prediction once more, in place, and record how
    each retry ended. A call refused by the budget is not retried."""
    for name, preds in predictions.items():
        failed = [i for i, p in enumerate(preds) if p.error and p.error != BUDGET_STOP]
        if not failed:
            continue
        again = await predict_all(
            [preds[i].item for i in failed], concurrency=concurrency, analyze=analyze
        )
        for i, retry in zip(failed, again, strict=True):
            report.retries.append(
                {
                    "set": name,
                    "id": preds[i].item.id,
                    "first_error": preds[i].error,
                    "retry": "ok" if retry.error is None else retry.error,
                }
            )
            preds[i] = retry


def write_report(
    report: EvalReport,
    predictions: dict[str, list[Prediction]],
    *,
    label: str,
    reports_dir: Path,
    run_dir: Path,
) -> ReportFiles:
    """The report goes to `reports_dir` as analyzer-<label>-<date>.md/.json, never overwriting an
    earlier one; one line per request goes to `run_dir`/predictions.jsonl."""
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for name, preds in predictions.items():
            for p in preds:
                row = {
                    "set": name,
                    "id": p.item.id,
                    "text": p.item.text,
                    "expected": {f: getattr(p.item, f) for f in GATED_FIELDS},
                    "predicted": {f: p.value(f) for f in GATED_FIELDS},
                    "needs_clarification": {
                        "expected": p.item.needs_clarification,
                        "predicted": None if p.result is None else p.result.needs_clarification,
                    },
                    "error": p.error,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return write_eval_report(
        f"analyzer-{label}-{report.created[:10]}",
        render_markdown(report),
        asdict(report),
        reports_dir=reports_dir,
        run_dir=run_dir,
    )


def render_markdown(report: EvalReport) -> str:
    lines = [
        f"# Request Analyzer evaluation, {report.created}",
        "",
        f"Mode: {'LIVE' if report.live else 'fake (numbers are not meaningful)'}. "
        f"Prompt {report.prompt['id']} v{report.prompt['version']}, model `{report.model}`.",
        "",
    ]
    if report.invalid:
        lines = [f"**{report.invalid}**", ""] + lines
    lines += [f"**Validity rule:** {report.validity_rule}", ""]
    if report.stopped:
        lines += [f"**STOPPED: budget.** {report.stopped}", ""]
    if report.retry_rule:
        ok = sum(r["retry"] == "ok" for r in report.retries)
        lines += [
            f"**Retry rule (decided before this run):** {report.retry_rule}",
            "",
            f"Retried: {len(report.retries)}; succeeded on retry: {ok}; "
            f"still failed (counted wrong): {len(report.retries) - ok}.",
            "",
        ]
        if report.retries:
            lines += ["| set | id | first error | retry |", "|---|---|---|---|"]
            lines += [
                f"| {r['set']} | {r['id']} | {r['first_error']} | {r['retry']} |"
                for r in report.retries
            ]
            lines += [""]
    if report.gate is not None:
        verdict = "PASSED" if report.gate["passed"] else "FAILED"
        lines += [f"**Gate (each field >= {THRESHOLD:.0%} on {GATE_SIZE} requests): {verdict}**"]
        lines += [f"- {r}" for r in report.gate["reasons"]] + [""]
    lines += ["| Set | n | kind | domain area | risk | joint | clarify acc. | errors |"]
    lines += ["|---|---|---|---|---|---|---|---|"]
    for name, m in report.sets.items():
        f = m["fields"]
        lines.append(
            f"| {name} | {m['n']} | {_pct(f['kind']['accuracy'])} | "
            f"{_pct(f['domain_area']['accuracy'])} | {_pct(f['risk']['accuracy'])} | "
            f"{_pct(m['joint_accuracy'])} | {_pct(m['needs_clarification']['accuracy'])} | "
            f"{sum(m['errors'].values())} |"
        )
    u = report.usage
    lines += [
        "",
        f"Usage: {u['calls']} calls, {u['input_tokens']} input / {u['output_tokens']} output "
        f"tokens, ${u['cost_usd']}"
        + (f" (budget ${report.budget_usd})." if report.budget_usd is not None else "."),
        "",
        "Data: "
        + ", ".join(
            f"{s['name']} {s['version']} ({s['sha256'][:12]})" for s in report.data_sources
        ),
        "",
    ]
    return "\n".join(lines)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"
