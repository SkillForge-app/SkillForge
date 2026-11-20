import copy
import unittest

import yaml

from backend.app.compiler.claude_artifacts import (
    AGENTS_DIR,
    COMMANDS_DIR,
    MAX_DESCRIPTION_LENGTH,
    subagent_tools,
)
from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler
from backend.tests.skillspec_fixtures import load_valid_spec


def split_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "file must start with YAML front matter"
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


class TestClaudeSubagent(unittest.TestCase):

    def setUp(self):
        self.spec = load_valid_spec()
        self.files = ClaudeCompiler().compile(self.spec)
        self.agent_path = f"{AGENTS_DIR}/{self.spec['skill']['name']}.md"

    def test_generates_one_subagent_named_after_the_skill(self):
        agents = [path for path in self.files if path.startswith(f"{AGENTS_DIR}/")]
        self.assertEqual(agents, [self.agent_path])

    def test_front_matter_is_valid(self):
        meta, _ = split_frontmatter(self.files[self.agent_path])

        self.assertEqual(meta["name"], self.spec["skill"]["name"])
        self.assertTrue(meta["description"].strip())
        self.assertNotIn("\n", meta["description"])
        self.assertLessEqual(len(meta["description"]), MAX_DESCRIPTION_LENGTH)

    def test_tools_include_baseline_and_are_sorted(self):
        meta, _ = split_frontmatter(self.files[self.agent_path])
        tools = [name.strip() for name in meta["tools"].split(",")]

        for baseline in ("Read", "Glob", "Grep"):
            self.assertIn(baseline, tools)
        self.assertEqual(tools, sorted(tools))

    def test_optional_and_required_capabilities_map_to_tools(self):
        spec = copy.deepcopy(self.spec)
        spec["tools"] = {"required": ["filesystem_write"], "optional": ["web_search"]}

        tools = subagent_tools(spec)

        self.assertIn("Write", tools)
        self.assertIn("Edit", tools)
        self.assertIn("WebSearch", tools)
        self.assertNotIn("Bash", tools)

    def test_body_lists_principles_guardrails_and_commands(self):
        _, body = split_frontmatter(self.files[self.agent_path])

        self.assertIn(self.spec["skill"]["title"], body)
        self.assertIn(self.spec["expertise"]["principles"][0], body)
        for procedure in self.spec["procedures"]:
            self.assertIn(f"`/{procedure['id']}`", body)
        for guardrail in self.spec.get("guardrails", []):
            self.assertIn(guardrail["rule"], body)


class TestClaudeCommands(unittest.TestCase):

    def setUp(self):
        self.spec = load_valid_spec()
        self.files = ClaudeCompiler().compile(self.spec)

    def test_one_command_per_procedure(self):
        commands = sorted(path for path in self.files if path.startswith(f"{COMMANDS_DIR}/"))
        expected = sorted(
            f"{COMMANDS_DIR}/{procedure['id']}.md" for procedure in self.spec["procedures"]
        )
        self.assertEqual(commands, expected)

    def test_command_has_description_arguments_and_numbered_steps(self):
        for procedure in self.spec["procedures"]:
            text = self.files[f"{COMMANDS_DIR}/{procedure['id']}.md"]
            meta, body = split_frontmatter(text)

            self.assertTrue(meta["description"].strip())
            self.assertNotIn("allowed-tools", meta)
            self.assertIn("$ARGUMENTS", body)
            for index, step in enumerate(procedure["steps"], 1):
                self.assertIn(f"{index}. {step}", body)

    def test_command_lists_what_it_produces(self):
        procedure = next(item for item in self.spec["procedures"] if item.get("produces"))
        body = self.files[f"{COMMANDS_DIR}/{procedure['id']}.md"]

        self.assertIn("## Produces", body)
        for item in procedure["produces"]:
            self.assertIn(item, body)

    def test_command_points_to_reference_files_when_known(self):
        references = {
            reference["id"]: reference["file"]
            for reference in self.spec.get("knowledge", {}).get("references", [])
        }
        procedure = next(
            (item for item in self.spec["procedures"] if set(item.get("uses", [])) & set(references)),
            None,
        )
        if procedure is None:
            self.skipTest("fixture has no procedure that uses a reference")

        body = self.files[f"{COMMANDS_DIR}/{procedure['id']}.md"]
        for used in procedure["uses"]:
            self.assertIn(references.get(used, used), body)


class TestClaudeArtifactsSafety(unittest.TestCase):

    def test_output_is_deterministic(self):
        spec = load_valid_spec()
        self.assertEqual(ClaudeCompiler().compile(spec), ClaudeCompiler().compile(spec))

    def test_existing_files_are_still_generated(self):
        files = ClaudeCompiler().compile(load_valid_spec())

        self.assertIn("CLAUDE.md", files)
        self.assertIn(".claude/settings.json", files)

    def test_description_is_quoted_so_colons_cannot_break_front_matter(self):
        spec = copy.deepcopy(load_valid_spec())
        spec["skill"]["summary"] = "Reviews contracts: flags risk, never gives legal advice."
        spec["triggers"]["use_when"] = ['a request that says "review this": any contract']

        files = ClaudeCompiler().compile(spec)
        meta, _ = split_frontmatter(files[f"{AGENTS_DIR}/{spec['skill']['name']}.md"])

        self.assertIn("Reviews contracts: flags risk", meta["description"])


if __name__ == "__main__":
    unittest.main()
