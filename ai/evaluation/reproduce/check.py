"""`reproduce check`: the registry and the committed reports agree (AI-25). Fast, no model.

- every report under ai/evaluation/<area>/reports/*.json is registered (or listed as a data file);
- every active entry's report exists, with its Markdown twin, and was added by `recorded_at`;
- a pending-merge entry is skipped while its report is absent and checked fully once present;
- every recorded input still has its recorded hash at `recorded_at` (git history is needed).
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.spec import Issue
from evaluation.common import match_recorded_hash
from evaluation.reproduce.registry import Entry, Registry

REPORT_GLOB = "ai/evaluation/*/reports/*.json"


@dataclass
class CheckResult:
    issues: list[Issue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    pending_skipped: list[str] = field(default_factory=list)


def repo_root(start: Path) -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True).returncode == 0


def git_show(repo: Path, commit: str, path: str) -> bytes | None:
    out = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True)
    return out.stdout if out.returncode == 0 else None


def check(registry: Registry, repo: Path, *, history: bool = True) -> CheckResult:
    """With history=False only the files are checked (no git history needed)."""
    result = CheckResult()
    issues = result.issues
    ids = [e.id for e in registry.experiments]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(Issue(dup, "duplicate_id", "two entries share this id"))
    reports = [e.report for e in registry.experiments]
    for dup in sorted({r for r in reports if reports.count(r) > 1}):
        issues.append(Issue(dup, "duplicate_report", "two entries name this report"))

    known = set(reports) | {d.path for d in registry.data_files}
    for found in sorted(p.relative_to(repo).as_posix() for p in repo.glob(REPORT_GLOB)):
        if found not in known:
            issues.append(
                Issue(
                    found, "unregistered_report", "add an entry to ai/evaluation/experiments.yaml"
                )
            )
    for data_file in registry.data_files:
        if not (repo / data_file.path).is_file():
            issues.append(Issue(data_file.path, "missing_file", "listed data file is missing"))

    for entry in registry.experiments:
        present = (repo / entry.report).is_file()
        if entry.status == "pending-merge" and not present:
            result.pending_skipped.append(entry.id)
            continue
        issues += _check_entry(entry, repo, present, history=history)
        result.checked.append(entry.id)
    return result


def _check_entry(entry: Entry, repo: Path, present: bool, *, history: bool) -> list[Issue]:
    issues = []
    where = entry.id
    if not present:
        return [Issue(where, "missing_report", f"{entry.report} does not exist")]
    if entry.report.endswith(".json") and "/reports/" in entry.report:
        twin = entry.report[: -len(".json")] + ".md"
        if not (repo / twin).is_file():
            issues.append(Issue(where, "missing_markdown", f"{twin} does not exist"))
    if entry.kind == "offline" and not entry.command:
        issues.append(Issue(where, "no_command", "an offline entry needs its command"))
    if not history:
        return issues
    if not _git_ok(repo, "cat-file", "-e", f"{entry.recorded_at}^{{commit}}"):
        issues.append(
            Issue(
                where, "unknown_commit", f"{entry.recorded_at[:12]} is not in this clone's history"
            )
        )
        return issues
    if git_show(repo, entry.recorded_at, entry.report) is None:
        issues.append(
            Issue(where, "not_at_commit", f"the report is not in {entry.recorded_at[:12]}")
        )
    for item in entry.inputs:
        content = git_show(repo, entry.recorded_at, item.path)
        if content is None:
            issues.append(
                Issue(where, "missing_input", f"{item.path} not in {entry.recorded_at[:12]}")
            )
        elif match_recorded_hash(item.sha256, content, item.hash) is None:
            issues.append(Issue(where, "changed_input", f"{item.path} no longer has its hash"))
    return issues


__all__ = ["REPORT_GLOB", "CheckResult", "check", "git_show", "repo_root"]
