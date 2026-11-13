"""AI-21 at the gateway: the fallback chains in models.yaml, the skill budget, the per-call caps
and rate limits. The real gateway runs against the scripted LiteLLM stand-in; no network."""

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import litellm
import pytest

from core.llm import (
    BudgetExceeded,
    FakeGateway,
    Limits,
    LLMInputError,
    LLMUnavailable,
    RoleLimit,
    load_config,
    set_limits,
    skill_run,
)
from core.llm.config import LOCAL_PREFIX
from core.llm.limits import RoleLimiter
from tests.llm.helpers import Greeting
from tests.llm.litellm_mock import (
    DIRECT_SONNET,
    SONNET,
    FakeLiteLLM,
    chat,
    config_with,
    make_gateway,
    provider_error,
)

E = litellm.exceptions
INPUTS = {"name": "Ziad", "platform": "Claude"}
OPUS = "openrouter/anthropic/claude-opus-5.5"


@pytest.fixture(autouse=True)
def _no_limits(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    caplog.set_level(logging.INFO, logger="skillforge.llm")
    previous = set_limits(Limits())
    yield
    set_limits(previous)


def records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "skillforge.llm"]


def real_chain() -> Any:
    """The test config with the analysis role's real chain from models.yaml."""
    return config_with(
        analysis={"fallbacks": load_config().role("analysis").fallbacks, "num_retries": 0}
    )


# ---------------------------------------------------------------- the chains in models.yaml


def test_every_chat_role_has_a_stronger_fallback_and_a_direct_last_hop() -> None:
    config = load_config()
    for name, role in config.roles.items():
        if role.model.startswith(LOCAL_PREFIX):
            assert role.fallbacks == (), name  # embeddings: another model corrupts the index
            continue
        assert len(role.fallbacks) >= 2, name
        price = config.info_for(role.model)["input_cost_per_token"]  # type: ignore[index]
        first = config.info_for(role.fallbacks[0])
        assert first is not None and first["input_cost_per_token"] >= price, name  # never weaker
        assert role.fallbacks[-1].startswith("anthropic/"), name  # the OpenRouter-outage hop
        assert all(config.info_for(m) is not None for m in role.fallbacks), name  # all priced


# ---------------------------------------------------------------- the real gateway


