from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler
from backend.tests.skillspec_fixtures import load_valid_spec


def test_claude_md_snapshot():
    result = ClaudeCompiler().compile(load_valid_spec())

    assert "CLAUDE.md" in result
    assert result["CLAUDE.md"].startswith("# ")

