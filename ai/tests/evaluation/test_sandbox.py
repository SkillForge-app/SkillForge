"""AI-25: code from an old commit never sees a secret and can't make an HTTP call.

A throwaway repo holds a fake "old commit" whose code reports which secret-named variables it can
see and whether an HTTP request to a live local server got through. It runs through both paths
that execute old-commit code: `reproduce run` (run_entry) and the .md check (twins.render_at)."""

import http.server
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from evaluation.reproduce import run, twins
from evaluation.reproduce.registry import Registry
from evaluation.reproduce.sandbox import UnsafeTree

SECRETS = {
    "OPENROUTER_API_KEY": "sk-or-test",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "MY_SERVICE_TOKEN": "t",
    "APP_SECRET": "s",
    "DATABASE_URL": "postgresql://u:p@db/x",
    "SOME_UNLISTED_SETTING": "x",  # not secret-looking: dropped all the same (an allowlist)
}
# What the old commit's code does: no imports from the repo, so it runs at any commit.
PROBE = (
    "import json, os, urllib.request\n\nSECRETS = "
    + repr(sorted(SECRETS))
    + """


def probe(url):
    out = {"visible": sorted(n for n in SECRETS if n in os.environ)}
    try:
        urllib.request.urlopen(url, timeout=5).read()
        out["urllib"] = "reached"
    except Exception:
        out["urllib"] = "blocked"
    try:
        import httpx

        httpx.get(url, timeout=5)
        out["httpx"] = "reached"
    except Exception:
        out["httpx"] = "blocked"
    return out
"""
)
SAFE = {"visible": [], "urllib": "blocked", "httpx": "blocked"}

DEMO_MAIN = (
    PROBE
    + """
import sys
from pathlib import Path

report = Path(__file__).parent / "reports" / "demo-2026-11-26.json"
report.write_text(json.dumps(probe(sys.argv[1]), sort_keys=True), encoding="utf-8")
"""
)
ANALYZER_EVALUATE = (
    PROBE
    + """
from dataclasses import dataclass


@dataclass
class EvalReport:
    url: str


def render_markdown(report):
    return json.dumps(probe(report.url), sort_keys=True)
"""
)
REPORT = "ai/evaluation/demo/reports/demo-2026-11-26.json"


@pytest.fixture
def server() -> Iterator[str]:
    """A live HTTP server on loopback: reachable unless the code is sandboxed."""

    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (the handler's API)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def old_commit(repo: Path, files: dict[str, str]) -> str:
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "core.autocrlf", "false")
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8", newline="\n")
        git(repo, "add", "-f", rel)
    git(repo, "commit", "-q", "-m", "an old commit")
    return git(repo, "rev-parse", "HEAD")


def demo(sha: str, url: str) -> dict[str, object]:
    return {
        "id": "E1:demo",
        "experiment": "E1",
        "task": "AI-00",
        "question": "Is old code sandboxed?",
        "kind": "offline",
        "role": "final",
        "llm_backend": "fake",
        "report": REPORT,
        "recorded_at": sha,
        "command": ["python", "-m", "evaluation.demo", url],
    }


def test_the_probe_sees_secrets_and_the_server_without_the_sandbox(
    server: str, secrets: None, tmp_path: Path
) -> None:
    """The control: the same code, run plainly, sees every secret and reaches the server."""
    script = tmp_path / "probe.py"
    script.write_text(PROBE + "\nimport sys\nprint(json.dumps(probe(sys.argv[1])))\n", "utf-8")
    out = subprocess.run(
        [sys.executable, str(script), server], capture_output=True, text=True, env=dict(os.environ)
    )
    assert json.loads(out.stdout) == {
        "visible": sorted(SECRETS),
        "urllib": "reached",
        "httpx": "reached",
    }


def test_run_executes_old_code_with_no_secret_and_no_http(
    server: str, secrets: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = old_commit(
        repo,
        {
            "ai/evaluation/__init__.py": "",
            "ai/evaluation/demo/__init__.py": "",
            "ai/evaluation/demo/__main__.py": DEMO_MAIN,
            REPORT: json.dumps(SAFE, sort_keys=True),  # what a sandboxed run must write
            REPORT[:-5] + ".md": "# demo",
        },
    )
    monkeypatch.setattr(run, "TEMP_ROOT", tmp_path / "skillforge-reproduce")
    tree = run.extract(repo, sha, tmp_path / "skillforge-reproduce" / "t")
    reg = Registry.model_validate({"version": 1, "ignore": [], "experiments": [demo(sha, server)]})
    outcome = run.run_entry(reg.experiments[0], reg, repo, tree, Path(sys.executable))
    written = json.loads((tree / "evaluation/demo/reports/demo-2026-11-26.json").read_text())
    assert written == SAFE, written
    assert outcome.status == "match"


def test_render_at_executes_old_code_with_no_secret_and_no_http(
    server: str, secrets: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = old_commit(
        repo,
        {
            "ai/evaluation/__init__.py": "",
            "ai/evaluation/analyzer/__init__.py": "",
            "ai/evaluation/analyzer/evaluate.py": ANALYZER_EVALUATE,
        },
    )
    monkeypatch.setattr(twins, "TEMP_ROOT", tmp_path / "skillforge-reproduce")
    rendered = twins.render_at(repo, sha, "analyzer", json.dumps({"url": server, "run": "x"}))
    assert rendered is not None and json.loads(rendered) == SAFE, rendered


def test_an_extracted_tree_with_an_env_file_is_never_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = old_commit(
        repo,
        {
            "ai/.env": "OPENROUTER_API_KEY=sk-or-committed\n",
            "ai/evaluation/__init__.py": "",
            "ai/evaluation/analyzer/__init__.py": "",
            "ai/evaluation/analyzer/evaluate.py": ANALYZER_EVALUATE,
        },
    )
    monkeypatch.setattr(twins, "TEMP_ROOT", tmp_path / "skillforge-reproduce")
    with pytest.raises(UnsafeTree):
        twins.render_at(repo, sha, "analyzer", json.dumps({"url": "http://x/", "run": "x"}))
    monkeypatch.setattr(run, "TEMP_ROOT", tmp_path / "skillforge-reproduce")
    tree = run.extract(repo, sha, tmp_path / "skillforge-reproduce" / "t")
    reg = Registry.model_validate({"version": 1, "ignore": [], "experiments": [demo(sha, "x")]})
    with pytest.raises(UnsafeTree):
        run.run_entry(reg.experiments[0], reg, repo, tree, Path(sys.executable))
