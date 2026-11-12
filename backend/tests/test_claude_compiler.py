import json
import unittest

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler
from backend.tests.skillspec_fixtures import load_valid_spec


class TestClaudeCompiler(unittest.TestCase):

    def setUp(self):
        self.compiler = ClaudeCompiler()
        self.valid_spec = load_valid_spec()

    def test_generates_claude_md(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn("CLAUDE.md", result)
        self.assertTrue(result["CLAUDE.md"].strip())

    def test_generates_claude_settings(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn(".claude/settings.json", result)

        settings = json.loads(result[".claude/settings.json"])
        self.assertIn("permissions", settings)

    def test_deterministic_output(self):
        first = self.compiler.compile(self.valid_spec)
        second = self.compiler.compile(self.valid_spec)

        self.assertEqual(first, second)

    def test_rejects_empty_spec(self):
        with self.assertRaises(ValueError):
            self.compiler.compile({})

    def test_rejects_invalid_spec(self):
        invalid = load_valid_spec()
        invalid["spec_version"] = "999"

        with self.assertRaises(ValueError):
            self.compiler.compile(invalid)


if __name__ == "__main__":
    unittest.main()

