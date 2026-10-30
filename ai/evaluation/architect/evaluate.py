"""Measure the Skill Architect (AI-07 done-when): >= 90% of the 103 test requests get a valid spec.

A spec counts as valid when the Architect returns ok: it passed core.spec.validate_spec (no
errors) within 3 attempts. Safety-guardrail compliance and identity fidelity are re-checked
here independently of the Architect's own `enforce` step.
"""

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agents import ArchitectResult, build_spec, required_guardrails
from core.agents.architect import GENERATE
from core.analysis import screen_and_analyze
from core.llm import load_prompt, track_usage
from evaluation.architect.data import GATE_SIZE, ArchitectItem, sources
from evaluation.common import Outcome, model_for, run_all

THRESHOLD = 0.90

Build = Callable[[ArchitectItem], Awaitable[ArchitectResult]]
Result = Outcome[ArchitectItem, ArchitectResult]


async def _build(item: ArchitectItem) -> ArchitectResult:
    return await build_spec(item.analyzed)


async def _build_end_to_end(item: ArchitectItem) -> ArchitectResult:
    """Run the real safety screen + analyzer first (answers skipped), then the Architect."""
    from core.analysis import Answer, answer_questions_safely

    analyzed = await screen_and_analyze(item.text)
    if analyzed.needs_clarification:
        skipped = [Answer(question_id=q.id) for q in analyzed.questions]
        analyzed = await answer_questions_safely(analyzed, skipped)
    return await build_spec(analyzed)


def _safety_ok(o: Result) -> bool:
    if o.result is None or o.result.spec is None:
        return False
    have = {(g.id, g.severity, g.category) for g in o.result.spec.guardrails}
    need = {(g["id"], g["severity"], g["category"]) for g in required_guardrails(o.item.analyzed)}
    return need <= have


def _identity_ok(o: Result) -> bool:
    if o.result is None or o.result.spec is None:
        return False
    spec, analyzed = o.result.spec, o.item.analyzed
    return spec.skill.kind == analyzed.kind and spec.skill.domain == analyzed.domain


def compute_metrics(outcomes: Sequence[Result]) -> dict[str, Any]:
    n = len(outcomes)
    valid = [o for o in outcomes if o.result is not None and o.result.ok]
    attempts = Counter(o.result.attempts for o in valid if o.result is not None)
    failed_codes: Counter[str] = Counter()
    for o in outcomes:
        if o.result is not None and not o.result.ok:
            failed_codes.update(i.code for i in o.result.issues)
    return {
        "n": n,
        "valid": len(valid),
        "valid_rate": _ratio(len(valid), n),
        "first_try_rate": _ratio(attempts.get(1, 0), n),
        "attempts": {str(k): v for k, v in sorted(attempts.items())},
        "failed": [o.item.id for o in outcomes if o.result is not None and not o.result.ok],
        "top_failure_codes": dict(failed_codes.most_common(10)),
        "safety_guardrails_ok": _ratio(sum(_safety_ok(o) for o in valid), len(valid)),
        "identity_ok": _ratio(sum(_identity_ok(o) for o in valid), len(valid)),
        "errors": dict(Counter(o.error for o in outcomes if o.error)),
    }


def gate_verdict(metrics: dict[str, Any], *, live: bool = True) -> dict[str, Any]:
    reasons = []
    if metrics["n"] != GATE_SIZE:
        reasons.append(f"the gate needs exactly {GATE_SIZE} requests, got {metrics['n']}")
    rate = metrics["valid_rate"]
    if rate is None or rate < THRESHOLD:
        shown = "n/a" if rate is None else f"{rate:.2f}"
        reasons.append(f"valid rate {shown} < {THRESHOLD:.2f}")
    # Only a live run can count for AI-07: a fake answers every request with one canned spec.
    return {"passed": not reasons, "counts": live, "threshold": THRESHOLD, "reasons": reasons}


@dataclass
class ArchitectReport:
    created: str
    live: bool
    end_to_end: bool
    prompts: dict[str, int]
    model: str
    data_sources: list[dict[str, str]]
    sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool | None:
        return None if self.gate is None else bool(self.gate["passed"])


async def run_eval(
    sets: dict[str, Sequence[ArchitectItem]],
    *,
    live: bool,
    end_to_end: bool = False,
    concurrency: int = 2,
    build: Build | None = None,
) -> tuple[ArchitectReport, dict[str, list[Result]]]:
    build = build or (_build_end_to_end if end_to_end else _build)
    report = ArchitectReport(
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        live=live,
        end_to_end=end_to_end,
        prompts={p: load_prompt(p).version for p in ("architect/generate", "architect/repair")},
        model=model_for(GENERATE),
        data_sources=sources(),
    )
    outcomes: dict[str, list[Result]] = {}
    with track_usage() as usage:
        for name, items in sets.items():
            outcomes[name] = await run_all(items, build, concurrency=concurrency)
            report.sets[name] = compute_metrics(outcomes[name])
    if "all" in report.sets:
        report.gate = gate_verdict(report.sets["all"], live=live)
    report.usage = {
        "calls": usage.calls,
        "errors": usage.errors,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 4),
    }
    return report, outcomes


def write_report(report: ArchitectReport, outcomes: dict[str, list[Result]], out_dir: Path) -> Path:
    (out_dir / "specs").mkdir(parents=True, exist_ok=False)
    (out_dir / "report.json").write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for name, rows in outcomes.items():
            for o in rows:
                r = o.result
                f.write(
                    json.dumps(
                        {
                            "set": name,
                            "id": o.item.id,
                            "ok": bool(r and r.ok),
                            "attempts": r.attempts if r else None,
                            "issues": [str(i) for i in r.issues] if r else [],
                            "error": o.error,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if r is not None and r.spec is not None:
                    safe = o.item.id.replace(":", "_").replace("/", "_")
                    (out_dir / "specs" / f"{safe}.json").write_text(
                        r.spec.model_dump_json(indent=2), encoding="utf-8"
                    )
    return out_dir


def render_markdown(report: ArchitectReport) -> str:
    mode = "LIVE" if report.live else "fake (numbers are not meaningful)"
    if report.end_to_end:
        mode += ", end to end (real analyzer + safety screen first)"
    lines = [
        f"# Skill Architect evaluation, {report.created}",
        "",
        f"Mode: {mode}. Prompts {report.prompts}, model `{report.model}`.",
        "",
    ]
    if report.gate is not None:
        verdict = "PASSED" if report.gate["passed"] else "FAILED"
        if not report.gate["counts"]:
            verdict += " (fake mode: does NOT count for AI-07)"
        lines += [f"**Gate (>= {THRESHOLD:.0%} valid specs on {GATE_SIZE} requests): {verdict}**"]
        lines += [f"- {r}" for r in report.gate["reasons"]] + [""]
    lines += ["| Set | n | valid | first try | attempts | safety guardrails | errors |"]
    lines += ["|---|---|---|---|---|---|---|"]
    for name, m in report.sets.items():
        lines.append(
            f"| {name} | {m['n']} | {_pct(m['valid_rate'])} | {_pct(m['first_try_rate'])} "
            f"| {m['attempts']} | {_pct(m['safety_guardrails_ok'])} | {sum(m['errors'].values())} |"
        )
    u = report.usage
    lines += ["", f"Usage: {u['calls']} calls, ${u['cost_usd']}.", ""]
    return "\n".join(lines)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"
