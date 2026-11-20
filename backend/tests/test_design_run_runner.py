import asyncio
import copy
import json
import unittest

from backend.app.pipeline.outcome import StepOutcome
from backend.app.pipeline.runner import (
    MAX_PROGRESS_EVENTS,
    RunState,
    RunStateError,
    answer,
    start,
)
from backend.tests.pipeline_stubs import ScriptedPipeline, analyzed, ok, valid_spec



def run(coro):
    return asyncio.run(coro)


class TestHappyPath(unittest.TestCase):

    def setUp(self):
        self.pipeline = ScriptedPipeline(
            analyze=ok("analyze", analyzed(), usage={"calls": 2, "cost_usd": 0.01}),
            design=ok("design", valid_spec(), usage={"calls": 1, "cost_usd": 0.05, "input_tokens": 900}),
        )
        self.saved: list[tuple[str, int]] = []
        self.state = RunState()

    def save(self, state):
        self.saved.append((state.status, len(state.progress)))

    def test_completes_with_a_validated_spec(self):
        state = run(
            start(self.pipeline, self.state, "text", ["claude"], ["taken-name"], save=self.save)
        )

        self.assertEqual(state.status, "completed")
        self.assertEqual(state.step, "design")
        self.assertEqual(state.spec["skill"]["name"], "ai-engineer")
        self.assertIsNone(state.error_code)
        self.assertEqual(self.pipeline.steps, ["analyze", "design"])
        self.assertEqual(self.pipeline.calls[0][1], ("text", ["claude"]))
        self.assertEqual(self.pipeline.calls[1][1][1], ["taken-name"])

    def test_usage_is_added_up_over_the_steps(self):
        state = run(start(self.pipeline, self.state, "text", ["claude"]))

        self.assertEqual(state.usage["calls"], 3)
        self.assertEqual(state.usage["input_tokens"], 900)
        self.assertAlmostEqual(state.usage["cost_usd"], 0.06)

    def test_progress_events_are_kept_and_saved_as_they_arrive(self):
        state = run(start(self.pipeline, self.state, "text", ["claude"], save=self.save))

        self.assertEqual([event["stage"] for event in state.progress], ["started", "done"])
        # A client polling during the design sees the first event before the second one.
        self.assertIn(("running", 1), self.saved)
        self.assertIn(("running", 2), self.saved)
        self.assertEqual(self.saved[-1], ("completed", 2))

    def test_a_run_can_only_be_started_once(self):
        run(start(self.pipeline, self.state, "text", ["claude"]))

        with self.assertRaises(RunStateError):
            run(start(self.pipeline, self.state, "text", ["claude"]))


class TestClarification(unittest.TestCase):

    def setUp(self):
        self.pipeline = ScriptedPipeline(
            analyze=StepOutcome(step="analyze", status="needs_input", value=analyzed(questions=True)),
            clarify=ok("clarify", analyzed()),
            design=ok("design", valid_spec()),
        )

    def test_stops_with_the_questions_and_does_not_design(self):
        state = run(start(self.pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "needs_input")
        self.assertEqual([q["id"] for q in state.questions], ["q1", "q2", "q3"])
        self.assertEqual(self.pipeline.steps, ["analyze"])

    def test_answers_continue_to_a_finished_design(self):
        state = run(start(self.pipeline, RunState(), "text", ["claude"]))
        answers = [{"question_id": "q1", "text": "Python"}, {"question_id": "q2", "text": None}]

        state = run(answer(self.pipeline, state, answers))

        self.assertEqual(state.status, "completed")
        self.assertEqual(state.questions, [])
        self.assertEqual(self.pipeline.steps, ["analyze", "clarify", "design"])
        self.assertEqual(self.pipeline.calls[1][1][1], answers)

    def test_answering_a_run_that_is_not_waiting_is_an_error(self):
        state = run(start(ScriptedPipeline(
            analyze=ok("analyze", analyzed()), design=ok("design", valid_spec())
        ), RunState(), "text", ["claude"]))

        with self.assertRaises(RunStateError):
            run(answer(self.pipeline, state, []))

    def test_a_second_round_of_questions_fails_the_run(self):
        pipeline = ScriptedPipeline(
            analyze=StepOutcome(step="analyze", status="needs_input", value=analyzed(questions=True)),
            clarify=StepOutcome(step="clarify", status="needs_input", value=analyzed(questions=True)),
        )
        state = run(start(pipeline, RunState(), "text", ["claude"]))

        state = run(answer(pipeline, state, []))

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.error_code, "clarification_loop")
        self.assertNotIn("design", pipeline.steps)

    def test_design_that_still_needs_input_pauses_the_run(self):
        pipeline = ScriptedPipeline(
            analyze=ok("analyze", analyzed()),
            design=StepOutcome(
                step="design", status="needs_input", value=None, error_code="open_questions"
            ),
        )
        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "needs_input")
        self.assertEqual(state.error_code, "open_questions")


