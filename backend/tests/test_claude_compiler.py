
import unittest

from pydantic import ValidationError

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler


class TestClaudeCompiler(unittest.TestCase):

    def setUp(self):
        self.compiler = ClaudeCompiler()
        self.valid_spec = {
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

    def test_generates_claude_md(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn("CLAUDE.md", result)
        self.assertIn("# AgentForge", result["CLAUDE.md"])
        self.assertIn("AI Assistant", result["CLAUDE.md"])
        self.assertIn("## Runtime", result["CLAUDE.md"])
        self.assertIn("python", result["CLAUDE.md"])
        self.assertIn("main.py", result["CLAUDE.md"])

    def test_deterministic_output(self):
        first = self.compiler.compile(self.valid_spec)
        second = self.compiler.compile(self.valid_spec)

        self.assertEqual(first, second)

    def test_rejects_empty_spec(self):
        with self.assertRaises(ValidationError):
            self.compiler.compile({})

    def test_rejects_invalid_runtime(self):
        self.valid_spec["agent"]["runtime"] = "invalid"

        with self.assertRaises(ValidationError):
            self.compiler.compile(self.valid_spec)

    def test_rejects_undefined_tool(self):
        self.valid_spec["agent"]["tools"] = ["unknown_tool"]

        with self.assertRaisesRegex(ValueError, "unknown_tool"):
            self.compiler.compile(self.valid_spec)

    def test_rejects_conflicting_constraints(self):
        self.valid_spec["agent"]["constraints"] = {
            "rules": ["allow:files", "deny:files"]
        }

        with self.assertRaisesRegex(ValueError, "Conflicting rules"):
            self.compiler.compile(self.valid_spec)


if __name__ == "__main__":
    unittest.main()