async def test_primary_down_the_fallback_answers_and_it_is_logged(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [provider_error(E.ServiceUnavailableError), chat(model=OPUS)]
    result = await make_gateway(real_chain()).complete("demo/greet", INPUTS, Greeting)
    assert result.tone == "warm"
    recs = records(caplog)
    assert [(r["model"], r["fallback"], r["status"]) for r in recs] == [
        (SONNET, 0, "error"),
        (OPUS, 1, "ok"),
    ]
    assert len({r["call_id"] for r in recs}) == 1


async def test_the_direct_hop_is_skipped_without_its_key(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    llm.completions = [provider_error(E.AuthenticationError)] * 2
    with pytest.raises(LLMUnavailable):
        await make_gateway(real_chain()).complete("demo/greet", INPUTS, Greeting)
    assert [c["model"] for c in llm.calls] == [SONNET, OPUS]  # no request for the direct hop
    last = records(caplog)[-1]
    assert (last["model"], last["fallback"], last["error_type"]) == (
        DIRECT_SONNET,
        2,
        "MissingApiKey",
    )


async def test_the_direct_hop_answers_when_openrouter_is_down(llm: FakeLiteLLM) -> None:
    llm.completions = [provider_error(E.AuthenticationError)] * 2 + [chat(model=DIRECT_SONNET)]
    await make_gateway(real_chain()).complete("demo/greet", INPUTS, Greeting)
    assert [c["model"] for c in llm.calls] == [SONNET, OPUS, DIRECT_SONNET]


async def test_the_budget_stops_the_next_call(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [chat(), chat()]
    gateway = make_gateway()
    with skill_run("job-42", budget_usd=0.0003) as run:  # one call costs $0.0004
        await gateway.complete("demo/greet", INPUTS, Greeting)
        with pytest.raises(BudgetExceeded, match=r"\$0\.00 is used up|budget"):
            await gateway.complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 1 and run.total_usd == pytest.approx(0.0004)
    assert [r["skill_run"] for r in records(caplog)] == ["job-42"]


async def test_spend_from_earlier_steps_counts(llm: FakeLiteLLM) -> None:
    with skill_run("job-1", spent_usd=1.50, budget_usd=1.50), pytest.raises(BudgetExceeded):
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert llm.calls == []


async def test_the_budget_is_checked_before_a_fallback_too(llm: FakeLiteLLM) -> None:
    def costly_failure(kwargs: dict[str, Any]) -> Any:
        raise provider_error(E.ServiceUnavailableError)

    llm.completions = [chat(content="not json"), costly_failure]
    with skill_run(None, budget_usd=0.0003), pytest.raises(BudgetExceeded):
        await make_gateway(real_chain()).complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 1  # the repair attempt was never sent


async def test_caps_on_output_tokens_and_prompt_size(llm: FakeLiteLLM) -> None:
    set_limits(Limits(max_output_tokens=500))
    llm.completions = [chat()]
    await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert llm.calls[0]["max_tokens"] == 500
    set_limits(Limits(max_input_chars=20))
    with pytest.raises(LLMInputError, match="the limit is 20"):
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 1


# ---------------------------------------------------------------- rate limits


async def test_requests_per_minute_wait_then_fail_cleanly() -> None:
    now = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RoleLimiter(RoleLimit(requests_per_minute=2), 90, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        async with limiter.slot("analysis"):
            pass
    assert slept == [60.0]  # the third call waited for the window to move
    short = RoleLimiter(RoleLimit(requests_per_minute=1), 5, clock=lambda: now[0], sleep=sleep)
    async with short.slot("analysis"):
        pass
    with pytest.raises(LLMUnavailable, match="rate limited locally"):
        async with short.slot("analysis"):
            pass


async def test_concurrency_never_exceeds_the_limit() -> None:
    limiter = RoleLimiter(RoleLimit(max_concurrency=2), 5)

    async def work() -> None:
        async with limiter.slot("architect"):
            await asyncio.sleep(0.01)

    await asyncio.gather(*(work() for _ in range(6)))
    assert limiter.peak == 2


async def test_the_gateway_uses_the_role_limits(llm: FakeLiteLLM) -> None:
    set_limits(Limits(roles={"analysis": RoleLimit(max_concurrency=1)}, max_wait_s=5))
    llm.completions = [chat() for _ in range(3)]
    gateway = make_gateway()
    await asyncio.gather(*(gateway.complete("demo/greet", INPUTS, Greeting) for _ in range(3)))
    assert len(llm.calls) == 3


# ---------------------------------------------------------------- the fake gateway


async def test_fake_gateway_walks_the_real_chain(
    fake: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    fake.fail_model(SONNET)
    await fake.complete("demo/greet", INPUTS, Greeting)
    recs = records(caplog)
    assert [(r["model"], r["fallback"], r["status"], r["error_type"]) for r in recs] == [
        (SONNET, 0, "error", "LLMUnavailable"),
        (OPUS, 1, "ok", None),
    ]
    assert len({r["call_id"] for r in recs}) == 1


async def test_fake_gateway_all_links_down(fake: FakeGateway) -> None:
    for model in (SONNET, OPUS, DIRECT_SONNET):
        fake.fail_model(model)
    with pytest.raises(LLMUnavailable, match="all models failed"):
        await fake.complete("demo/greet", INPUTS, Greeting)


async def test_fake_gateway_outage_for_n_calls(
    fake: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    fake.fail_model(SONNET, times=1)
    await fake.complete("demo/greet", INPUTS, Greeting)
    await fake.complete("demo/greet", INPUTS, Greeting)
    assert [r["fallback"] for r in records(caplog) if r["status"] == "ok"] == [1, 0]


async def test_fake_gateway_costs_and_budget(fake: FakeGateway) -> None:
    fake.cost_usd = 0.6
    with skill_run("job-9", budget_usd=1.0) as run:
        await fake.complete("demo/greet", INPUTS, Greeting)
        await fake.complete("demo/greet", INPUTS, Greeting)
        with pytest.raises(BudgetExceeded):
            await fake.complete("demo/greet", INPUTS, Greeting)
    assert run.total_usd == pytest.approx(1.2)  # the in-flight call finished: one overrun
