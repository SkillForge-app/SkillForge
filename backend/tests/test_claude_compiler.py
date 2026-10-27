
import unittest

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler


class TestClaudeCompiler(unittest.TestCase):

    def test_generates_claude_md(self):
        compiler = ClaudeCompiler()

        agent_spec = {
            "name": "AgentForge",
            "description": "AI Assistant",
            "instructions": "Help users write Python code"
        }

        result = compiler.compile(agent_spec)

        self.assertIn("CLAUDE.md", result)
        self.assertIn("# AgentForge", result["CLAUDE.md"])
        self.assertIn("AI Assistant", result["CLAUDE.md"])
        self.assertIn(
            "Help users write Python code",
            result["CLAUDE.md"]
        )

    def test_empty_agent_spec(self):
        compiler = ClaudeCompiler()

        result = compiler.compile({})

        self.assertIn("CLAUDE.md", result)
        self.assertIn("Unnamed Agent", result["CLAUDE.md"])


if __name__ == "__main__":
    unittest.main()
