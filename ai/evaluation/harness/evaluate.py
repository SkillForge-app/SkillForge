"""Run paired with/without-skill evaluations and compare judge scores with human labels."""

import asyncio
import hashlib
import json
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.llm import complete, load_prompt, track_usage
from core.llm.gateway import BACKEND_ENV
from evaluation.benchmarks.dataset import RubricRecord
from evaluation.common import live_guard, model_for, run_all
from evaluation.harness.data import Condition, HumanLabel, SkillBenchmark

ANSWER_PROMPT = "evaluation/answer"
JUDGE_PROMPT = "evaluation/judge"
CALIBRATION_THRESHOLD = 0.80


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1)


class RubricScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_id: str
    passed: bool
    rationale: str = Field(min_length=1, max_length=1000)


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scores: list[RubricScore] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_rubric_ids(self) -> "JudgeResult":
        ids = [score.rubric_id for score in self.scores]
        if len(ids) != len(set(ids)):
            raise ValueError("judge returned duplicate rubric ids")
        return self


@dataclass(frozen=True)
class ArmResult:
    condition: Condition
    answer: str
    answer_sha256: str
    judgement: JudgeResult


@dataclass(frozen=True)
class PromptResult:
    prompt_id: str
    with_skill: ArmResult
    without_skill: ArmResult


@dataclass(frozen=True)
class CalibrationResult:
    n: int
    matches: int
    agreement: float | None
    threshold: float
    passed: bool
    reason: str | None = None
    cohen_kappa: float | None = None


@dataclass(frozen=True)
class RunResult:
    prompt_id: str
    result: PromptResult | None
    error: str | None
    latency_ms: float


@dataclass
class HarnessReport:
    report_type: str
    status: str
    created: str
    live: bool
    dataset: str
    dataset_version: str
    dataset_sha256: str
    skill: str
    skill_instructions_sha256: str
    review_status: str
    prompts: dict[str, int]
    models: dict[str, str]
    metrics: dict[str, Any]
    calibration: dict[str, Any]
    usage: dict[str, Any]


_ERROR_CODES = {
    "BudgetExceeded": "budget_exceeded",
    "ConfigError": "configuration_error",
    "LLMInputError": "invalid_input",
    "LLMOutputInvalid": "invalid_model_output",
    "LLMRefused": "model_refused",
    "LLMUnavailable": "provider_unavailable",
    "PromptFormatError": "prompt_format_error",
    "PromptInputError": "invalid_input",
    "PromptNotFound": "prompt_not_found",
    "ValueError": "invalid_model_output",
}


def error_code_for(error: str | None) -> str | None:
    if error is None:
        return None
    return _ERROR_CODES.get(error, "unexpected_error")


def calibration_status(result: CalibrationResult) -> str:
    return "passed" if result.passed else "failed"


def _answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def _cohen_kappa(rows: Sequence[dict[str, Any]]) -> float | None:
    compared = [row for row in rows if row["judge_passed"] is not None]
    n = len(compared)
    if not n:
        return None

    human_passed = sum(bool(row["human_passed"]) for row in compared)
    judge_passed = sum(bool(row["judge_passed"]) for row in compared)
    expected = (human_passed * judge_passed + (n - human_passed) * (n - judge_passed)) / (n * n)
    if expected == 1:
        return None

    observed = sum(bool(row["match"]) for row in compared) / n
    return (observed - expected) / (1 - expected)


async def _run_arm(
    prompt_id: str,
    text: str,
    skill_instructions: str,
    condition: Condition,
    benchmark: SkillBenchmark,
) -> ArmResult:
    answer = await complete(
        ANSWER_PROMPT,
        {"request": text, "skill_instructions": skill_instructions},
        GeneratedAnswer,
    )
    rubric = [
        {"id": item.id, "text": item.text, "critical": item.critical} for item in benchmark.rubric
    ]
    judgement = await complete(
        JUDGE_PROMPT,
        {
            "request": text,
            "answer": answer.answer,
            "rubric": json.dumps(rubric, ensure_ascii=False),
        },
        JudgeResult,
    )
    expected_ids = {item.id for item in benchmark.rubric}
    actual_ids = {score.rubric_id for score in judgement.scores}
    if actual_ids != expected_ids:
        raise ValueError(
            f"judge rubric ids differ for {prompt_id}/{condition}: "
            f"missing={sorted(expected_ids - actual_ids)}, "
            f"unknown={sorted(actual_ids - expected_ids)}"
        )
    return ArmResult(condition, answer.answer, _answer_hash(answer.answer), judgement)


