"""`reproduce check`: the registry and the committed reports agree (AI-25). Fast, no model.

- every report under ai/evaluation/<area>/reports/*.json is registered (or listed as a data file);
- every active entry's report exists, with its Markdown twin, and its `recorded_at` commit is in
  this branch's history (an ancestor of HEAD);
- a pending-merge entry is skipped while its report is absent and checked fully once present;
- every recorded input still has its recorded hash at `recorded_at` (git history is needed);
- a live/rescore entry's tracked run exists, has its recorded hash and line count, only
  allowlisted fields and unique ids, and every id is well-formed and (with history) one of the
  ids in the label files at `recorded_at`; a rescore's source hash equals its report's.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.spec import Issue
from evaluation.common import match_recorded_hash, text_sha256
from evaluation.reproduce.registry import Entry, Registry
from evaluation.reproduce.rescore import known_ids
from evaluation.reproduce.strict import DuplicateKeyError, loads_unique
from evaluation.reproduce.track import bad_fields, parse_lines

REPORT_GLOB = "ai/evaluation/*/reports/*.json"
# Code that loads the embedding model: under a fake backend it would get random vectors.
EMBEDS = re.compile(rb"core\.llm\.local_embed|embed\(")


@dataclass
class CheckResult:
    issues: list[Issue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    pending_skipped: list[str] = field(default_factory=list)
    # The done-when, over checked FINAL entries only (superseded and invalid never count).
    final_reproduces: list[str] = field(default_factory=list)
    final_not_run: list[str] = field(default_factory=list)


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
        if entry.role != "final":
            continue
        if entry.reproduces is True:
            result.final_reproduces.append(entry.id)
        elif entry.reproduces is None:
            result.final_not_run.append(entry.id)
        else:
            issues.append(
                Issue(entry.id, "final_not_reproducing", "a final entry must reproduce (done-when)")
            )
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
    if entry.report.endswith(".json"):
        try:
            loads_unique((repo / entry.report).read_text(encoding="utf-8"))
        except DuplicateKeyError as exc:
            return [*issues, Issue(where, "report_duplicate_key", str(exc))]
    if entry.kind == "offline" and not entry.command:
        issues.append(Issue(where, "no_command", "an offline entry needs its command"))
    known = None  # without history: the id format only
    if history and entry.tracked_run is not None:
        if _git_ok(repo, "cat-file", "-e", f"{entry.recorded_at}^{{commit}}"):
            known = known_ids(repo, entry.recorded_at)
        else:
            known = frozenset()  # unknown_commit is reported below; no id can pass
    issues += _check_tracked_run(entry, repo, known)
    if not history:
        return issues
    if not _git_ok(repo, "cat-file", "-e", f"{entry.recorded_at}^{{commit}}"):
        issues.append(
            Issue(
                where, "unknown_commit", f"{entry.recorded_at[:12]} is not in this clone's history"
            )
        )
        return issues
    if not _git_ok(repo, "merge-base", "--is-ancestor", entry.recorded_at, "HEAD"):
        issues.append(
            Issue(where, "not_an_ancestor", f"{entry.recorded_at[:12]} is not an ancestor of HEAD")
        )
    if entry.kind == "offline" and entry.llm_backend == "fake" and _module_embeds(entry, repo):
        issues.append(
            Issue(
                where,
                "fake_backend_for_a_model",
                "its code embeds text: set llm_backend: local-model (a fake backend would give "
                "random vectors and a meaningless report)",
            )
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


def _check_tracked_run(entry: Entry, repo: Path, known: frozenset[str] | None) -> list[Issue]:
    where = entry.id
    run = entry.tracked_run
    if entry.kind == "offline":
        return []
    if run is None:
        if entry.role == "final":
            return [
                Issue(where, "no_tracked_run", "a final live/rescore entry needs its tracked run")
            ]
        return []
    path = repo / run.path
    if not path.is_file():
        return [Issue(where, "missing_tracked_run", f"{run.path} does not exist")]
    issues = []
    if text_sha256(path) != run.sha256:
        issues.append(Issue(where, "changed_tracked_run", f"{run.path} no longer has its hash"))
    lines, problems = parse_lines(path.read_text(encoding="utf-8"))
    issues += [Issue(where, "tracked_run_json", p) for p in problems[:5]]
    if len(lines) + len(problems) != run.lines:
        issues.append(
            Issue(
                where,
                "tracked_run_lines",
                f"{len(lines) + len(problems)} lines, recorded {run.lines}",
            )
        )
    issues += [Issue(where, "tracked_run_field", p) for p in bad_fields(lines, known)[:5]]
    ids = [line.get("id") for line in lines]
    if len(set(ids)) != len(ids):
        issues.append(Issue(where, "tracked_run_ids", "duplicate ids in the tracked run"))
    report = loads_unique((repo / entry.report).read_text(encoding="utf-8"))
    recorded = (report.get("rescored_from") or {}).get("predictions_sha256")
    if recorded is not None and recorded != run.source_sha256:
        issues.append(
            Issue(where, "source_hash", "the tracked run's source is not the run the report used")
        )
    n = sum(s.get("n", 0) for s in (report.get("sets") or {}).values())
    total = len(lines) + len(problems)
    if n and n != total:
        issues.append(Issue(where, "tracked_run_lines", f"{total} lines for a report of {n}"))
    return issues


def _module_embeds(entry: Entry, repo: Path) -> bool:
    """Does the evaluation package the command runs (`python -m evaluation.X`) embed text, in
    its code at recorded_at? Reports and data files are not looked at."""
    if not entry.command or len(entry.command) < 3 or entry.command[1] != "-m":
        return False
    package = "ai/" + entry.command[2].split(".")[0] + "/" + entry.command[2].split(".")[1]
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", entry.recorded_at, package + "/"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout.split()
    for path in listing:
        if path.endswith(".py") and EMBEDS.search(git_show(repo, entry.recorded_at, path) or b""):
            return True
    return False


__all__ = ["REPORT_GLOB", "CheckResult", "check", "git_show", "repo_root"]
