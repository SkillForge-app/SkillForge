"""Tracked runs (AI-25): id-only copies of a live run's raw predictions, for offline re-scoring.

The raw `runs/<id>/predictions.jsonl` of a live evaluation stays out of Git (it holds request
text). `convert()` READS it (never moves, renames or deletes it) and writes
`ai/evaluation/<area>/reports/runs/<id>/predictions.jsonl` with, per line, exactly:

    id         "<set>:<request id>": well-formed (ID_FORMAT) AND one of the ids in the tracked
               label files at the entry's recorded_at (rescore.known_ids), so no text can
               ride in on an id
    expected   the labels the run was scored against
    predicted  the labels the model gave (closed vocabularies only); from runs that record
               them (2026-11-25 on): mentioned_targets (platform names, a label) and
               question_rule_kept (a boolean computed at run time: 3-5 questions when it
               asked). Never the question text.
    error      an error class (provider_error, parse_error, timeout, budget, other) or null

No request text, no rationale or summary, no raw error message: every value is checked against
the closed vocabularies and every id against the label files, so free text cannot get in.
Problems never echo an id (it could be the text being kept out).

Two hashes are recorded for each: the source file's sha256 (raw bytes, as the old reports
recorded it) and the tracked file's (LF-normalised, the same on every OS).
"""

import hashlib
import json
import re
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Any, get_args

from core.analysis.types import HarmCategory, SafetyCondition
from core.spec import DOMAIN_AREAS, KINDS, RISK_LEVELS, TARGETS
from evaluation.common import text_sha256
from evaluation.reproduce.strict import DuplicateKeyError, loads_unique

FIELDS = ("id", "expected", "predicted", "error")
# "<set>:<id>", or "normal:<set>:<id>" for the safety screen's everyday requests. Matched with
# fullmatch (a trailing newline does not pass). The allowlist is the real guard; this is a second.
ID_FORMAT = re.compile(r"[a-z]+:(?:[a-z]+:)?[a-z0-9._/-]{1,80}")
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


# The keys a problem message may name: the tracked fields, the label fields, and the source
# run's own. Any other key is "(name not shown)".
NAMES = frozenset({*FIELDS, *VOCAB, *LISTS, "set", "text", "latency_ms"})


class TrackError(ValueError):
    pass