async def _run_prompt(
    text: str, prompt_id: str, benchmark: SkillBenchmark, instructions: str
) -> PromptResult:
    with_skill, without_skill = await asyncio.gather(
        _run_arm(prompt_id, text, instructions, "with_skill", benchmark),
        _run_arm(prompt_id, text, "", "without_skill", benchmark),
    )
    return PromptResult(prompt_id, with_skill, without_skill)


def _scores(arm: ArmResult, rubric: Sequence[RubricRecord]) -> dict[str, float | int]:
    score_map = {score.rubric_id: score.passed for score in arm.judgement.scores}
    total = len(score_map)
    critical = [item.id for item in rubric if item.critical]
    critical_passed = sum(score_map[item] for item in critical)
    return {
        "n": total,
        "passed": sum(score_map.values()),
        "pass_rate": sum(score_map.values()) / total if total else 0.0,
        "critical_n": len(critical),
        "critical_passed": critical_passed,
        "critical_pass_rate": critical_passed / len(critical) if critical else 1.0,
    }


def _arm_rows(result: PromptResult) -> list[ArmResult]:
    return [result.with_skill, result.without_skill]


def compute_metrics(results: Sequence[RunResult], rubric: Sequence[RubricRecord]) -> dict[str, Any]:
    completed = [row.result for row in results if row.result is not None]
    arm_scores: dict[str, list[dict[str, float | int]]] = {
        "with_skill": [],
        "without_skill": [],
    }
    for result in completed:
        for arm in _arm_rows(result):
            arm_scores[arm.condition].append(_scores(arm, rubric))

    metrics: dict[str, Any] = {"n": len(results), "completed": len(completed)}
    for condition, rows in arm_scores.items():
        denominator = sum(int(row["n"]) for row in rows)
        passed = sum(int(row["passed"]) for row in rows)
        critical_n = sum(int(row["critical_n"]) for row in rows)
        critical_passed = sum(int(row["critical_passed"]) for row in rows)
        metrics[condition] = {
            "rubric_items": denominator,
            "passed": passed,
            "pass_rate": passed / denominator if denominator else None,
            "critical_items": critical_n,
            "critical_passed": critical_passed,
            "critical_pass_rate": critical_passed / critical_n if critical_n else None,
        }
    left = metrics["with_skill"]["pass_rate"]
    right = metrics["without_skill"]["pass_rate"]
    metrics["uplift"] = left - right if left is not None and right is not None else None
    metrics["errors"] = dict(Counter(error_code_for(row.error) for row in results if row.error))
    return metrics


def _check_model_mode(live: bool) -> None:
    backend = os.environ.get(BACKEND_ENV, "litellm").strip().lower()
    if not live and backend != "fake":
        raise RuntimeError(
            f"refusing real model calls without live=True; set {BACKEND_ENV}=fake for a smoke run"
        )
    if live and backend == "fake":
        raise RuntimeError(f"live evaluation cannot use {BACKEND_ENV}=fake")


