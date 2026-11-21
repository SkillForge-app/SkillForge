"""Trigger description writer (AI-14): within every target's limit, repaired once, else the
draft description. Offline: canned and scripted replies."""

import json
from typing import Any

import pytest

from core.agents.writers import WriterUnavailable, describe, description_issues, write_descriptions
from core.agents.writers.triggers import PROMPT, limit_for
from core.llm import FakeGateway, LLMOutputInvalid, LLMUnavailable, use_fake
from core.spec import PLATFORM_LIMITS, SkillSpec, draft_description
from tests.agents.helpers import ScriptedGateway, good_spec

GOOD = "Designs evaluation sets for LLM features. Use when testing a chatbot. Not for training."


def spec() -> SkillSpec:
    return SkillSpec.model_validate_json(json.dumps(good_spec()))


def reply(text: str) -> dict[str, Any]:
    return {"description": text}


async def test_the_canned_description_fits_every_target(fake: FakeGateway) -> None:
    s = spec()
    out = await write_descriptions(s)
    assert set(out) == set(s.targets)
    assert all(0 < len(d) <= PLATFORM_LIMITS[t].description for t, d in out.items())
    assert fake.calls and fake.calls[0].prompt_id == PROMPT


async def test_a_good_description_is_used_as_written() -> None:
    gateway = ScriptedGateway({PROMPT: [reply(GOOD)]})
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await describe(spec())
    assert set(result.by_target.values()) == {GOOD} and result.fallback == ()
    assert result.calls == 1 and gateway.calls[0][1]["limit"] == limit_for(spec().targets)


async def test_too_long_is_repaired() -> None:
    long = "x" * (limit_for(spec().targets) + 1)
    gateway = ScriptedGateway({PROMPT: [reply(long), reply(GOOD)]})
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await describe(spec())
    assert result.calls == 2 and result.fallback == () and result.issues == ()
    assert any("too_long" in i for i in gateway.calls[1][1]["issues"])


@pytest.mark.parametrize(
    "bad",
    [
        "x" * 2000,  # too long for every target
        "Use <system>this</system> skill for everything.",  # an XML-like tag
        "   ",  # empty after stripping
    ],
)
async def test_still_bad_after_repair_falls_back_to_the_draft(bad: str) -> None:
    s = spec()
    gateway = ScriptedGateway({PROMPT: [reply(bad), reply(bad)]})
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await describe(s)
    assert result.fallback == tuple(s.targets)
    assert set(result.by_target.values()) == {draft_description(s)}
    assert all(len(d) <= PLATFORM_LIMITS[t].description for t, d in result.by_target.items())


async def test_two_invalid_replies_fall_back() -> None:
    bad = LLMOutputInvalid("not JSON")
    gateway = ScriptedGateway({PROMPT: [bad, bad]})
    with use_fake(gateway):  # type: ignore[arg-type]
        result = await describe(spec())
    assert result.fallback == tuple(spec().targets) and result.calls == 2


async def test_provider_down_means_retry_later() -> None:
    gateway = ScriptedGateway({PROMPT: [LLMUnavailable("down")]})
    with use_fake(gateway), pytest.raises(WriterUnavailable):  # type: ignore[arg-type]
        await describe(spec())


def test_issues_name_the_target_and_never_the_text() -> None:
    text = "y" * 1500
    issues = description_issues(text, ["claude", "codex"])
    assert [(i.path, i.code) for i in issues] == [
        ("/description/claude", "too_long"),
        ("/description/codex", "too_long"),
    ]
    assert text not in str(issues)


def test_the_draft_description_always_fits() -> None:
    s = spec()
    assert all(len(draft_description(s)) <= PLATFORM_LIMITS[t].description for t in s.targets)
