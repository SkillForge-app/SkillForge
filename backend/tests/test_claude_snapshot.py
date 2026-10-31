
from pathlib import Path

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler


def test_claude_md_snapshot():
    agent_spec = {
        "agent": {
            "name": "AgentForge",
            "description": "AI Assistant",
            "runtime": "python",
            "entrypoint": "main.py",
        },
        "project": {
            "name": "AgentForge",
        },
    }

    compiler = ClaudeCompiler()
    result = compiler.compile(agent_spec)

    snapshot_path = (
        Path(__file__).resolve().parent
        / "snapshots"
        / "claude_md.snapshot"
    )

    expected = snapshot_path.read_text(encoding="utf-8")

    assert result["CLAUDE.md"] == expected
