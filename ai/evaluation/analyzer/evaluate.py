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
from core.llm import load_config, load_prompt, track_usage
from evaluation.analyzer.data import GATE_SIZE, EvalItem, sources
from evaluation.common import run_all

THRESHOLD = 0.90
GATED_FIELDS = ("kind", "domain_area", "risk")
ERROR = "<error>"

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

    @property
    def passed(self) -> bool | None:
        return None if self.gate is None else bool(self.gate["passed"])


async def run_eval(
    sets: dict[str, Sequence[EvalItem]],
    *,
    live: bool,
    concurrency: int = 4,
    analyze: Analyze = analyze_request,
) -> tuple[EvalReport, dict[str, list[Prediction]]]:
    report = EvalReport(
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        live=live,
        prompt={"id": PROMPT_ID, "version": load_prompt(PROMPT_ID).version},
        model=load_config().role(load_prompt(PROMPT_ID).meta.model_role).model,
        data_sources=[asdict(s) for s in sources()],
    )
    predictions: dict[str, list[Prediction]] = {}
    with track_usage() as usage:
        for name, items in sets.items():
            predictions[name] = await predict_all(items, concurrency=concurrency, analyze=analyze)
            report.sets[name] = compute_metrics(predictions[name])
    if "gate" in report.sets:
        report.gate = gate_verdict(report.sets["gate"])
    report.usage = {
        "calls": usage.calls,
        "errors": usage.errors,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 4),
    }
    return report, predictions


def write_report(
    report: EvalReport, predictions: dict[str, list[Prediction]], out_dir: Path
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "report.json").write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
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
    return out_dir


def render_markdown(report: EvalReport) -> str:
    lines = [
        f"# Request Analyzer evaluation, {report.created}",
        "",
        f"Mode: {'LIVE' if report.live else 'fake (numbers are not meaningful)'}. "
        f"Prompt {report.prompt['id']} v{report.prompt['version']}, model `{report.model}`.",
        "",
    ]
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
        f"tokens, ${u['cost_usd']}.",
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
