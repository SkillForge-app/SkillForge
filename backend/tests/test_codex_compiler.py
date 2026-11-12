import unittest

from backend.app.compiler.compilers.codex_compiler import CodexCompiler
from tests.skillspec_fixtures import load_valid_spec


class TestCodexCompiler(unittest.TestCase):

    def setUp(self):
        self.compiler = CodexCompiler()
        self.valid_spec = load_valid_spec()

    def test_generates_agents_md(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn("AGENTS.md", result)
        self.assertTrue(result["AGENTS.md"].strip())

    def test_contains_skill_information(self):
        result = self.compiler.compile(self.valid_spec)

        title = self.valid_spec["skill"]["title"]
        self.assertIn(title, result["AGENTS.md"])

    def test_deterministic_output(self):
        first = self.compiler.compile(self.valid_spec)
        second = self.compiler.compile(self.valid_spec)

        self.assertEqual(first, second)

    def test_rejects_empty_spec(self):
        with self.assertRaises(ValueError):
            self.compiler.compile({})


if __name__ == "__main__":
    unittest.main()