def parse_lines(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """A run file's lines, and one problem for each line that is not a single JSON object with
    unique keys at every depth (json.loads would keep the last of two equal keys, hiding the
    first). Problems name the line and a known key, never a value."""
    lines: list[dict[str, Any]] = []
    problems: list[str] = []
    for n, raw in enumerate((r for r in text.splitlines() if r.strip()), 1):
        try:
            value = loads_unique(raw, NAMES)
        except DuplicateKeyError as exc:
            problems.append(f"line {n}: {exc}")
            continue
        except ValueError:
            problems.append(f"line {n}: not valid JSON (value not shown)")
            continue
        if not isinstance(value, dict):
            problems.append(f"line {n}: not a JSON object (value not shown)")
            continue
        lines.append(value)
    return lines, problems


def error_class(name: str | None) -> str | None:
    """provider_error, parse_error, timeout, budget or other; None when there was no error."""
    return None if name is None else _ERROR_CLASS.get(name, "other")


def id_problem(value: object, known: Collection[str] | None) -> str | None:
    """Why `value` can't be a tracked id, or None. `known` is the allowlist at recorded_at; None
    (only `reproduce check` without git history) checks the format alone. Never echoes the id."""
    if not isinstance(value, str) or not ID_FORMAT.fullmatch(value):
        return "the id is not well-formed (value not shown)"
    if known is not None and value not in known:
        return "the id is not in the label files at recorded_at (value not shown)"
    return None


def _labels(values: object) -> dict[str, Any]:
    """The labels, each checked against its closed vocabulary. A problem names the field only when
    it is a known one, and never shows a value: either could be the text being kept out."""
    if not isinstance(values, dict):
        raise TrackError("the labels are not an object (value not shown)")
    out: dict[str, Any] = {}
    try:
        return _checked(values, out)
    except TypeError:  # e.g. an unhashable key or value: never a vocabulary label
        raise TrackError("a label of an unexpected type (value not shown)") from None


def _checked(values: dict[Any, Any], out: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if key in LISTS:
            if value is not None and (
                not isinstance(value, list) or not all(_in_vocab(c, LISTS[key]) for c in value)
            ):
                raise TrackError(f"{key}: the value is outside the vocabulary (value not shown)")
            out[key] = value
        elif key in VOCAB:
            if not _in_vocab(value, VOCAB[key]):
                raise TrackError(f"{key}: the value is outside the vocabulary (value not shown)")
            out[key] = value
        else:
            raise TrackError("a label field outside the allowlist (name not shown)")
    return out


def _in_vocab(value: object, vocab: set[Any]) -> bool:
    try:
        return value in vocab
    except TypeError:  # unhashable (a list or an object): never a vocabulary value
        return False


def convert_line(row: dict[str, Any], known: Collection[str]) -> dict[str, Any]:
    """One id-only line from an analyzer or safety prediction line. `known`: the ids in the label
    files at the run's recorded_at (rescore.known_ids); any other id is refused."""
    line_id = f"{row.get('set')}:{row.get('id')}"
    problem = id_problem(line_id, known)
    if problem:
        raise TrackError(problem)
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
        raise TrackError("unknown prediction format (field names not shown)")
    return {
        "id": line_id,
        "expected": _labels(expected),
        "predicted": _labels(predicted),
        "error": error_class(row.get("error")),
    }


def canonical(lines: Iterable[dict[str, Any]]) -> str:
    """The one form a tracked file may have: one json.dumps(sort_keys=True) line each, LF."""
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)


def convert(source: Path, target: Path, known: Collection[str]) -> dict[str, Any]:
    """Write the id-only file; return its record (hashes, line count). Reads `source` only.
    `known`: rescore.known_ids(repo, recorded_at). Nothing is written if any line is refused."""
    raw = source.read_bytes()
    rows, problems = parse_lines(raw.decode("utf-8"))
    if problems:
        raise TrackError(problems[0])
    lines = []
    for n, row in enumerate(rows, 1):
        try:
            lines.append(convert_line(row, known))
        except TrackError as exc:
            raise TrackError(f"line {n}: {exc}") from None
    ids = [line["id"] for line in lines]
    if len(set(ids)) != len(ids):
        raise TrackError("duplicate ids in the source run")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = canonical(lines)
    target.write_text(body, encoding="utf-8", newline="\n")
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "sha256": text_sha256(target),
        "lines": len(lines),
    }


def bad_fields(lines: Iterable[dict[str, Any]], known: Collection[str] | None) -> list[str]:
    """Any field outside the allowlist, or an id that is malformed or (with `known`, the ids at
    recorded_at) unknown, anywhere in a tracked file. Empty when it is clean. `known=None` checks
    the id format only: pass it explicitly, and only where git history is unavailable."""
    problems = []
    for n, line in enumerate(lines, 1):
        extra = set(line) - set(FIELDS)
        if extra:
            problems.append(
                f"line {n}: {len(extra)} field(s) outside the allowlist (names not shown)"
            )
        problem = id_problem(line.get("id"), known)
        if problem:
            problems.append(f"line {n}: {problem}")
        for part in ("expected", "predicted"):
            try:
                _labels(line.get(part) or {})
            except TrackError as exc:
                problems.append(f"line {n} {part}: {exc}")
        if not _in_vocab(line.get("error"), {None, *ERROR_CLASSES}):
            problems.append(f"line {n}: error is not an error class (value not shown)")
    return problems


__all__ = [
    "ERROR_CLASSES",
    "FIELDS",
    "ID_FORMAT",
    "TrackError",
    "bad_fields",
    "canonical",
    "convert",
    "convert_line",
    "id_problem",
    "parse_lines",
]