async def calibrate_judge(
    benchmark: SkillBenchmark,
    labels: Sequence[HumanLabel],
    *,
    live: bool,
    concurrency: int = 2,
) -> tuple[CalibrationResult, list[dict[str, Any]]]:
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if benchmark.skill.review_status != "reviewed" and live:
        raise ValueError("live calibration requires a reviewed skill in the immutable release")
    _check_model_mode(live)
    if live:
        refused = live_guard(True, JUDGE_PROMPT)
        if refused is not None:
            raise RuntimeError(f"live calibration refused (code {refused})")
    if not labels:
        return CalibrationResult(
            n=0,
            matches=0,
            agreement=None,
            threshold=CALIBRATION_THRESHOLD,
            passed=False,
            reason="no human calibration labels were supplied",
        ), []

    label_keys = [
        (
            label.prompt_id,
            label.condition,
            _answer_hash(label.answer),
            label.reviewer,
        )
        for label in labels
    ]
    if len(label_keys) != len(set(label_keys)):
        raise ValueError("human calibration labels contain duplicate entries")

    prompts = {prompt.id: prompt.text for prompt in benchmark.prompts}
    rubric = {item.id for item in benchmark.rubric}
    for label in labels:
        if prompts.get(label.prompt_id) != label.prompt:
            raise ValueError(f"human label prompt does not match release: {label.prompt_id}")
        unknown = set(label.rubric_scores) - rubric
        if unknown:
            raise ValueError(
                f"human label has unknown rubric ids for {label.prompt_id}: {sorted(unknown)}"
            )

    async def judge(label: HumanLabel) -> tuple[HumanLabel, JudgeResult]:
        result = await complete(
            JUDGE_PROMPT,
            {
                "request": label.prompt,
                "answer": label.answer,
                "rubric": json.dumps(
                    [
                        {"id": item.id, "text": item.text, "critical": item.critical}
                        for item in benchmark.rubric
                    ],
                    ensure_ascii=False,
                ),
            },
            JudgeResult,
        )
        actual = {score.rubric_id for score in result.scores}
        if actual != rubric:
            raise ValueError(
                f"judge rubric ids differ for calibration prompt {label.prompt_id}: "
                f"missing={sorted(rubric - actual)}, unknown={sorted(actual - rubric)}"
            )
        return label, result

    outcomes = await run_all(labels, judge, concurrency=concurrency)
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        if outcome.result is None:
            for rubric_id, human_passed in outcome.item.rubric_scores.items():
                rows.append(
                    {
                        "record_type": "calibration_decision",
                        "status": "failed",
                        "prompt_id": outcome.item.prompt_id,
                        "condition": outcome.item.condition,
                        "reviewer": outcome.item.reviewer,
                        "rubric_id": rubric_id,
                        "human_passed": human_passed,
                        "judge_passed": None,
                        "match": False,
                        "answer_sha256": _answer_hash(outcome.item.answer),
                        "error": outcome.error,
                        "error_code": error_code_for(outcome.error),
                    }
                )
            continue
        label, judgement = outcome.result
        predictions = {score.rubric_id: score.passed for score in judgement.scores}
        rationales = {score.rubric_id: score.rationale for score in judgement.scores}
        for rubric_id, human_passed in label.rubric_scores.items():
            rows.append(
                {
                    "record_type": "calibration_decision",
                    "status": "completed",
                    "prompt_id": label.prompt_id,
                    "condition": label.condition,
                    "reviewer": label.reviewer,
                    "rubric_id": rubric_id,
                    "human_passed": human_passed,
                    "judge_passed": predictions[rubric_id],
                    "match": predictions[rubric_id] == human_passed,
                    "judge_rationale": rationales[rubric_id],
                    "answer_sha256": _answer_hash(label.answer),
                    "error": None,
                    "error_code": None,
                }
            )
    labeled_rows = [row for row in rows if "match" in row]
    matches = sum(bool(row["match"]) for row in labeled_rows)
    agreement = matches / len(labeled_rows) if labeled_rows else None
    failed_calls = sum(row.get("error") is not None for row in rows)
    passed = agreement is not None and agreement >= CALIBRATION_THRESHOLD and failed_calls == 0
    return (
        CalibrationResult(
            n=len(labeled_rows),
            matches=matches,
            agreement=agreement if labeled_rows else None,
            threshold=CALIBRATION_THRESHOLD,
            passed=passed,
            reason="judge calls failed"
            if failed_calls
            else (None if passed else "agreement is below 80%"),
            cohen_kappa=_cohen_kappa(labeled_rows),
        ),
        rows,
    )


