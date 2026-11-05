"""Skill Architect v0 (AI-07): refusals, the repair loop, enforce, the graph, the prompts."""

import json
import os
import re

import pytest

from core.agents import (
    MAX_ATTEMPTS,
    ArchitectRefused,
    ArchitectUnavailable,
    NotReady,
    NotScreened,
    build_graph,
    build_spec,
    enforce,
    required_guardrails,
)
from core.agents.architect import CONDITION_GUARDRAILS, GENERATE, REPAIR
from core.analysis.types import SAFETY_CONDITIONS, SafetyClearance
from core.llm import (
    FakeGateway,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
    load_prompt,
    use_fake,
)
from core.llm.prompt_lock import check_lock
from core.llm.prompts import PROMPTS_DIR
from core.spec import validate_spec
from tests.agents.helpers import ScriptedGateway, bad_spec, good_spec, screened

# ---------------------------------------------------------------- refusals


async def test_refuses_unscreened_requests_before_any_call(fake: FakeGateway) -> None:
    with pytest.raises(NotScreened):
        await build_spec(screened(safety=None))
    assert fake.calls == []


async def test_refuses_requests_with_open_questions(fake: FakeGateway) -> None:
    open_questions = screened("marketing-strategist", needs_clarification=True, answers=[])
    with pytest.raises(NotReady):
        await build_spec(open_questions)
    assert fake.calls == []


# ---------------------------------------------------------------- the loop


async def test_valid_spec_on_the_first_try(fake: FakeGateway) -> None:
    analyzed = screened("ai-engineer")
    events: list[tuple[str, int]] = []
    result = await build_spec(analyzed, on_progress=lambda s, n: events.append((s, n)))
    assert result.ok and result.attempts == 1 and result.spec is not None
    assert result.spec.skill.kind == analyzed.kind and result.spec.skill.domain == analyzed.domain
    assert result.spec.targets == ["codex"]  # from the analysis
    assert events == [("attempt", 1), ("done", 1)]
    assert result.prompt_versions == {GENERATE: 1, REPAIR: 1}


async def test_issues_are_sent_back_and_repaired() -> None:
    gateway = ScriptedGateway({GENERATE: [bad_spec()], REPAIR: [good_spec()]})
    events: list[tuple[str, int]] = []
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await build_spec(screened(), on_progress=lambda s, n: events.append((s, n)))
    assert result.ok and result.attempts == 2
    assert gateway.prompts() == [GENERATE, REPAIR]
    repair_inputs = gateway.calls[1][1]
    assert any("unknown_source" in issue for issue in repair_inputs["issues"])
    assert '"src-missing"' in repair_inputs["previous_spec"]
    assert repair_inputs["attempt"] == 2 and repair_inputs["max_attempts"] == MAX_ATTEMPTS
    assert events == [("attempt", 1), ("repairing", 2), ("done", 2)]


async def test_gives_up_after_three_attempts() -> None:
    gateway = ScriptedGateway({GENERATE: [bad_spec()], REPAIR: [bad_spec(), bad_spec()]})
    events: list[tuple[str, int]] = []
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await build_spec(screened(), on_progress=lambda s, n: events.append((s, n)))
    assert not result.ok and result.spec is None and result.attempts == MAX_ATTEMPTS == 3
    assert gateway.prompts() == [GENERATE, REPAIR, REPAIR]
    assert [i.code for i in result.issues] == ["unknown_source"]
    assert events[-1] == ("failed", 3)


async def test_an_invalid_reply_counts_as_an_attempt() -> None:
    gateway = ScriptedGateway({GENERATE: [LLMOutputInvalid("bad json"), good_spec()]})
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await build_spec(screened())
    assert result.ok and result.attempts == 2
    assert gateway.prompts() == [GENERATE, GENERATE]  # nothing to repair yet: generate again


