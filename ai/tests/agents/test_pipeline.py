"""The AI pipeline interface (contract for BE-07/BE-08): statuses, progress, usage, the fake."""

from collections.abc import Callable

import pytest
from pydantic import TypeAdapter

from core.analysis import AnalyzedRequest, Answer
from core.analysis.safety import refusal_message
from core.llm import (
    BudgetExceeded,
    FakeGateway,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
    use_fake,
)
from core.pipeline import (
    AIPipeline,
    FakePipeline,
    ProgressEvent,
    RealPipeline,
    StepResult,
    interface,
)
from core.pipeline.fake import _unanswered, example_request
from core.pipeline.interface import (
    DESIGN_BLOCKED_MESSAGE,
    DESIGN_BUDGET_MESSAGE,
    DESIGN_INVALID_MESSAGE,
    DESIGN_NOT_READY_MESSAGE,
    DESIGN_PAUSED_MESSAGE,
    DESIGN_READY_MESSAGE,
    INVALID_ANSWERS_MESSAGE,
    INVALID_REQUEST_MESSAGE,
    closing_event,
)
from core.spec import SkillSpec
from tests.agents.helpers import ScriptedGateway, bad_spec, good_spec, screened

QUESTIONS = [
    {"id": "q1", "text": "Who is it for?", "about": "audience"},
    {"id": "q2", "text": "What should it produce?", "about": "outputs"},
    {"id": "q3", "text": "Which platforms?", "about": "platforms"},
]
ANALYSIS = {
    "kind": "task",
    "domain": "writing/press-releases",
    "risk": "low",
    "mentioned_targets": [],
    "summary": "Writes press releases.",
    "needs_clarification": False,
    "questions": [],
}


def test_both_pipelines_implement_the_protocol() -> None:
    real: AIPipeline = RealPipeline()
    fake: AIPipeline = FakePipeline()
    assert real and fake


# ---------------------------------------------------------------- RealPipeline with fake models


async def test_analyze_ok_records_usage(fake: FakeGateway) -> None:
    result = await RealPipeline().analyze("A skill that writes press releases")
    assert result.status == "ok" and result.value is not None
    assert result.value.safety is not None
    assert result.usage.calls == 2  # the safety screen and the analysis


async def test_analyze_needs_input(fake: FakeGateway) -> None:
    fake.register(
        "analysis/request", {**ANALYSIS, "needs_clarification": True, "questions": QUESTIONS}
    )
    result = await RealPipeline().analyze("help")
    assert result.status == "needs_input"
    assert result.value is not None and len(result.value.questions) == 3


async def test_analyze_blocked(fake: FakeGateway) -> None:
    fake.register(
        "analysis/safety", {"verdict": "block", "category": "fraud_scams", "rationale": "r"}
    )
    result = await RealPipeline().analyze("placeholder request")
    assert result.status == "blocked" and result.value is None
    assert result.error_code == "blocked.fraud_scams"
    assert result.user_message == refusal_message("fraud_scams")


async def test_analyze_retry_later_when_screen_is_down(fake: FakeGateway) -> None:
    fake.register_error("analysis/safety", LLMUnavailable("down"))
    result = await RealPipeline().analyze("x")
    assert result.status == "retry_later" and result.error_code == "provider_unavailable"


async def test_analyze_failed_when_analysis_is_invalid(fake: FakeGateway) -> None:
    fake.register_error("analysis/request", LLMOutputInvalid("bad"))
    result = await RealPipeline().analyze("x")
    assert result.status == "failed"
    assert result.error_code == "analysis_failed.LLMOutputInvalid"


# ---------------------------------------------------------------- input rules (review F2)


@pytest.mark.parametrize("text", ["", "   \n ", "x" * 4001])
async def test_analyze_refuses_bad_text_before_any_model_call(fake: FakeGateway, text: str) -> None:
    for pipeline in (RealPipeline(), FakePipeline()):
        result = await pipeline.analyze(text)
        assert (result.status, result.error_code) == ("failed", "invalid_request")
        assert result.user_message == INVALID_REQUEST_MESSAGE and result.value is None
        assert result.usage.calls == 0
    assert fake.calls == []  # not one paid call


async def test_analyze_takes_exactly_4000_characters(fake: FakeGateway) -> None:
    for pipeline in (RealPipeline(), FakePipeline()):
        assert (await pipeline.analyze("x" * 4000)).status == "ok"