async def run_benchmark(
    benchmark: SkillBenchmark,
    skill_instructions: str,
    *,
    live: bool,
    concurrency: int = 2,
) -> tuple[HarnessReport, list[RunResult]]:
    """Evaluate every test prompt twice; skill instructions are compiler-generated text."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if benchmark.skill.review_status != "reviewed" and live:
        raise ValueError("live evaluation requires a reviewed skill in the immutable release")
    _check_model_mode(live)
    if live:
        for prompt_id in (ANSWER_PROMPT, JUDGE_PROMPT):
            refused = live_guard(True, prompt_id)
            if refused is not None:
                raise RuntimeError(f"live evaluation refused for {prompt_id} (code {refused})")
    with track_usage() as usage:
        outcomes = await run_all(
            benchmark.prompts,
            lambda prompt: _run_prompt(prompt.text, prompt.id, benchmark, skill_instructions),
            concurrency=concurrency,
        )

    results = [
        RunResult(
            prompt_id=outcome.item.id,
            result=outcome.result,
            error=outcome.error,
            latency_ms=outcome.latency_ms,
        )
        for outcome in outcomes
    ]
    metrics = compute_metrics(results, benchmark.rubric)
    run_status = (
        "completed"
        if metrics["completed"] == metrics["n"]
        else ("completed_with_errors" if metrics["completed"] else "failed")
    )
    calibration = asdict(
        CalibrationResult(
            n=0,
            matches=0,
            agreement=None,
            threshold=CALIBRATION_THRESHOLD,
            passed=False,
            reason="calibrate separately against reviewed human labels",
        )
    )
    calibration["status"] = "not_calibrated"
    report = HarnessReport(
        report_type="benchmark",
        status=run_status,
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        live=live,
        dataset=benchmark.dataset,
        dataset_version=benchmark.version,
        dataset_sha256=benchmark.dataset_sha256,
        skill=benchmark.skill.name,
        skill_instructions_sha256=_answer_hash(skill_instructions),
        review_status=benchmark.skill.review_status,
        prompts={
            ANSWER_PROMPT: load_prompt(ANSWER_PROMPT).version,
            JUDGE_PROMPT: load_prompt(JUDGE_PROMPT).version,
        },
        models={"answer": model_for(ANSWER_PROMPT), "judge": model_for(JUDGE_PROMPT)},
        metrics=metrics,
        calibration=calibration,
        usage={
            "calls": usage.calls,
            "errors": usage.errors,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(usage.cost_usd, 4),
        },
    )
    return report, results


def write_report(
    report: HarnessReport,
    results: Sequence[RunResult],
    out_dir: Path,
    *,
    reserved: bool = False,
) -> Path:
    if reserved:
        if not out_dir.is_dir() or any(out_dir.iterdir()):
            raise FileExistsError(f"reserved output directory is missing or not empty: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=False)
    with (out_dir / "report.json").open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n")
    with (out_dir / "predictions.jsonl").open("x", encoding="utf-8", newline="\n") as file:
        for row in results:
            record: dict[str, Any] = {
                "record_type": "prediction",
                "status": "completed" if row.result is not None else "failed",
                "prompt_id": row.prompt_id,
                "error": row.error,
                "error_code": error_code_for(row.error),
                "latency_ms": round(row.latency_ms, 2),
            }
            if row.result is not None:
                record["arms"] = {
                    arm.condition: {
                        "answer": arm.answer,
                        "answer_sha256": arm.answer_sha256,
                        "scores": [score.model_dump() for score in arm.judgement.scores],
                    }
                    for arm in _arm_rows(row.result)
                }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (out_dir / "report.md").open("x", encoding="utf-8", newline="\n") as file:
        file.write(render_markdown(report))
    return out_dir


def render_markdown(report: HarnessReport) -> str:
    calibration = report.calibration
    uplift = report.metrics["uplift"]
    agreement = (
        "not measured"
        if calibration["agreement"] is None
        else f"{calibration['agreement']:.1%} ({calibration['matches']}/{calibration['n']})"
    )
    kappa = (
        "not measured"
        if calibration["cohen_kappa"] is None
        else f"{calibration['cohen_kappa']:.3f}"
    )
    uplift_text = "n/a" if uplift is None else f"{uplift:+.1%}"
    lines = [
        f"# AI-16 evaluation: {report.skill}",
        "",
        f"- Run status: {report.status}",
        f"- Mode: {'live' if report.live else 'fake (does not count)'}",
        f"- Dataset: {report.dataset} {report.dataset_version}",
        f"- Dataset SHA-256: `{report.dataset_sha256}`",
        f"- Skill instructions SHA-256: `{report.skill_instructions_sha256}`",
        f"- Review status: {report.review_status}",
        f"- Prompts: {report.metrics['completed']}/{report.metrics['n']} completed",
        "",
        "| Condition | Rubric pass rate | Critical pass rate |",
        "|---|---:|---:|",
    ]
    for key, title in (("with_skill", "With skill"), ("without_skill", "Without skill")):
        metrics = report.metrics[key]
        rate = metrics["pass_rate"]
        critical = metrics["critical_pass_rate"]
        lines.append(
            f"| {title} | {'n/a' if rate is None else f'{rate:.1%}'} "
            f"| {'n/a' if critical is None else f'{critical:.1%}'} |"
        )
    lines.extend(
        [
            "",
            f"- Uplift (with minus without): {uplift_text}",
            f"- Judge-human agreement: {agreement}; gate "
            f"{'PASSED' if calibration['passed'] else 'NOT PASSED'} "
            f"(threshold {calibration['threshold']:.0%})",
            f"- Cohen's kappa (informational): {kappa}",
            f"- LLM usage: {report.usage['calls']} calls, ${report.usage['cost_usd']:.4f}",
            "",
            "Fake runs and runs against draft benchmark data are smoke checks only; they do not "
            "satisfy AI-16.",
            "",
        ]
    )
    return "\n".join(lines)
