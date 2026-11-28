"""Measure the Skill Architect (AI-07 done-when): >= 90% of the 103 test requests get a valid spec.

A spec counts as valid when the Architect returns ok: it passed core.spec.validate_spec (no
errors) within 3 attempts. Safety-guardrail compliance and identity fidelity are re-checked
here independently of the Architect's own `enforce` step.

Every outcome is saved to the run folder as soon as it is known (evaluation/architect/runlog.py),
and the metrics are computed from what was saved, so a run that dies can be resumed without
paying again for the requests already done.

The run rules for live runs (decided 2026-11-26 by the AI Lead, before any live architect run,
the same as AI-05's plus a pause on outages; written into every report):
- budget: the calls run inside a cost budget; once the spend (all segments) reaches it, no
  further call is made and the run is STOPPED (it does not count).
- retry: a request that ends in a provider error is retried once, at the end of the segment.
- pause: after PAUSE_AFTER requests in a row end in a provider error, no new request starts;
  the run is PAUSED and is resumed later with --resume (the waiting requests have no outcome).
- validity: a complete run is INVALID when under 95% of a set's requests got a prediction.
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
from core.llm import load_config, load_prompt, skill_run, track_usage
from evaluation.architect.data import GATE_SIZE, ArchitectItem, sources
from evaluation.architect.runlog import RunLog, git_head
from evaluation.common import Outcome, ReportFiles, run_all, write_eval_report

THRESHOLD = 0.90
PROMPTS = (GENERATE, REPAIR)

# The error names of a request the provider failed. ArchitectUnavailable wraps LLMUnavailable
# (all models failed, or rate limited locally) and DeadlineExceeded (a step deadline).
PROVIDER_ERRORS = frozenset(
    {"ArchitectUnavailable", "LLMUnavailable", "DeadlineExceeded", "TimeoutError"}
)
BUDGET_STOP = "BudgetExceeded"  # a call refused by the run's cost budget
PAUSED = "ProviderPaused"  # a request not started because the run paused
PAUSE_AFTER = 5
MIN_PREDICTED = 0.95
RETRY_RULE = (
    "A request that ends in a provider error (no spec attempt came back) is retried ONCE, at the "
    "end of the run segment, with the same prompts and settings. If it fails again, it counts as "
    "not valid. (Decided 2026-11-26, before the first live architect run; as AI-05.)"
)
VALIDITY_RULE = (
    "A run is valid only if at least 95% of each set's requests got a prediction (valid or not) "
    "after the one retry. Otherwise it is INVALID: a provider failure, not a measurement of the "
    "prompt, and it is repeated with the same prompts and data. (Decided 2026-11-26; as AI-05.)"
)
PAUSE_RULE = (
    f"After {PAUSE_AFTER} requests in a row end in a provider error, no new request starts: the "
    "run is PAUSED and resumed later with --resume; requests that never started are run then. "
    "(Decided 2026-11-26, after the AI-05 gate run of 2026-11-24 lost 48 requests to an outage.)"
)

Build = Callable[[ArchitectItem], Awaitable[ArchitectResult]]
Result = Outcome[ArchitectItem, ArchitectResult]


class ProviderPaused(Exception):
    """A request not started: the run paused on a provider outage."""


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
    budget_usd: float | None = None
    stopped: str | None = None  # the budget stopped the last segment: the run does not count
    paused: str | None = None  # the last segment paused on a provider outage: resume it
    retry_rule: str | None = None  # RETRY_RULE when the run used it
    retries: list[dict[str, Any]] = field(default_factory=list)  # one row per retried request
    pause_rule: str = PAUSE_RULE
    validity_rule: str = VALIDITY_RULE
    invalid: str | None = None  # a complete run with under MIN_PREDICTED predicted
    provider_errors: list[dict[str, Any]] = field(default_factory=list)  # failed call attempts

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


@dataclass
class _Segment:
    """What happened in this process: for the stopped / paused verdicts."""

    pause_after: int
    streak: int = 0  # requests in a row that ended in a provider error
    paused: bool = False
    budget_refused: int = 0
    not_started: int = 0


async def run_eval(
    sets: Mapping[str, Sequence[ArchitectItem]],
    *,
    live: bool,
    run_dir: Path,
    label: str = "run",
    resume: bool = False,
    end_to_end: bool = False,
    concurrency: int = 2,
    build: Build | None = None,
    budget_usd: float | None = None,
    retry_errors: bool = False,
    pause_after: int = PAUSE_AFTER,
) -> tuple[ArchitectReport, dict[str, list[Result]]]:
    """Run every request that has no outcome yet in `run_dir`, saving each as it finishes, then
    score everything saved. `resume=False` makes a new run folder (it must not exist);
    `resume=True` continues one (runlog.RunLog.resume refuses a different measurement).

    With `budget_usd`, every call checks the spend of all segments so far (the call log) plus
    this one against it (core.llm.usage.skill_run). With `retry_errors`, RETRY_RULE applies at
    the end of the segment (not after a pause: the provider is down; the next resume does it).
    `pause_after` requests in a row with a provider error pause the run (PAUSE_RULE)."""
    build = build or (_build_end_to_end if end_to_end else _build)
    manifest = manifest_for(sets, label=label, live=live, end_to_end=end_to_end)
    log = RunLog.resume(run_dir, manifest) if resume else RunLog.create(run_dir, manifest)
    seg = _Segment(pause_after=pause_after)
    started, ran = _now(), 0
    spent_before = log.calls_usage()["cost_usd"]
    try:
        with (
            log.logging_calls(),
            skill_run(None, spent_usd=spent_before, budget_usd=budget_usd),
        ):
            done = log.done()
            for name, items in sets.items():
                todo = [i for i in items if (name, i.id) not in done]
                ran += len(todo)
                await _run_requests(log, seg, name, todo, build, concurrency, attempt=1)
            if retry_errors and not seg.paused:
                for name, items in sets.items():
                    again = _to_retry(log, name, items)
                    await _run_requests(log, seg, name, again, build, concurrency, attempt=2)
    finally:  # also on Ctrl-C or a crash: the next resume sees what this process did
        log.add_segment(
            {
                "started": started,
                "ended": _now(),
                "git_head": git_head(),
                "resume": resume,
                "requests_run": ran,
                "budget_usd": budget_usd,
                "retry_errors": retry_errors,
                "paused": seg.paused,
                "budget_refused": seg.budget_refused,
            }
        )
    report = score(log, sets)
    report.budget_usd = budget_usd
    report.retry_rule = RETRY_RULE if retry_errors else None
    if seg.budget_refused:
        report.stopped = (
            f"the ${budget_usd} budget was used up; {seg.budget_refused} requests were not "
            "completed. This run does not count."
        )
    if seg.paused and seg.not_started:  # a pause with nothing left waiting changes nothing
        report.paused = (
            f"{seg.pause_after} requests in a row ended in a provider error; "
            f"{seg.not_started} requests or retries did not start. Resume the run later "
            "(--resume)."
        )
        report.invalid = None  # not a verdict yet: the waiting retries may still succeed
    _verdicts(report)
    return report, log.outcomes(sets)


async def _run_requests(
    log: RunLog,
    seg: _Segment,
    name: str,
    items: Sequence[ArchitectItem],
    build: Build,
    concurrency: int,
    *,
    attempt: int,
) -> None:
    usage_of: dict[str, dict[str, Any]] = {}

    async def tracked(item: ArchitectItem) -> ArchitectResult:
        if seg.paused:
            raise ProviderPaused
        with track_usage() as totals:  # this request's calls only (one task each)
            try:
                return await build(item)
            finally:
                usage_of[item.id] = asdict(totals)

    def save(o: Result) -> None:
        if o.error == PAUSED:
            seg.not_started += 1
            return  # never started: no line, so a resume runs it
        if o.error == BUDGET_STOP:
            seg.budget_refused += 1
            return  # not completed: no line (its spend is in the call log), a resume runs it
        log.record(name, o, usage=usage_of.get(o.item.id, {}), extra=row_extra(o), attempt=attempt)
        seg.streak = seg.streak + 1 if o.error in PROVIDER_ERRORS else 0
        if seg.pause_after and seg.streak >= seg.pause_after:
            seg.paused = True

    await run_all(items, tracked, concurrency=concurrency, on_done=save)


def _to_retry(log: RunLog, name: str, items: Sequence[ArchitectItem]) -> list[ArchitectItem]:
    """RETRY_RULE: requests whose only line is a first try that ended in a provider error."""
    latest = log.latest()
    return [
        i
        for i in items
        if (row := latest.get((name, i.id))) is not None
        and row.get("try", 1) == 1
        and row.get("error") in PROVIDER_ERRORS
    ]


def score(log: RunLog, sets: Mapping[str, Sequence[ArchitectItem]]) -> ArchitectReport:
    """The report, from the run folder alone."""
    m = log.manifest
    calls = log.calls_usage()
    report = ArchitectReport(
        created=m["created"],
        live=m["live"],
        end_to_end=m["end_to_end"],
        prompts={p: int(v["version"]) for p, v in m["prompts"].items()},
        model=m["model"],
        data_sources=m["data_sources"],
        # The call log has every attempt, also of requests that never finished; an old run
        # folder without one falls back to the sum over the lines.
        usage=calls if calls["calls"] else log.usage(),
        segments=log.segments(),
        missing={name: len(ids) for name, ids in log.missing(sets).items() if ids},
        retries=_retries(log),
        provider_errors=log.provider_errors(),
    )
    outcomes = log.outcomes(sets)
    for name in sets:
        report.sets[name] = compute_metrics(outcomes[name])
    if not report.missing:
        report.invalid = _invalid(outcomes, sets)
    return report


def _verdicts(report: ArchitectReport) -> None:
    if "all" not in report.sets:
        return
    report.gate = gate_verdict(report.sets["all"], live=report.live)
    reasons = report.gate["reasons"]
    if report.missing:
        reasons.append(f"requests with no outcome: {sum(report.missing.values())} (resume)")
    if report.stopped:
        reasons.append("stopped by the cost budget")
    if report.paused:
        reasons.append("paused on a provider outage")
    if report.invalid:
        reasons.append("invalid run (validity rule): repeat it")
    report.gate["passed"] = not reasons


def _invalid(
    outcomes: Mapping[str, Sequence[Result]], sets: Mapping[str, Sequence[ArchitectItem]]
) -> str | None:
    """VALIDITY_RULE: under 95% of a set's requests got a prediction (the Architect answered)."""
    bad = {}
    for name, items in sets.items():
        if not items:
            continue
        predicted = sum(o.result is not None for o in outcomes[name])
        if predicted / len(items) < MIN_PREDICTED:
            bad[name] = (len(items) - predicted, len(items))
    if not bad:
        return None
    counts = "; ".join(f"{name}: {k} of {n}" for name, (k, n) in bad.items())
    return (
        f"INVALID: provider failure (requests with no prediction, {counts}). "
        "Not a measurement of the prompt."
    )


