"""Measure the Skill Architect (AI-07 done-when): >= 90% of the 103 test requests get a valid spec.

A spec counts as valid when the Architect returns ok: it passed core.spec.validate_spec (no
errors) within 3 attempts. Safety-guardrail compliance and identity fidelity are re-checked
here independently of the Architect's own `enforce` step.

Every outcome is saved to the run folder as soon as it is known (evaluation/architect/runlog.py),
and the metrics are computed from what was saved, so a run that dies can be resumed without
paying again for the requests already done.
"""

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agents import ArchitectResult, build_spec, required_guardrails
from core.agents.architect import GENERATE, REPAIR
from core.analysis import screen_and_analyze
from core.llm import load_config, load_prompt, track_usage
from evaluation.architect.data import GATE_SIZE, ArchitectItem, sources
from evaluation.architect.runlog import RunLog, git_head
from evaluation.common import Outcome, ReportFiles, run_all, write_eval_report

THRESHOLD = 0.90
PROMPTS = (GENERATE, REPAIR)

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
    created: str  # when the run started (its manifest); a resumed run keeps it
    live: bool
    end_to_end: bool
    prompts: dict[str, int]
    model: str
    data_sources: list[dict[str, str]]
    sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    segments: list[dict[str, Any]] = field(default_factory=list)  # one per process that ran
    missing: dict[str, int] = field(default_factory=dict)  # requests with no outcome, per set

    @property
    def passed(self) -> bool | None:
        return None if self.gate is None else bool(self.gate["passed"])


def manifest_for(
    sets: Mapping[str, Sequence[ArchitectItem]], *, label: str, live: bool, end_to_end: bool
) -> dict[str, Any]:
    """What this run measures. A resumed run must match it (runlog.COMPARED)."""
    role = load_config().role(load_prompt(GENERATE).meta.model_role)
    return {
        "label": label,
        "live": live,
        "end_to_end": end_to_end,
        "model": role.model,
        "fallbacks": list(role.fallbacks),
        "prompts": {
            p: {"version": load_prompt(p).version, "sha256": load_prompt(p).sha256} for p in PROMPTS
        },
        "data_sources": sources(),
        "ids": {name: [i.id for i in items] for name, items in sets.items()},
    }


def row_extra(o: Result) -> dict[str, Any]:
    """Per-request fields for re-scoring from an id-only tracked run (AI-25): the labels the
    request was built from, the issue codes in order, and the two checks made on valid specs.
    No text: the free-text issue messages stay in the run folder only."""
    a = o.item.analyzed
    r = o.result
    ok = r is not None and r.ok
    return {
        "expected": {"kind": a.kind, "domain_area": a.domain_area, "risk": a.risk},
        "codes": [i.code for i in r.issues] if r is not None and not r.ok else [],
        "safety_ok": _safety_ok(o) if ok else None,
        "identity_ok": _identity_ok(o) if ok else None,
    }


async def run_eval(
    sets: dict[str, Sequence[ArchitectItem]],
    *,
    live: bool,
    run_dir: Path,
    label: str = "run",
    resume: bool = False,
    end_to_end: bool = False,
    concurrency: int = 2,
    build: Build | None = None,
) -> tuple[ArchitectReport, dict[str, list[Result]]]:
    """Run every request that has no outcome yet in `run_dir`, saving each as it finishes, then
    score everything saved. `resume=False` makes a new run folder (it must not exist);
    `resume=True` continues one (runlog.RunLog.resume refuses a different measurement)."""
    build = build or (_build_end_to_end if end_to_end else _build)
    manifest = manifest_for(sets, label=label, live=live, end_to_end=end_to_end)
    log = RunLog.resume(run_dir, manifest) if resume else RunLog.create(run_dir, manifest)
    done = log.done()
    started, ran = _now(), 0
    try:
        for name, items in sets.items():
            todo = [i for i in items if (name, i.id) not in done]
            ran += len(todo)
            usage_of: dict[str, dict[str, Any]] = {}

            async def tracked(
                item: ArchitectItem, usage_of: dict[str, dict[str, Any]] = usage_of
            ) -> ArchitectResult:
                with track_usage() as totals:  # this request's calls only (one task each)
                    try:
                        return await build(item)
                    finally:
                        usage_of[item.id] = asdict(totals)

            def save(
                o: Result, name: str = name, usage_of: dict[str, dict[str, Any]] = usage_of
            ) -> None:
                log.record(name, o, usage=usage_of.get(o.item.id, {}), extra=row_extra(o))

            await run_all(todo, tracked, concurrency=concurrency, on_done=save)
    finally:  # also on Ctrl-C or a crash: the next resume sees what this process did
        log.add_segment(
            {
                "started": started,
                "ended": _now(),
                "git_head": git_head(),
                "resume": resume,
                "requests_run": ran,
            }
        )
    return score(log, sets), log.outcomes(sets)


def score(log: RunLog, sets: Mapping[str, Sequence[ArchitectItem]]) -> ArchitectReport:
    """The report, from the run folder alone."""
    m = log.manifest
    report = ArchitectReport(
        created=m["created"],
        live=m["live"],
        end_to_end=m["end_to_end"],
        prompts={p: int(v["version"]) for p, v in m["prompts"].items()},
        model=m["model"],
        data_sources=m["data_sources"],
        usage=log.usage(),
        segments=log.segments(),
        missing={name: len(ids) for name, ids in log.missing(sets).items() if ids},
    )
    outcomes = log.outcomes(sets)
    for name in sets:
        report.sets[name] = compute_metrics(outcomes[name])
    if "all" in report.sets:
        report.gate = gate_verdict(report.sets["all"], live=report.live)
        if report.missing:
            report.gate["passed"] = False
            report.gate["reasons"].append(
                f"requests with no outcome: {sum(report.missing.values())} (resume the run)"
            )
    return report


def write_report(
    report: ArchitectReport, *, label: str, reports_dir: Path, run_dir: Path
) -> ReportFiles:
    """The report goes to `reports_dir` as architect-<label>[-e2e]-<date>.md/.json, never
    overwriting an earlier one. The run's lines and specs are already in `run_dir`."""
    e2e = "-e2e" if report.end_to_end else ""
    return write_eval_report(
        f"architect-{label}{e2e}-{report.created[:10]}",
        render_markdown(report),
        asdict(report),
        reports_dir=reports_dir,
        run_dir=run_dir,
    )


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
    if report.missing:
        counts = ", ".join(f"{name}: {n}" for name, n in report.missing.items())
        lines += [f"**INCOMPLETE: requests with no outcome ({counts}). Resume the run.**", ""]
    if len(report.segments) > 1:
        lines += [f"Run in {len(report.segments)} segments (resumed).", ""]
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
    lines += [
        "",
        f"Usage: {u['calls']} calls, {u['input_tokens']} input / {u['output_tokens']} output "
        f"tokens, ${u['cost_usd']}.",
        "",
    ]
    return "\n".join(lines)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"