class TestStopsBeforeDesign(unittest.TestCase):

    def test_blocked_request_is_not_kept_and_starts_no_design(self):
        pipeline = ScriptedPipeline(
            analyze=StepOutcome(
                step="analyze",
                status="blocked",
                user_message="We can't create this skill.",
                error_code="blocked.fraud_scams",
            )
        )
        state = RunState(analyzed={"request": "left over"})
        state.status = "queued"

        state = run(start(pipeline, state, "text", ["claude"]))

        self.assertEqual(state.status, "blocked")
        self.assertEqual(state.user_message, "We can't create this skill.")
        self.assertEqual(state.error_code, "blocked.fraud_scams")
        self.assertIsNone(state.analyzed)
        self.assertIsNone(state.spec)
        self.assertEqual(pipeline.steps, ["analyze"])

    def test_retry_later_and_failed_are_reported_as_they_are(self):
        for status in ("retry_later", "failed"):
            with self.subTest(status=status):
                pipeline = ScriptedPipeline(
                    analyze=StepOutcome(
                        step="analyze",
                        status=status,
                        user_message="Try again.",
                        error_code="provider_unavailable",
                    )
                )

                state = run(start(pipeline, RunState(), "text", ["claude"]))

                self.assertEqual(state.status, status)
                self.assertEqual(state.user_message, "Try again.")
                self.assertEqual(pipeline.steps, ["analyze"])

    def test_ok_without_a_value_is_a_failure_not_a_crash(self):
        pipeline = ScriptedPipeline(analyze=StepOutcome(step="analyze", status="ok", value=None))

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.error_code, "empty_result")


class TestDesignOutcomes(unittest.TestCase):

    def test_failed_design_keeps_the_issues(self):
        issues = [{"path": "/procedures", "code": "too_short", "message": "x", "severity": "error"}]
        pipeline = ScriptedPipeline(
            analyze=ok("analyze", analyzed()),
            design=StepOutcome(
                step="design",
                status="failed",
                user_message="We could not design this skill.",
                error_code="invalid_spec",
                issues=issues,
            ),
        )

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.issues, issues)
        self.assertIsNone(state.spec)

    def test_a_spec_the_backend_validator_rejects_is_not_completed(self):
        broken = valid_spec()
        broken["spec_version"] = "999"
        pipeline = ScriptedPipeline(analyze=ok("analyze", analyzed()), design=ok("design", broken))

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "failed")
        self.assertEqual(state.error_code, "invalid_spec")
        self.assertIsNone(state.spec)
        self.assertTrue(state.issues)
        self.assertTrue(all(issue["severity"] == "error" for issue in state.issues))
        self.assertNotIn("999", json.dumps(state.issues))  # messages never echo field values

    def test_warnings_from_the_ai_package_are_kept_on_a_completed_run(self):
        warning = [{"path": "/sources", "code": "no_sources", "message": "w", "severity": "warning"}]
        pipeline = ScriptedPipeline(
            analyze=ok("analyze", analyzed()), design=ok("design", valid_spec(), issues=warning)
        )

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(state.status, "completed")
        self.assertEqual(state.issues, warning)

    def test_the_stored_spec_is_a_copy_of_what_was_validated(self):
        spec = valid_spec()
        original = copy.deepcopy(spec)
        pipeline = ScriptedPipeline(analyze=ok("analyze", analyzed()), design=ok("design", spec))

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(spec, original)  # the pipeline's own dict is not changed
        self.assertEqual(state.spec["spec_version"], "0.2")

    def test_progress_is_capped(self):
        pipeline = ScriptedPipeline(
            analyze=ok("analyze", analyzed()), design=ok("design", valid_spec())
        )
        pipeline.progress_events = [
            {"step": "design", "stage": "attempt", "attempt": 1, "message": str(i)}
            for i in range(MAX_PROGRESS_EVENTS + 50)
        ]

        state = run(start(pipeline, RunState(), "text", ["claude"]))

        self.assertEqual(len(state.progress), MAX_PROGRESS_EVENTS)


if __name__ == "__main__":
    unittest.main()