@pytest.mark.parametrize(
    ("error", "expected"),
    [(LLMUnavailable("down"), ArchitectUnavailable), (LLMRefused("no"), ArchitectRefused)],
)
async def test_provider_errors_stop_the_loop(error: Exception, expected: type[Exception]) -> None:
    gateway = ScriptedGateway({GENERATE: [error]})
    with use_fake(gateway), pytest.raises(expected):  # type: ignore[arg-type]
        await build_spec(screened())
    assert len(gateway.calls) == 1


# ---------------------------------------------------------------- enforce


def test_every_condition_becomes_a_must_guardrail() -> None:
    analyzed = screened(
        "ai-engineer",
        safety=json.loads(
            SafetyClearance(conditions=list(SAFETY_CONDITIONS), prompt_version=1).model_dump_json()
        ),
    )
    spec = enforce(analyzed, good_spec())
    guardrails = {g["id"]: g for g in spec["guardrails"]}
    for condition in SAFETY_CONDITIONS:
        g = guardrails["safety-" + condition.replace("_", "-")]
        assert g["severity"] == "must"
        assert g["category"] == CONDITION_GUARDRAILS[condition][0]
    assert validate_spec(spec).ok


def test_high_risk_domains_get_disclaimer_and_human_review() -> None:
    analyzed = screened("review-nda")
    ids = [g["id"] for g in required_guardrails(analyzed)]
    assert ids == ["safety-professional-disclaimer", "safety-human-review"]
    no_conditions = screened("review-nda", safety={"conditions": [], "prompt_version": 1})
    assert [g["id"] for g in required_guardrails(no_conditions)] == ids  # added regardless


def test_enforce_aligns_identity_and_is_idempotent() -> None:
    analyzed = screened("marketing-strategist", targets=[])
    draft = good_spec()  # an ai-engineer spec: wrong kind/domain/name for this request
    once = enforce(analyzed, draft)
    assert once["skill"]["domain"] == "marketing/strategy"
    assert once["skill"]["name"] == "marketing-strategist"
    assert once["targets"] == ["claude", "codex"]  # default when the analysis has none
    assert enforce(analyzed, once) == once


def test_enforce_replaces_a_model_guardrail_with_the_same_id() -> None:
    analyzed = screened("review-nda")
    draft = good_spec()
    draft["guardrails"].append(
        {"id": "safety-human-review", "rule": "weak", "severity": "should", "category": "general"}
    )
    spec = enforce(analyzed, draft)
    matches = [g for g in spec["guardrails"] if g["id"] == "safety-human-review"]
    assert len(matches) == 1 and matches[0]["severity"] == "must"


async def test_a_taken_name_is_not_forced(fake: FakeGateway) -> None:
    analyzed = screened("ai-engineer")
    spec = enforce(analyzed, good_spec(), existing_names={"ai-engineer"})
    assert spec["skill"]["name"] == "ai-engineer"  # left as the model wrote it, not forced
    await build_spec(analyzed, existing_names={"ai-engineer"})
    assert fake.calls[0].inputs is not None
    assert "already taken" in fake.calls[0].inputs["name_hint"]


# ---------------------------------------------------------------- graph, prompts, privacy


def test_graph_shape() -> None:
    graph = build_graph().get_graph()
    assert {"write", "enforce", "check"} <= set(graph.nodes)
    edges = {(e.source, e.target) for e in graph.edges}
    assert {("write", "enforce"), ("enforce", "check"), ("check", "write")} <= edges


def test_prompts_are_locked_and_the_example_spec_is_valid() -> None:
    assert check_lock(PROMPTS_DIR) == []
    for prompt_id in (GENERATE, REPAIR):
        assert load_prompt(prompt_id).meta.model_role == "architect"
    text = (PROMPTS_DIR / "architect" / "generate.md").read_text(encoding="utf-8")
    example = re.search(r"<example_spec>\n(.*?)\n</example_spec>", text, flags=re.DOTALL)
    assert example is not None
    result = validate_spec(json.loads(example.group(1)))
    assert result.ok and result.issues == ()
    assert result.spec is not None and result.spec.skill.name == "meeting-minutes"


def test_langsmith_tracing_is_off_by_default() -> None:
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"
