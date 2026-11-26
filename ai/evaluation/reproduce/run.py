"""`reproduce run`: re-run offline experiments at their recorded commit and compare (AI-25).

For each offline entry:
1. `git archive <recorded_at> ai` (core.autocrlf off, so the tree is the same on every OS) is
   extracted into a new folder under %TEMP%/skillforge-reproduce/ (one per commit). Nothing
   is written inside the repository; only folders this run created are deleted.
2. A venv built from that commit's uv.lock (`uv sync --locked --all-extras
   --no-install-project`), cached by the lock's hash in ai/.data/reproduce/venvs/ (ignored).
3. The recorded command runs in the extracted tree, with no API keys, fake LLM and search
   backends, HF offline, and the local model cache for entries that need a model.
   Before it runs, the target report and every LATER report of the same series (same
   name before the date; later date, or same date with a higher -N) are removed from the
   extracted reports folder, so the folder is as it was when the report was written (a tool
   that reads earlier reports, e.g. sources' history, then sees what it saw). Only reports of
   that series are removed, never inputs or data files.
4. The report it writes is compared EXACTLY with the committed one, after dropping only the
   registry's global `ignore` fields and the entry's `ignore_extra` (each with a reason).
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.common import text_sha256
from evaluation.reproduce.check import git_show
from evaluation.reproduce.registry import AI_DIR, TEMP_ROOT, Entry, Registry
from evaluation.reproduce.rescore import rescore
from evaluation.reproduce.strict import loads_unique

VENVS = AI_DIR / ".data" / "reproduce" / "venvs"
MODEL_CACHE = Path(os.environ.get("SKILLFORGE_MODEL_CACHE") or AI_DIR / ".data" / "models")
SECRET_ENV = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "DSN")


@dataclass
class Outcome:
    entry: str
    status: str  # "match", "differs", "skipped", "error"
    detail: str = ""
    diffs: list[str] = field(default_factory=list)
    seconds: float = 0.0
    # offline: the sha256-lf of the committed report this run compared (record it in the
    # registry as report_sha256 with `reproduces`)
    report_sha256: str = ""


def strip(value: Any, ignore: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: strip(v, ignore) for k, v in value.items() if k not in ignore}
    if isinstance(value, list):
        return [strip(v, ignore) for v in value]
    return value


def differences(old: Any, new: Any, path: str = "", limit: int = 12) -> list[str]:
    out: list[str] = []

    def walk(a: Any, b: Any, at: str) -> None:
        if len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a:
                    out.append(f"{at}/{key}: only in the new report")
                elif key not in b:
                    out.append(f"{at}/{key}: only in the committed report")
                else:
                    walk(a[key], b[key], f"{at}/{key}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append(f"{at}: {len(a)} items committed, {len(b)} new")
            for i, (x, y) in enumerate(zip(a, b, strict=False)):
                walk(x, y, f"{at}/{i}")
        elif a != b:
            out.append(f"{at}: committed {json.dumps(a)[:80]} | new {json.dumps(b)[:80]}")

    walk(old, new, path)
    return out


def _uv() -> str:
    found = os.environ.get("UV") or shutil.which("uv")
    if found:
        return found
    local = Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    if local.exists():
        return str(local)
    raise RuntimeError("uv is needed to build the recorded environment")


def extract(repo: Path, commit: str, into: Path) -> Path:
    tar = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", commit, "ai"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        archive.extractall(into, filter="data")
    return into / "ai"


def venv_for(tree: Path) -> tuple[Path, str]:
    lock_hash = text_sha256(tree / "uv.lock")[:16]
    venv = VENVS / lock_hash
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(venv))
    subprocess.run(
        [_uv(), "sync", "--locked", "--all-extras", "--no-install-project", "--quiet"],
        cwd=tree,
        env=env,
        check=True,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return python, lock_hash


def clean_env(needs_model: bool) -> dict[str, str]:
    """The environment for one entry: no secrets, offline hub, and the entry's own backend
    (fake, or the real gateway with the local model). Nothing is inherited for the backend."""
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in SECRET_ENV)}
    env.pop("SKILLFORGE_LLM_BACKEND", None)
    env.update(
        SKILLFORGE_SEARCH="fake",
        HF_HUB_OFFLINE="1",
        PYTHONUTF8="1",
        PYTHONHASHSEED="0",
    )
    env.pop("VIRTUAL_ENV", None)
    if not needs_model:
        env["SKILLFORGE_LLM_BACKEND"] = "fake"
    else:
        # The real gateway with the local model (no key, no network: hub offline, keys removed).
        if not MODEL_CACHE.is_dir():
            raise RuntimeError(f"model cache not found: {MODEL_CACHE} (set SKILLFORGE_MODEL_CACHE)")
        env["SKILLFORGE_MODEL_CACHE"] = str(MODEL_CACHE)
    return env


_SERIES = re.compile(r"^(?P<series>.+?)-(?P<date>\d{4}-\d{2}-\d{2})(?:-(?P<n>\d+))?(?P<rest>.*)$")


def series_key(stem: str) -> tuple[tuple[str, str], tuple[str, int]] | None:
    """((series, suffix), (date, n)) for a report name like `sources-2026-10-26-3`."""
    m = _SERIES.match(stem)
    if m is None:
        return None
    return (m["series"], m["rest"]), (m["date"], int(m["n"] or 1))


def remove_later_reports(reports_dir: Path, target_stem: str, keep: set[str]) -> list[str]:
    """Delete the target report and later ones of its series (.json and .md) from the
    extracted tree. Files in `keep` (registered data files) are never removed."""
    target = series_key(target_stem)
    if target is None:
        return []
    removed = []
    for path in sorted(reports_dir.glob("*")):
        if not path.is_file() or path.suffix not in (".json", ".md") or path.name in keep:
            continue
        key = series_key(path.stem)
        if key is not None and key[0] == target[0] and key[1] >= target[1]:
            path.unlink()
            removed.append(path.name)
    return removed


def _new_json(reports_dir: Path, before: set[Path]) -> Path | None:
    made = sorted(p for p in reports_dir.glob("*.json") if p not in before)
    return made[-1] if len(made) == 1 else None


def run_entry(entry: Entry, registry: Registry, repo: Path, tree: Path, python: Path) -> Outcome:
    start = time.perf_counter()
    if not entry.command:
        return Outcome(entry.id, "skipped", "no command")
    committed = (repo / entry.report).read_bytes()
    pinned = text_sha256(committed)
    reports_dir = tree / Path(entry.report).relative_to("ai").parent
    reports_dir.mkdir(parents=True, exist_ok=True)
    if "/reports/" in entry.report:
        keep = {Path(d.path).name for d in registry.data_files}
        remove_later_reports(reports_dir, Path(entry.report).stem, keep)
    before = set(reports_dir.glob("*.json"))
    argv = [str(python), *entry.command[1:]] if entry.command[0] == "python" else entry.command
    proc = subprocess.run(
        argv,
        cwd=tree,
        env=clean_env(entry.needs_model),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    seconds = time.perf_counter() - start
    if entry.report.endswith("manifest.json"):
        ok = proc.returncode == 0
        detail = proc.stdout.strip()[-200:]
        return Outcome(entry.id, "match" if ok else "differs", detail, [], seconds, pinned)
    new = _new_json(reports_dir, before)
    if new is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        return Outcome(
            entry.id, "error", f"exit {proc.returncode}; no new report: {tail}", [], seconds
        )
    ignore = set(registry.ignore) | {x.field for x in entry.ignore_extra}
    old = strip(loads_unique(committed), ignore)
    fresh = strip(loads_unique(new.read_text(encoding="utf-8")), ignore)
    diffs = differences(old, fresh)
    return Outcome(entry.id, "differs" if diffs else "match", "", diffs, seconds, pinned)


def reproduce(
    registry: Registry,
    repo: Path,
    *,
    only: Sequence[str] = (),
    no_model: bool = False,
) -> Iterator[tuple[Outcome, str | None]]:
    """Yield (outcome, lock hash) per entry: an offline one re-run in its own fresh extracted
    tree; a live or rescore one re-scored from its tracked run (no model call)."""
    picked = [
        e
        for e in registry.experiments
        if e.status == "active" and (not only or e.id in only or e.experiment in only)
    ]
    for entry in picked:
        if entry.kind != "offline" and entry.tracked_run is not None:
            start = time.perf_counter()
            diffs, left = rescore(entry, registry, repo)
            note = f"not recomputable (listed): {', '.join(left)}" if left else ""
            status = "differs" if diffs else "match"
            yield Outcome(entry.id, status, note, diffs, time.perf_counter() - start), None
    chosen = [e for e in picked if e.kind == "offline"]
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    for entry in chosen:
        if entry.needs_model and no_model:
            yield Outcome(entry.id, "skipped", "needs the local model (--no-model)"), None
            continue
        made = Path(tempfile.mkdtemp(prefix=f"{entry.recorded_at[:10]}-", dir=TEMP_ROOT))
        try:
            tree = extract(repo, entry.recorded_at, made)
            python, lock = venv_for(tree)
            yield run_entry(entry, registry, repo, tree, python), lock
        finally:
            shutil.rmtree(made, ignore_errors=True)  # only the folder this run created


__all__ = ["TEMP_ROOT", "Outcome", "differences", "git_show", "reproduce", "strip"]