async def first_pass(fake: FakeGateway) -> AnalyzedRequest:
    fake.register(
        "analysis/request", {**ANALYSIS, "needs_clarification": True, "questions": QUESTIONS}
    )
    first = await RealPipeline().analyze("help")
    assert first.value is not None
    fake.register("analysis/request", ANALYSIS)
    fake.calls.clear()
    return first.value


@pytest.mark.parametrize(
    "answers",
    [
        [],  # no answers at all: every question skipped
        [Answer(question_id=q, text=None) for q in ("q1", "q2", "q3")],  # one empty answer each
    ],
)
async def test_clarify_with_every_question_skipped(
    fake: FakeGateway, answers: list[Answer]
) -> None:
    analyzed = await first_pass(fake)
    for pipeline in (RealPipeline(), FakePipeline()):
        result = await pipeline.clarify(analyzed, answers)
        assert result.status == "ok" and result.value is not None
    sent = [c for c in fake.calls if c.prompt_id == "analysis/request"][0]
    assert sent.inputs is not None
    assert [a["answer"] for a in sent.inputs["answers"]] == [None, None, None]


@pytest.mark.parametrize(
    "answers",
    [
        [Answer(question_id="q4", text="not asked")],
        [Answer(question_id="q1", text="one"), Answer(question_id="q1", text="two")],
    ],
)
async def test_clarify_refuses_answers_to_unasked_or_repeated_questions(
    fake: FakeGateway, answers: list[Answer]
) -> None:
    analyzed = await first_pass(fake)
    for pipeline in (RealPipeline(), FakePipeline()):
        result = await pipeline.clarify(analyzed, answers)
        assert (result.status, result.error_code) == ("failed", "invalid_request")
        assert result.user_message == INVALID_ANSWERS_MESSAGE and result.usage.calls == 0
    assert fake.calls == []


async def test_an_unexpected_validation_error_is_a_result_without_the_users_text() -> None:
    async def run() -> AnalyzedRequest:
        TypeAdapter(int).validate_python("SECRET user text")
        raise AssertionError("unreachable")

    result = await interface._analysis_step("analyze", run())
    assert (result.status, result.error_code) == ("failed", "analysis_failed.ValidationError")
    assert "SECRET" not in result.model_dump_json()


async def test_clarify_then_design(fake: FakeGateway) -> None:
    fake.register(
        "analysis/request", {**ANALYSIS, "needs_clarification": True, "questions": QUESTIONS}
    )
    pipeline = RealPipeline()
    first = await pipeline.analyze("help")
    assert first.value is not None
    fake.register("analysis/request", ANALYSIS)
    second = await pipeline.clarify(first.value, [Answer(question_id="q1", text="Our PR team")])
    assert second.status == "ok" and second.value is not None
    events: list[ProgressEvent] = []
    designed = await pipeline.design(second.value, on_progress=events.append)
    assert designed.status == "ok" and designed.value is not None
    assert designed.value.skill.domain == "writing/press-releases"
    assert [(e.stage, e.attempt) for e in events] == [
        ("started", None),
        ("attempt", 1),
        ("done", 1),
    ]
    assert designed.usage.calls == 1


async def test_design_failed_after_three_attempts() -> None:
    gateway = ScriptedGateway(
        {"architect/generate": [bad_spec()], "architect/repair": [bad_spec(), bad_spec()]}
    )
    events: list[ProgressEvent] = []
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await RealPipeline().design(screened(), on_progress=events.append)
    assert result.status == "failed" and result.error_code == "invalid_spec"
    assert [i.code for i in result.issues] == ["unknown_source"]
    assert [e.stage for e in events] == ["started", "attempt", "repairing", "repairing", "failed"]


@pytest.mark.parametrize(
    ("analyzed_changes", "script", "status", "code"),
    [
        ({"safety": None}, {}, "failed", "not_screened"),
        (
            {},
            {"architect/generate": [LLMUnavailable("down")]},
            "retry_later",
            "provider_unavailable",
        ),
    ],
)
async def test_design_status_mapping(
    analyzed_changes: dict[str, object], script: dict[str, list[object]], status: str, code: str
) -> None:
    with use_fake(ScriptedGateway(script)):  # type: ignore[arg-type]
        result = await RealPipeline().design(screened("ai-engineer", **analyzed_changes))
    assert (result.status, result.error_code) == (status, code)


# ---------------------------------------------------------------- closing event (review F12)


def not_ready() -> AnalyzedRequest:
    return _unanswered(example_request("marketing-strategist"))  # open questions, screened


