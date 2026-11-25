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
        "role": "final",
        "llm_backend": "fake",
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


def test_missing_markdown_fails_and_the_code_commit_may_precede_the_report(repo: Path) -> None:
    code = commit_files(repo, {DATA: b"x: 1\n"}, "the code that produced the report")
    commit_files(repo, {REPORT: b"{}"}, "report added later, without its .md")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": code}), repo)
    assert codes(result) == ["missing_markdown"]


def side_commit(repo: Path) -> str:
    """A commit on another branch: in the repository, but not an ancestor of HEAD."""
    main = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-b", "side")
    sha = commit_files(repo, {"side.txt": b"s"}, "side branch")
    git(repo, "checkout", "-q", main)
    return sha


def test_a_commit_that_is_not_an_ancestor_fails(repo: Path) -> None:
    commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    sha = side_commit(repo)
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": sha}), repo)
    assert codes(result) == ["not_an_ancestor"]


def test_a_commit_missing_from_history_fails(repo: Path) -> None:
    commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    result = check(registry({"id": "E1:demo", "report": REPORT, "recorded_at": "a" * 40}), repo)
    assert codes(result) == ["unknown_commit"]


def test_a_pending_entry_is_skipped_until_its_report_arrives(repo: Path) -> None:
    commit_files(repo, {DATA: b"x: 1\n"}, "start")
    other = side_commit(repo)
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
    # ... and a commit outside this branch's history is then reported, not skipped.
    result = check(registry({**pending, "recorded_at": other}), repo)
    assert codes(result) == ["not_an_ancestor"]


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
                "role": "final",
                "llm_backend": "fake",
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


def test_later_reports_of_the_same_series_are_removed_never_inputs(tmp_path: Path) -> None:
    from evaluation.reproduce.run import remove_later_reports

    names = [
        "sources-2026-10-26.json",
        "sources-2026-10-26.md",
        "sources-2026-10-26-2.json",
        "sources-2026-10-26-3.json",
        "sources-2026-10-26-3.md",
        "sources-2026-10-27.json",
        "sources-2026-10-25-4.json",
        "other-2026-10-30.json",
        "llm-verdicts-test-2026-11-02.json",
        "injection-test-2026-11-02.json",
    ]
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    keep = {"llm-verdicts-test-2026-11-02.json"}
    removed = remove_later_reports(tmp_path, "sources-2026-10-26-2", keep)
    assert removed == [
        "sources-2026-10-26-2.json",
        "sources-2026-10-26-3.json",
        "sources-2026-10-26-3.md",
        "sources-2026-10-27.json",
    ]
    left = {p.name for p in tmp_path.iterdir()}
    assert {"sources-2026-10-26.json", "sources-2026-10-25-4.json"} <= left
    assert {"llm-verdicts-test-2026-11-02.json", "other-2026-10-30.json"} <= left


# ------------------------------------------------------------------ the backend is per entry


EMBEDDING_CODE = (
    b"from core.llm import embed\n\n\nasync def vectors(t):\n    return await embed(t)\n"
)
NO_MODEL_CODE = b"def score(x):\n    return len(x)\n"


def test_a_fake_backend_for_code_that_embeds_is_rejected(repo: Path) -> None:
    sha = commit_files(
        repo,
        {
            "ai/evaluation/demo/evaluate.py": EMBEDDING_CODE,
            REPORT: b"{}",
            REPORT[:-5] + ".md": b"# d",
        },
        "an evaluation that embeds",
    )
    entry = {"id": "E1:demo", "report": REPORT, "recorded_at": sha}
    assert codes(check(registry(entry), repo)) == ["fake_backend_for_a_model"]
    assert check(registry({**entry, "llm_backend": "local-model"}), repo).issues == []


def test_a_fake_backend_is_fine_for_code_that_does_not_embed(repo: Path) -> None:
    sha = commit_files(
        repo,
        {
            "ai/evaluation/demo/evaluate.py": NO_MODEL_CODE,
            REPORT: b"{}",
            REPORT[:-5] + ".md": b"# d",
        },
        "an evaluation without a model",
    )
    entry = {"id": "E1:demo", "report": REPORT, "recorded_at": sha}
    assert check(registry(entry), repo).issues == []


def test_an_offline_entry_must_name_its_backend() -> None:
    with pytest.raises(ValidationError, match="llm_backend"):
        Entry.model_validate(
            {
                "id": "x",
                "experiment": "E1",
                "task": "t",
                "question": "q",
                "kind": "offline",
                "role": "final",
                "report": REPORT,
                "recorded_at": "c" * 40,
                "command": ["python", "-m", "evaluation.demo", "report"],
            }
        )


def test_the_environment_follows_the_entry_not_a_global_setting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from evaluation.reproduce import run

    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")  # never inherited
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setattr(run, "MODEL_CACHE", tmp_path)
    local = run.clean_env(needs_model=True)
    assert "SKILLFORGE_LLM_BACKEND" not in local and local["SKILLFORGE_MODEL_CACHE"] == str(
        tmp_path
    )
    assert "OPENROUTER_API_KEY" not in local and local["HF_HUB_OFFLINE"] == "1"
    fake = run.clean_env(needs_model=False)
    assert fake["SKILLFORGE_LLM_BACKEND"] == "fake" and "SKILLFORGE_MODEL_CACHE" not in fake
    monkeypatch.setattr(run, "MODEL_CACHE", tmp_path / "missing")
    with pytest.raises(RuntimeError, match="model cache not found"):
        run.clean_env(needs_model=True)


def test_the_registry_runs_the_model_experiments_on_the_local_model() -> None:
    reg = load_registry()
    by_task = {e.id: e.llm_backend for e in reg.experiments if e.kind == "offline"}
    assert all(backend is not None for backend in by_task.values())
    for entry_id, backend in by_task.items():
        if entry_id.startswith(("E3:", "E4:", "E11:")):  # retrieval, gap, support calibration
            assert backend == "local-model", entry_id


def test_the_done_when_counts_final_entries_only(repo: Path) -> None:
    sha = commit_files(repo, {REPORT: b"{}", REPORT[:-5] + ".md": b"# d"}, "report")
    entry = {"id": "E1:demo", "report": REPORT, "recorded_at": sha}
    ok = check(registry({**entry, "reproduces": True}), repo)
    assert ok.issues == [] and ok.final_reproduces == ["E1:demo"]
    not_run = check(registry(entry), repo)
    assert not_run.issues == [] and not_run.final_not_run == ["E1:demo"]
    failing = check(registry({**entry, "reproduces": False}), repo)
    assert codes(failing) == ["final_not_reproducing"]
    for role in ("superseded", "invalid"):  # never count toward the done-when
        other = check(registry({**entry, "reproduces": False, "role": role}), repo)
        assert other.issues == [] and other.final_reproduces == other.final_not_run == []
