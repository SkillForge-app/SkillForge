
import unittest

from backend.app.compiler.compilers.codex_compiler import CodexCompiler


class TestCodexCompiler(unittest.TestCase):

    def test_generates_agents_md(self):
        compiler = CodexCompiler()

        agent_spec = {
            "name": "AgentForge",
            "description": "AI Assistant",
            "instructions": "Write clean Python code"
        }

        result = compiler.compile(agent_spec)

        self.assertIn("AGENTS.md", result)
        self.assertIn("# AgentForge", result["AGENTS.md"])
        self.assertIn("AI Assistant", result["AGENTS.md"])
        self.assertIn(
            "Write clean Python code",
            result["AGENTS.md"]
        )

    def test_empty_agent_spec(self):
        compiler = CodexCompiler()

        result = compiler.compile({})

        self.assertIn("AGENTS.md", result)
        self.assertIn("Unnamed Agent", result["AGENTS.md"])


if __name__ == "__main__":
    unittest.main()