@pytest.mark.parametrize(
    ("analyzed", "script", "outcome", "closing"),
    [
        (lambda: screened(), {}, ("ok", None), ("done", 1, DESIGN_READY_MESSAGE)),
        (
            lambda: screened(safety=None),
            {},
            ("failed", "not_screened"),
            ("failed", None, DESIGN_NOT_READY_MESSAGE),
        ),
        (
            not_ready,
            {},
            ("needs_input", "open_questions"),
            ("failed", None, DESIGN_NOT_READY_MESSAGE),
        ),
        (
            lambda: screened(),
            {"architect/generate": [LLMUnavailable("down")]},
            ("retry_later", "provider_unavailable"),
            ("failed", 1, DESIGN_PAUSED_MESSAGE),
        ),
        (
            lambda: screened(),
            {"architect/generate": [LLMRefused("no")]},
            ("blocked", "blocked.other"),
            ("failed", 1, DESIGN_BLOCKED_MESSAGE),
        ),
        (
            lambda: screened(),
            {"architect/generate": [BudgetExceeded("spent")]},
            ("failed", "budget_exceeded"),
            ("failed", 1, DESIGN_BUDGET_MESSAGE),
        ),
    ],
)
async def test_every_design_ends_with_exactly_one_closing_event(
    analyzed: Callable[[], AnalyzedRequest],
    script: dict[str, list[object]],
    outcome: tuple[str, str | None],
    closing: tuple[str, int | None, str],
) -> None:
    gateway = ScriptedGateway(script or {"architect/generate": [good_spec()]})
    events: list[ProgressEvent] = []
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await RealPipeline().design(analyzed(), on_progress=events.append)
    assert (result.status, result.error_code) == outcome
    assert [e.stage in ("done", "failed") for e in events].count(True) == 1
    assert (events[-1].stage, events[-1].attempt, events[-1].message) == closing
    if result.status == "needs_input":
        assert result.value is None  # design's needs_input: run clarify first


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        ("ok", None, DESIGN_READY_MESSAGE),
        ("failed", "invalid_spec", DESIGN_INVALID_MESSAGE),
        ("retry_later", "deadline_exceeded", DESIGN_PAUSED_MESSAGE),
        ("blocked", "blocked.other", DESIGN_BLOCKED_MESSAGE),
    ],
)
async def test_the_fake_closes_design_like_the_real_pipeline(
    status: str, code: str | None, message: str
) -> None:
    fake = FakePipeline()
    fake.set("design", status, error_code=code)  # type: ignore[arg-type]
    events: list[ProgressEvent] = []
    await fake.design(screened(), on_progress=events.append)
    assert [e.stage in ("done", "failed") for e in events].count(True) == 1
    assert events[-1].message == message == closing_event(status, code)[1]  # type: ignore[arg-type]


# ---------------------------------------------------------------- FakePipeline


async def test_fake_pipeline_defaults_are_ok() -> None:
    fake = FakePipeline()
    analyzed = await fake.analyze("anything", selected_targets=["claude"])
    assert analyzed.status == "ok" and analyzed.value is not None
    events: list[ProgressEvent] = []
    designed = await fake.design(analyzed.value, on_progress=events.append)
    assert designed.status == "ok" and designed.value is not None
    assert [e.stage for e in events] == ["started", "attempt", "done"]
    assert [step for step, _ in fake.calls] == ["analyze", "design"]


@pytest.mark.parametrize("status", ["needs_input", "blocked", "retry_later", "failed"])
async def test_fake_pipeline_can_be_scripted(status: str) -> None:
    fake = FakePipeline()
    fake.set("analyze", status, user_message="msg", error_code="code")  # type: ignore[arg-type]
    result = await fake.analyze("x")
    assert result.status == status
    if status == "needs_input":
        assert result.value is not None and result.value.needs_clarification
    else:
        assert result.value is None and result.user_message == "msg"


async def test_results_round_trip_through_json(fake: FakeGateway) -> None:
    pipeline = RealPipeline()
    analyzed = await pipeline.analyze("A skill that writes press releases")
    again = StepResult[AnalyzedRequest].model_validate_json(analyzed.model_dump_json())
    assert again == analyzed
    assert analyzed.value is not None
    designed = await pipeline.design(analyzed.value)
    back = StepResult[SkillSpec].model_validate_json(designed.model_dump_json())
    assert back == designed and back.pipeline_version == "0.1"
