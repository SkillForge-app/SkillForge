
import unittest

from backend.app.compiler.base_compiler import BaseCompiler
from backend.app.compiler.compilers.noop_compiler import NoOpCompiler


class TestBaseCompiler(unittest.TestCase):

    def test_cannot_instantiate_base_compiler(self):
        with self.assertRaises(TypeError):
            BaseCompiler()

    def test_subclass_must_implement_compile(self):
        class IncompleteCompiler(BaseCompiler):
            pass

        with self.assertRaises(TypeError):
            IncompleteCompiler()

    def test_valid_compiler(self):
        class DummyCompiler(BaseCompiler):
            def compile(self, agent_spec):
                return {"test.txt": "Hello AgentForge"}

        compiler = DummyCompiler()
        result = compiler.compile({})

        self.assertEqual(result, {"test.txt": "Hello AgentForge"})

    # الاختبار الرابع الجديد
    def test_noop_compiler(self):
        compiler = NoOpCompiler()

        result = compiler.compile({
            "name": "Test Agent",
            "description": "Testing NoOpCompiler"
        })

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
