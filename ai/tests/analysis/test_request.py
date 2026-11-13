"""analyze_request / answer_questions with the FakeGateway (no network)."""

from typing import Any

import pytest

from core.analysis import Answer, analyze_request, answer_questions
from core.llm import FakeGateway, LLMOutputInvalid, load_prompt
from core.spec import DOMAIN_AREAS, HIGH_RISK_AREAS, KINDS

QUESTIONS = [
    {"id": "q1", "text": "Who will use it?", "about": "audience"},
    {"id": "q2", "text": "What should it produce?", "about": "outputs"},
    {"id": "q3", "text": "Which platforms?", "about": "platforms"},
]


def llm_answer(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "task",
        "domain": "writing/press-releases",
        "risk": "low",
        "audience": None,
        "expected_outputs": ["press release"],
        "mentioned_targets": [],
        "skill_name": "write-press-release",
        "summary": "Writes press releases.",
        "needs_clarification": False,
        "questions": [],
    }
    data.update(changes)
    return data


async def test_default_fixture_answers_without_registering(fake: FakeGateway) -> None:
    analyzed = await analyze_request("any request at all")
    assert analyzed.kind == "role" and analyzed.domain_area == "marketing"


async def test_prompt_gets_the_shared_vocabularies(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer())
    await analyze_request("Write press releases for us")
    [call] = fake.calls
    assert call.inputs is not None
    assert call.inputs["kinds"] == list(KINDS)
    assert call.inputs["domain_areas"] == list(DOMAIN_AREAS)
    assert call.inputs["high_risk_areas"] == sorted(HIGH_RISK_AREAS)
    assert call.messages is not None
    assert "<request>\nWrite press releases for us\n</request>" in call.messages[1]["content"]
    assert ", ".join(DOMAIN_AREAS) in call.messages[0]["content"]


async def test_records_prompt_and_request(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer())
    analyzed = await analyze_request("Write press releases for us")
    assert analyzed.request == "Write press releases for us"
    assert analyzed.analyzer.prompt_version == load_prompt("analysis/request").version


@pytest.mark.parametrize(
    ("domain", "model_risk", "expected"),
    [
        ("legal/contracts", "low", "high"),  # high-risk area: always high
        ("finance/tax", "medium", "high"),
        ("hr/recruiting", "high", "medium"),  # high outside the high-risk areas: medium
        ("design/ux", "high", "medium"),
        ("design/ux", "low", "low"),
        ("hr/recruiting", "medium", "medium"),
    ],
)
async def test_risk_rule_is_applied_in_code(
    fake: FakeGateway, domain: str, model_risk: str, expected: str
) -> None:
    fake.register("analysis/request", llm_answer(domain=domain, risk=model_risk))
    assert (await analyze_request("x")).risk == expected


async def test_targets_combine_ui_choice_and_mentions(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer(mentioned_targets=["generic", "claude"]))
    analyzed = await analyze_request("x", selected_targets=["codex", "claude"])
    assert analyzed.targets == ["claude", "codex", "generic"]  # TARGETS order, no duplicates


async def test_vague_request_gets_questions(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer(needs_clarification=True, questions=QUESTIONS))
    analyzed = await analyze_request("help")
    assert analyzed.needs_clarification
    assert [q.id for q in analyzed.questions] == ["q1", "q2", "q3"]


@pytest.mark.parametrize(
    "changes",
    [
        {"needs_clarification": True, "questions": QUESTIONS[:2]},  # too few
        {"needs_clarification": False, "questions": QUESTIONS},  # questions without need
        {"domain": "cooking/baking"},  # area outside the closed list
    ],
)
async def test_invalid_llm_answers_are_rejected(fake: FakeGateway, changes: dict[str, Any]) -> None:
    fake.register("analysis/request", llm_answer(**changes))
    with pytest.raises(LLMOutputInvalid):
        await analyze_request("help")


async def test_answers_pass_never_asks_again(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer(needs_clarification=True, questions=QUESTIONS))
    first = await analyze_request("help", selected_targets=["claude"])
    fake.register(
        "analysis/request",
        llm_answer(domain="hr/recruiting", kind="role", audience="warehouse managers"),
    )
    answers = [Answer(question_id="q1", text="Warehouse managers"), Answer(question_id="q3")]
    second = await answer_questions(first, answers)
    assert not second.needs_clarification
    assert second.questions == first.questions and second.answers == answers
    assert second.targets == ["claude"] and second.domain == "hr/recruiting"
    call = fake.calls[-1]
    assert call.inputs is not None
    assert call.inputs["answers"] == [
        {"question": "Who will use it?", "answer": "Warehouse managers"},
        {"question": "Which platforms?", "answer": None},
    ]
    assert call.messages is not None and "(skipped)" in call.messages[1]["content"]


async def test_answers_to_unknown_questions_fail_before_any_llm_call(fake: FakeGateway) -> None:
    fake.register("analysis/request", llm_answer(needs_clarification=True, questions=QUESTIONS))
    first = await analyze_request("help")
    calls = len(fake.calls)
    with pytest.raises(ValueError, match="not asked"):
        await answer_questions(first, [Answer(question_id="q5", text="x")])
    assert len(fake.calls) == calls


async def test_arabic_request_passes_through(fake: FakeGateway) -> None:
    text = "أريد مهارة تشرح نتائج تحاليل الدم للمرضى بلغة بسيطة."
    fake.register("analysis/request", llm_answer(domain="medical/patient-education"))
    analyzed = await analyze_request(text)
    assert analyzed.request == text and analyzed.risk == "high"
