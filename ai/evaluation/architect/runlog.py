"""The run folder of one architect evaluation, written while the run goes (AI-07 pre-flight).

A paid run must never be lost to a crash, a killed process or a bug in scoring. So the run
folder is made before the first model call, and every outcome is saved the moment it is known:

    runs/<UTC time>/
        manifest.json      written first: what this run measures (prompts, model, data, items)
        predictions.jsonl  one line per finished request, appended and flushed to disk at once
        specs/<id>.json    every generated spec, written before its line
        segments.jsonl     one line per process that worked on the run (start, end, git HEAD)
        calls.jsonl        one CallRecord per model call attempt, as it happens: metadata
                           only (tokens, cost, model, fallback link, error class, HTTP status,
                           the sanitized provider error detail), never prompt or output text

`--resume runs/<id>` continues such a run: it refuses when the prompts, model, data or items
differ from the manifest, skips every request that already has a line, and runs the rest.
Scoring always reads the lines back from the file, so a fresh run and a resumed one are scored
by the same code. The run folder is ignored by Git (request text and model output stay local).
"""

import json
import logging
import os
import re
import subprocess
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agents import ArchitectResult
from core.spec import Issue, SkillSpec
from evaluation.architect.data import ArchitectItem
from evaluation.common import AI_ROOT, Outcome

MANIFEST = "manifest.json"
PREDICTIONS = "predictions.jsonl"
SEGMENTS = "segments.jsonl"
CALLS = "calls.jsonl"
SPECS = "specs"
LLM_LOGGER = "skillforge.llm"  # core.llm.usage.log_call logs every CallRecord here
MANIFEST_VERSION = 1
# What must be the same for a resumed run to be one measurement. Not compared: when it started,
# the git HEAD (a bug fix in scoring between segments is fine; segments.jsonl records each HEAD).
COMPARED = ("label", "live", "end_to_end", "model", "fallbacks", "prompts", "data_sources", "ids")
# A request refused by the cost budget, or not started because the run paused on a provider
# outage, was never attempted: a resumed run runs it. (The harness does not write lines for
# them; a line with one of these errors from elsewhere is still not an outcome.)
NOT_ATTEMPTED = frozenset({"BudgetExceeded", "ProviderPaused"})
_PROVIDER = re.compile(r"(?:^|; )provider=([^;]+)")
USAGE_FIELDS = ("calls", "errors", "input_tokens", "output_tokens", "cost_usd")

Result = Outcome[ArchitectItem, ArchitectResult]


class ResumeError(ValueError):
    """The run folder cannot be resumed (missing, unreadable, or a different measurement)."""


def spec_filename(item_id: str) -> str:
    return item_id.replace(":", "_").replace("/", "_") + ".json"