def _retries(log: RunLog) -> list[dict[str, Any]]:
    """One row per retried request, from the run folder: its first error and how the retry
    ended (survives resume)."""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    out = []
    for row in log.rows():
        key = (row["set"], row["id"])
        if row.get("try", 1) == 1:
            first[key] = row
        elif key in first:
            out.append(
                {
                    "set": row["set"],
                    "id": row["id"],
                    "first_error": first[key].get("error"),
                    "retry": row.get("error") or "ok",
                }
            )
    return out


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
    lines = []
    if report.invalid:
        lines += [f"**{report.invalid}**", ""]
    lines += [
        f"# Skill Architect evaluation, {report.created}",
        "",
        f"Mode: {mode}. Prompts {report.prompts}, model `{report.model}`.",
        "",
    ]
    if report.paused:
        lines += [f"**PAUSED: provider outage.** {report.paused}", ""]
    if report.stopped:
        lines += [f"**STOPPED: budget.** {report.stopped}", ""]
    if report.missing:
        counts = ", ".join(f"{name}: {n}" for name, n in report.missing.items())
        lines += [f"**INCOMPLETE: requests with no outcome ({counts}). Resume the run.**", ""]
    if len(report.segments) > 1:
        lines += [f"Run in {len(report.segments)} segments (resumed).", ""]
    lines += [f"**Validity rule:** {report.validity_rule}", ""]
    lines += [f"**Pause rule:** {report.pause_rule}", ""]
    if report.retry_rule:
        ok = sum(r["retry"] == "ok" for r in report.retries)
        lines += [
            f"**Retry rule (decided before this run):** {report.retry_rule}",
            "",
            f"Retried: {len(report.retries)}; succeeded on retry: {ok}; "
            f"still failed (counted not valid): {len(report.retries) - ok}.",
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
    if report.provider_errors:
        lines += ["", "Failed call attempts (from the call log; no messages):", ""]
        lines += [
            "| error | HTTP status | provider | model link | count |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {e['error']} | {e['status']} | {e['provider'] or '-'} | {e['fallback']} "
            f"| {e['count']} |"
            for e in report.provider_errors
        ]
    u = report.usage
    budget = f" (budget ${report.budget_usd})" if report.budget_usd is not None else ""
    lines += [
        "",
        f"Usage: {u['calls']} calls, {u['input_tokens']} input / {u['output_tokens']} output "
        f"tokens, ${u['cost_usd']}{budget}.",
        "",
    ]
    return "\n".join(lines)


def exit_code(report: ArchitectReport) -> int:
    """0 passed (or no gate), 1 gate failed, 3 stopped by the budget, 4 invalid, 5 paused."""
    if report.paused:
        return 5
    if report.stopped:
        return 3
    if report.invalid:
        return 4
    return 0 if report.passed in (None, True) else 1


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"
