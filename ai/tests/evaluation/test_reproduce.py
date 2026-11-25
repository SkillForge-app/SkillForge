"""AI-25: `reproduce check` against small throwaway git repositories, plus the real registry."""

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from evaluation.reproduce.__main__ import main
from evaluation.reproduce.check import check, repo_root
from evaluation.reproduce.registry import AI_DIR, Entry, Registry, load_registry

REPORT = "ai/evaluation/demo/reports/demo-2026-11-25.json"
DATA = "ai/evaluation/demo/labels.yaml"


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def commit_files(repo: Path, files: dict[str, bytes], message: str) -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def registry(*entries: dict[str, Any], data_files: list[dict[str, str]] | None = None) -> Registry:
    base = {
        "experiment": "E1",
        "task": "AI-00",
        "question": "Does the demo work?",
        "kind": "offline",
        "command": ["python", "-m", "evaluation.demo", "report"],
    }
    return Registry.model_validate(
        {
            "version": 1,
            "ignore": ["date"],
            "data_files": data_files or [],
            "experiments": [{**base, **e} for e in entries],
        }
    )


def codes(result: Any) -> list[str]:
    return [i.code for i in result.issues]


def test_a_registered_report_at_its_commit_passes(repo: Path) -> None:
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# demo"}, "report")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": sha}), repo)
    assert result.issues == [] and result.checked == ["E1:demo"]


def test_an_unregistered_report_fails(repo: Path) -> None:
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    other = "ai/evaluation/demo/reports/other.json"
    commit_files(repo, {other: b"{}"}, "another report, no entry")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": sha}), repo)
    assert codes(result) == ["unregistered_report"]


def test_a_listed_data_file_is_not_a_report(repo: Path) -> None:
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    verdicts = "ai/evaluation/demo/reports/verdicts.json"
    commit_files(repo, {verdicts: b"{}"}, "saved verdicts")
    reg = registry(
        {"id": "E1:demo", "report": REPORT, "recorded_at": sha},
        data_files=[{"path": verdicts, "why": "an input of E1"}],
    )
    assert check(reg, repo).issues == []


def test_missing_markdown_and_wrong_commit_fail(repo: Path) -> None:
    first = commit_files(repo, {DATA: b"x: 1\n"}, "data only")
    commit_files(repo, {REPORT: b"{}"}, "report without its .md")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": first}), repo)
    assert codes(result) == ["missing_markdown", "not_at_commit"]


def test_a_commit_missing_from_history_fails(repo: Path) -> None:
    commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": "a" * 40}), repo)
    assert codes(result) == ["unknown_commit"]


def test_a_pending_entry_is_skipped_until_its_report_arrives(repo: Path) -> None:
    commit_files(repo, {DATA: b"x: 1\n"}, "start")
    other = git(repo, "rev-parse", "HEAD")
    pending = {
        "id": "E1:demo",
        "report": REPORT,
        "recorded_at": "b" * 40,
        "status": "pending-merge",
    }
    result = check(registry(pending), repo)
    assert result.issues == [] and result.pending_skipped == ["E1:demo"]

    # The other branch merges: the report and its commit arrive, and the entry is checked fully.
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "merged report")
    result = check(registry({**pending, "recorded_at": sha}), repo)
    assert result.issues == [] and result.checked == ["E1:demo"]
    # ... and a wrong commit is then reported, not skipped.
    result = check(registry({**pending, "recorded_at": other}), repo)
    assert codes(result) == ["not_at_commit"]


def test_inputs_are_verified_at_recorded_at_including_legacy_crlf(repo: Path) -> None:
    content = b"a: 1\nb: 2\n"
    sha = commit_files(
        repo, {DATA: content, REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report and data"
    )
    lf = hashlib.sha256(content).hexdigest()
    crlf = hashlib.sha256(content.replace(b"\n", b"\r\n")).hexdigest()
    entry = {"id": "E1:demo", "report": REPORT, "recorded_at": sha}
    ok = check(registry({**entry, "inputs": [{"path": DATA, "sha256": lf}]}), repo)
    legacy = check(
        registry({**entry, "inputs": [{"path": DATA, "sha256": crlf, "hash": "legacy"}]}), repo
    )
    assert ok.issues == [] and legacy.issues == []
    # A new-scheme entry does not accept the CRLF form, and a changed file fails.
    strict = check(registry({**entry, "inputs": [{"path": DATA, "sha256": crlf}]}), repo)
    assert codes(strict) == ["changed_input"]
    commit_files(repo, {DATA: b"a: 1\nb: 3\n"}, "data changed later")  # recorded_at still holds
    assert check(registry({**entry, "inputs": [{"path": DATA, "sha256": lf}]}), repo).issues == []


def test_an_offline_entry_needs_a_command(repo: Path) -> None:
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    result = check(
        registry({"id": "E1:demo", "report": REPORT, "recorded_at": sha, "command": None}), repo
    )
    assert codes(result) == ["no_command"]


def test_an_extra_ignored_field_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        Entry.model_validate(
            {
                "id": "x",
                "experiment": "E1",
                "task": "t",
                "question": "q",
                "kind": "offline",
                "report": REPORT,
                "recorded_at": "c" * 40,
                "ignore_extra": [{"field": "score"}],
            }
        )


def test_the_real_registry_covers_every_committed_report() -> None:
    reg = load_registry()
    assert "human_review" in reg.ignore and "date" in reg.ignore
    result = check(reg, repo_root(AI_DIR), history=False)  # CI checks history separately
    assert result.issues == []
    assert all(e.kind != "live" or e.command for e in reg.experiments)


def test_cli_check_and_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    assert "Live experiments" in capsys.readouterr().out
