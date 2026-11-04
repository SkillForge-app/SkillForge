import json
import unittest
import unittest

from pydantic import ValidationError

from backend.app.compiler.compilers.claude_compiler import ClaudeCompiler


class TestClaudeCompiler(unittest.TestCase):




    def test_generates_commands_from_workflow(self):
        self.valid_spec["agent"]["workflow"] = {
            "steps": ["Review code", "Run tests"]
        }

        result = self.compiler.compile(self.valid_spec)

        command_files = [
            path for path in result
            if path.startswith(".claude/commands/")
        ]

        self.assertEqual(len(command_files), 2)
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
    def test_generates_subagent(self):
        self.valid_spec["agent"]["config"] = {
            "claude_code": {
                "subagents": [
                    {
                        "name": "code-reviewer",
                        "description": "Review code quality",
                        "instructions": "Review code and report issues.",
                    }
                ]
            }
        }

        result = self.compiler.compile(self.valid_spec)

        path = ".claude/agents/code-reviewer.md"

        self.assertIn(path, result)
        self.assertIn("code-reviewer", result[path])
        self.assertIn("Review code and report issues.", result[path])





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

    def test_generates_claude_settings(self):
        result = self.compiler.compile(self.valid_spec)

        self.assertIn(".claude/settings.json", result)

        settings = json.loads(result[".claude/settings.json"])

        self.assertEqual(
            settings["permissions"],
            {
                "allow": [],
                "ask": [],
                "deny": [],
            },
        )

    def test_permissions_from_tools(self):
        self.valid_spec["agent"]["tools"] = [
            "Read", "Write"
        ]
        self.valid_spec["tools"] = [
            {"name": "Read", "enabled": True},
            {"name": "Write", "enabled": True},
        ]

        result = self.compiler.compile(self.valid_spec)
        settings = json.loads(result[".claude/settings.json"])

        self.assertIn("Read", settings["permissions"]["allow"])
        self.assertIn("Write", settings["permissions"]["ask"])

    def test_deny_permission(self):
        self.valid_spec["agent"]["tools"] = ["Read"]
        self.valid_spec["tools"] = [
            {"name": "Read", "enabled": True}
        ]
        self.valid_spec["agent"]["constraints"] = {
            "rules": ["deny:Read"]
        }

        result = self.compiler.compile(self.valid_spec)
        settings = json.loads(result[".claude/settings.json"])

        self.assertNotIn("Read", settings["permissions"]["allow"])
        self.assertIn("Read", settings["permissions"]["deny"])


    def test_generates_slash_command(self):
        self.valid_spec["agent"]["config"] = {
            "claude_code": {
                "commands": [
                    {
                        "name": "review",
                        "description": "Review project code",
                        "prompt": (
                            "Review the project code and "
                            "report important issues."
                        ),
                    }
                ]
            }
        }

        result = self.compiler.compile(self.valid_spec)

        path = ".claude/commands/review.md"

        self.assertIn(path, result)
        self.assertIn(
            "Review project code",
            result[path],
        )
        self.assertIn(
            "Review the project code",
            result[path],
        )

    def test_rejects_unsafe_subagent_name(self):
        self.valid_spec["agent"]["config"] = {
            "claude_code": {
                "subagents": [{
                    "name": "../secret",
                    "description": "Unsafe agent",
                    "instructions": "Do something",
                }]
            }
        }

        with self.assertRaisesRegex(ValueError, "Invalid subagent name"):
            self.compiler.compile(self.valid_spec)

    def test_rejects_duplicate_commands(self):
        command = {
            "name": "review",
            "description": "Review code",
            "prompt": "Review the project.",
        }

        self.valid_spec["agent"]["config"] = {
            "claude_code": {
                "commands": [command, command.copy()]
            }
        }

        with self.assertRaisesRegex(ValueError, "Duplicate command"):
            self.compiler.compile(self.valid_spec)

if __name__ == "__main__":
    unittest.main()