def git_head() -> str | None:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=AI_ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or None if out.returncode == 0 else None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RunLog:
    run_dir: Path
    manifest: dict[str, Any]

    # ------------------------------------------------------------------ open

    @classmethod
    def create(cls, run_dir: Path, manifest: Mapping[str, Any]) -> "RunLog":
        """A new run folder. Fails if it exists: a run is never written over."""
        (run_dir / SPECS).mkdir(parents=True, exist_ok=False)
        data = {"manifest_version": MANIFEST_VERSION, "created": _now(), **manifest}
        with (run_dir / MANIFEST).open("x", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            _sync(f)
        return cls(run_dir, data)

    @classmethod
    def resume(cls, run_dir: Path, manifest: Mapping[str, Any]) -> "RunLog":
        """An existing run folder, if `manifest` describes the same measurement."""
        path = run_dir / MANIFEST
        try:
            saved: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ResumeError(f"{run_dir} has no {MANIFEST}: not a run folder") from None
        except ValueError:
            raise ResumeError(f"{path} is not valid JSON") from None
        if saved.get("manifest_version") != MANIFEST_VERSION:
            raise ResumeError(f"{path}: manifest_version {saved.get('manifest_version')!r}")
        differ = [key for key in COMPARED if saved.get(key) != _plain(manifest.get(key))]
        if differ:
            raise ResumeError(
                "cannot resume: this run measured something else; these differ from "
                f"{path.name}: {', '.join(differ)}"
            )
        (run_dir / SPECS).mkdir(exist_ok=True)
        return cls(run_dir, saved)

    # ------------------------------------------------------------------ write

    def record(
        self,
        set_name: str,
        outcome: Result,
        *,
        usage: Mapping[str, Any],
        extra: Mapping[str, Any] | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Save one finished request: its spec first, then its line, flushed to disk."""
        r = outcome.result
        if r is not None and r.spec is not None:
            spec = self.run_dir / SPECS / spec_filename(outcome.item.id)
            spec.write_text(r.spec.model_dump_json(indent=2), encoding="utf-8")
        row = {
            "set": set_name,
            "id": outcome.item.id,
            "try": attempt,
            "ok": bool(r and r.ok),
            "attempts": r.attempts if r else None,
            "issues": [_issue(i) for i in r.issues] if r else [],
            "error": outcome.error,
            "latency_ms": round(outcome.latency_ms, 1),
            "usage": {k: usage.get(k, 0) for k in USAGE_FIELDS},
            **(extra or {}),
        }
        path = self.run_dir / PREDICTIONS
        # A crash can leave the last line cut off without its newline: start on a fresh line,
        # or this line would be glued to the broken one and lost with it.
        lead = "\n" if _ends_mid_line(path) else ""
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(lead + json.dumps(row, ensure_ascii=False) + "\n")
            _sync(f)
        return row

    def add_segment(self, segment: Mapping[str, Any]) -> None:
        with (self.run_dir / SEGMENTS).open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(dict(segment), ensure_ascii=False) + "\n")
            _sync(f)

    # ------------------------------------------------------------------ read

    def rows(self) -> list[dict[str, Any]]:
        """Every line, in the order written. A last line cut off by a crash is skipped (its
        request has no outcome and runs again on resume)."""
        path = self.run_dir / PREDICTIONS
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def latest(self) -> dict[tuple[str, str], dict[str, Any]]:
        """The last line of each (set, id): a retry's line replaces the first try's."""
        return {(r["set"], r["id"]): r for r in self.rows()}

    def done(self) -> set[tuple[str, str]]:
        """Requests with an outcome. A request refused by the budget has none."""
        return {key for key, r in self.latest().items() if r.get("error") not in NOT_ATTEMPTED}

    def segments(self) -> list[dict[str, Any]]:
        path = self.run_dir / SEGMENTS
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def usage(self) -> dict[str, Any]:
        """Usage summed over every line written (all segments, first tries and retries). A call
        whose request never finished (the process died during it) is not in any line."""
        total: dict[str, Any] = dict.fromkeys(USAGE_FIELDS, 0)
        for r in self.rows():
            for k in USAGE_FIELDS:
                total[k] += r.get("usage", {}).get(k, 0)
        total["cost_usd"] = round(total["cost_usd"], 4)
        return total

    # ------------------------------------------------------------------ the call log

    @contextmanager
    def logging_calls(self) -> Iterator[None]:
        """Append every CallRecord logged in the block to calls.jsonl (flushed at once), so a
        provider failure can be diagnosed after the run and the spend of a request that never
        finished is still counted."""
        logger = logging.getLogger(LLM_LOGGER)
        handler = _CallFileHandler(self.run_dir / CALLS)
        level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)  # successful calls are logged at INFO
        try:
            yield
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
            handler.close()

    def calls(self) -> list[dict[str, Any]]:
        path = self.run_dir / CALLS
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # cut off by a crash
        return out

    def calls_usage(self) -> dict[str, Any]:
        """Usage from the call log: every attempt of every segment, including the calls of a
        request that never finished. Zeros when there is no call log (an old run folder)."""
        total: dict[str, Any] = dict.fromkeys(USAGE_FIELDS, 0)
        for c in self.calls():
            total["calls"] += 1
            total["errors"] += c.get("status") == "error"
            total["input_tokens"] += c.get("input_tokens") or 0
            total["output_tokens"] += c.get("output_tokens") or 0
            total["cost_usd"] += c.get("cost_usd") or 0.0
        total["cost_usd"] = round(total["cost_usd"], 4)
        return total

    def provider_errors(self) -> list[dict[str, Any]]:
        """Failed call attempts counted by (error class, HTTP status, provider, model link).
        Only closed fields: the provider name comes from the sanitized error_detail."""
        counts: Counter[tuple[str, int | None, str | None, int]] = Counter()
        for c in self.calls():
            if c.get("status") != "error":
                continue
            match = _PROVIDER.search(c.get("error_detail") or "")
            key = (
                str(c.get("error_type")),
                c.get("error_status"),
                match.group(1) if match else None,
                int(c.get("fallback") or 0),
            )
            counts[key] += 1
        return [
            {"error": e, "status": s, "provider": p, "fallback": f, "count": n}
            for (e, s, p, f), n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ]

    def outcomes(self, sets: Mapping[str, Sequence[ArchitectItem]]) -> dict[str, list[Result]]:
        """The outcome of every request that has one, rebuilt from the lines and spec files, in
        the items' order (so the metrics never depend on which call finished first)."""
        latest = self.latest()
        versions = {p: int(v["version"]) for p, v in self.manifest.get("prompts", {}).items()}
        out: dict[str, list[Result]] = {}
        for name, items in sets.items():
            out[name] = []
            for item in items:
                row = latest.get((name, item.id))
                if row is None or row.get("error") in NOT_ATTEMPTED:
                    continue
                out[name].append(self._outcome(item, row, versions))
        return out

    def missing(self, sets: Mapping[str, Sequence[ArchitectItem]]) -> dict[str, list[str]]:
        done = self.done()
        return {
            name: [i.id for i in items if (name, i.id) not in done] for name, items in sets.items()
        }

    def _outcome(
        self, item: ArchitectItem, row: dict[str, Any], versions: dict[str, int]
    ) -> Result:
        if row.get("error") or row.get("attempts") is None:
            return Outcome(item, None, row.get("error") or "unknown", row.get("latency_ms", 0.0))
        spec_path = self.run_dir / SPECS / spec_filename(item.id)
        spec = None
        if row["ok"]:
            spec = SkillSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        result = ArchitectResult(
            ok=bool(row["ok"]),
            spec=spec,
            attempts=int(row["attempts"]),
            issues=tuple(Issue(**i) for i in row.get("issues", [])),
            prompt_versions=versions,
        )
        return Outcome(item, result, None, row.get("latency_ms", 0.0))


def _issue(issue: Issue) -> dict[str, str]:
    return {
        "path": issue.path,
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity,
    }


def _plain(value: Any) -> Any:
    """`value` as it reads back from JSON (tuples become lists), for comparing manifests."""
    return json.loads(json.dumps(value)) if value is not None else None


class _CallFileHandler(logging.Handler):
    """Writes the structured CallRecord a log_call record carries (`llm_call`), nothing else."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.INFO)
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        data = getattr(record, "llm_call", None)
        if not isinstance(data, dict):
            return
        try:
            lead = "\n" if _ends_mid_line(self.path) else ""
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(lead + json.dumps(data, ensure_ascii=False, default=str) + "\n")
                _sync(f)
        except OSError:
            self.handleError(record)


def _ends_mid_line(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) != b"\n"


def _sync(f: Any) -> None:
    f.flush()
    os.fsync(f.fileno())


__all__ = [
    "COMPARED",
    "MANIFEST",
    "PREDICTIONS",
    "ResumeError",
    "RunLog",
    "git_head",
    "spec_filename",
]
