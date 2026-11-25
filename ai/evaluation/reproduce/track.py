"""Tracked runs (AI-25): id-only copies of a live run's raw predictions, for offline re-scoring.

The raw `runs/<id>/predictions.jsonl` of a live evaluation stays out of Git (it holds request
text). `python -m evaluation.reproduce track` READS it (never moves, renames or deletes it) and
writes `ai/evaluation/<area>/reports/runs/<id>/predictions.jsonl` with, per line, exactly:

    id         "<set>:<request id>"
    expected   the labels the run was scored against
    predicted  the labels the model gave (closed vocabularies only); from runs that record
               them (2026-11-25 on): mentioned_targets (platform names, a label) and
               question_rule_kept (a boolean computed at run time: 3-5 questions when it
               asked). Never the question text.
    error      an error class (provider_error, parse_error, timeout, budget, other) or null

No request text, no rationale or summary, no raw error message: every value is checked against
the closed vocabularies, so free text cannot get in. Two hashes are recorded for each: the
source file's sha256 (raw bytes, as the old reports recorded it) and the tracked file's
(LF-normalised, the same on every OS).
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, get_args

from core.analysis.types import HarmCategory, SafetyCondition
from core.spec import DOMAIN_AREAS, KINDS, RISK_LEVELS, TARGETS
from evaluation.common import text_sha256

FIELDS = ("id", "expected", "predicted", "error")
ERROR_CLASSES = ("provider_error", "parse_error", "timeout", "budget", "other")
ERROR = "<error>"  # what the evaluations print for "no prediction"
_ERROR_CLASS = {
    "LLMUnavailable": "provider_error",
    "SafetyUnavailable": "provider_error",
    "LLMRefused": "provider_error",
    "LLMOutputInvalid": "parse_error",
    "ValidationError": "parse_error",
    "DeadlineExceeded": "timeout",
    "TimeoutError": "timeout",
    "BudgetExceeded": "budget",
}
VOCAB: dict[str, set[Any]] = {
    "kind": {*KINDS, ERROR},
    "domain_area": {*DOMAIN_AREAS, ERROR},
    "risk": {*RISK_LEVELS, ERROR},
    "needs_clarification": {True, False, None},
    "verdict": {"allow", "block", ERROR},
    "category": {*get_args(HarmCategory), None},
    "question_rule_kept": {True, False, None},
}
LISTS: dict[str, set[str]] = {
    "conditions": set(get_args(SafetyCondition)),
    "mentioned_targets": set(TARGETS),
}


class TrackError(ValueError):
    pass


def error_class(name: str | None) -> str | None:
    """provider_error, parse_error, timeout, budget or other; None when there was no error."""
    return None if name is None else _ERROR_CLASS.get(name, "other")


def _labels(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key in LISTS:
            if value is not None and (
                not isinstance(value, list) or any(c not in LISTS[key] for c in value)
            ):
                raise TrackError(f"{key} outside the vocabulary: {value!r}")
            out[key] = value
        elif key in VOCAB:
            if value not in VOCAB[key]:
                raise TrackError(f"{key}={value!r} is outside its vocabulary")
            out[key] = value
        else:
            raise TrackError(f"unexpected label field {key!r}")
    return out


def convert_line(row: dict[str, Any]) -> dict[str, Any]:
    """One id-only line from an analyzer or safety prediction line."""
    if "predicted" in row:  # analyzer: expected/predicted are dicts of the gated fields
        clar = row.get("needs_clarification") or {}
        expected = {**row["expected"], "needs_clarification": clar.get("expected")}
        predicted = {**row["predicted"], "needs_clarification": clar.get("predicted")}
        if "mentioned_targets" in row:  # runs from 2026-11-25 on
            expected["mentioned_targets"] = row["mentioned_targets"]["expected"]
            predicted["mentioned_targets"] = row["mentioned_targets"]["predicted"]
        if "question_rule_kept" in row:
            predicted["question_rule_kept"] = row["question_rule_kept"]
    elif "verdict" in row:  # safety
        expected = {"verdict": row["expected"]}
        predicted = {
            "verdict": row["verdict"],
            "category": row["category"],
            "conditions": row["conditions"],
        }
    else:
        raise TrackError(f"unknown prediction format: {sorted(row)}")
    return {
        "id": f"{row['set']}:{row['id']}",
        "expected": _labels(expected),
        "predicted": _labels(predicted),
        "error": error_class(row.get("error")),
    }


def convert(source: Path, target: Path) -> dict[str, Any]:
    """Write the id-only file; return its record (hashes, line count). Reads `source` only."""
    raw = source.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    lines = [convert_line(r) for r in rows]
    ids = [line["id"] for line in lines]
    if len(set(ids)) != len(ids):
        raise TrackError("duplicate ids in the source run")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)
    target.write_text(body, encoding="utf-8", newline="\n")
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "sha256": text_sha256(target),
        "lines": len(lines),
    }


def bad_fields(lines: Iterable[dict[str, Any]]) -> list[str]:
    """Any field outside the allowlist, anywhere in a tracked file (empty when it is clean)."""
    problems = []
    for n, line in enumerate(lines, 1):
        extra = set(line) - set(FIELDS)
        if extra:
            problems.append(f"line {n}: fields {sorted(extra)} are not allowed")
        for part in ("expected", "predicted"):
            try:
                _labels(line.get(part) or {})
            except TrackError as exc:
                problems.append(f"line {n} {part}: {exc}")
        if line.get("error") not in (None, *ERROR_CLASSES):
            problems.append(f"line {n}: error {line.get('error')!r} is not an error class")
    return problems


__all__ = ["ERROR_CLASSES", "FIELDS", "TrackError", "bad_fields", "convert", "convert_line"]
