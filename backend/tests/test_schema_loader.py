
import unittest

from backend.app.compiler.schema_loader import load_platform_schema


class TestSchemaLoader(unittest.TestCase):

    def test_load_claude_code_schema(self):
        schema = load_platform_schema("claude_code")

        self.assertEqual(schema.name, "claude_code")
        self.assertEqual(schema.instruction_file, "CLAUDE.md")
        self.assertEqual(
            schema.config_file,
            ".claude/settings.json"
        )

    def test_missing_schema(self):
        with self.assertRaises(FileNotFoundError):
            load_platform_schema("unknown_platform")


if __name__ == "__main__":
    unittest.main()

