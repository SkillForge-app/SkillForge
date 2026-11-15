import copy
import tomllib
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

    def test_generates_codex_config(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn(".codex/config.toml", result)
        config = tomllib.loads(result[".codex/config.toml"])

        self.assertEqual(config["approval_policy"], "on-request")
        self.assertEqual(config["sandbox_mode"], "read-only")
        self.assertEqual(config["web_search"], "cached")

    def test_contains_skill_information(self):
        result = self.compiler.compile(self.valid_spec)

        title = self.valid_spec["skill"]["title"]
        self.assertIn(title, result["AGENTS.md"])

    def test_deterministic_output(self):
        first = self.compiler.compile(self.valid_spec)
        second = self.compiler.compile(self.valid_spec)

        self.assertEqual(first, second)

    def test_required_filesystem_write_enables_workspace_write(self):
        spec = copy.deepcopy(self.valid_spec)
        spec["tools"]["required"] = ["filesystem_write"]

        result = self.compiler.compile(spec)
        config = tomllib.loads(result[".codex/config.toml"])

        self.assertEqual(config["sandbox_mode"], "workspace-write")

    def test_required_web_search_enables_live_search(self):
        spec = copy.deepcopy(self.valid_spec)
        spec["tools"]["required"] = ["web_search"]
        spec["tools"]["optional"] = []

        result = self.compiler.compile(spec)
        config = tomllib.loads(result[".codex/config.toml"])

        self.assertEqual(config["web_search"], "live")

    def test_disables_web_search_when_not_declared(self):
        spec = copy.deepcopy(self.valid_spec)
        spec["tools"]["required"] = []
        spec["tools"]["optional"] = []

        result = self.compiler.compile(spec)
        config = tomllib.loads(result[".codex/config.toml"])

        self.assertEqual(config["web_search"], "disabled")

    def test_rejects_empty_spec(self):
        with self.assertRaises(ValueError):
            self.compiler.compile({})


if __name__ == "__main__":
    unittest.main()
