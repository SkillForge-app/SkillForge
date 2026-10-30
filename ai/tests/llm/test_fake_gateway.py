import math

import pytest

from core.llm import (
    ConfigError,
    FakeGateway,
    FakeOutputMissing,
    LLMGateway,
    LLMInputError,
    LLMOutputInvalid,
    LLMUnavailable,
    PromptInputError,
    complete,
    complete_sync,
    embed,
    embed_sync,
    get_gateway,
    set_gateway,
    use_fake,
)
from core.llm.fake import fake_vector
from core.llm.gateway import BACKEND_ENV
from tests.llm.helpers import Greeting

INPUTS = {"name": "Ziad", "platform": "Claude"}


def test_fake_satisfies_the_gateway_protocol() -> None:
    gateway: LLMGateway = FakeGateway()
    assert gateway is not None


# ---------------------------------------------------------------- complete


async def test_registered_dict_is_validated_into_output_model(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi Ziad", "tone": "warm"})
    result = await complete("demo/greet", INPUTS, Greeting)
    assert result == Greeting(greeting="Hi Ziad", tone="warm")


async def test_registered_model_is_returned_as_a_copy(fake: FakeGateway) -> None:
    canned = Greeting(greeting="Hi", tone="warm")
    fake.register("demo/greet", canned)
    first = await complete("demo/greet", INPUTS, Greeting)
    first.greeting = "changed"
    assert (await complete("demo/greet", INPUTS, Greeting)).greeting == "Hi"


async def test_fixture_file_is_used_when_nothing_registered(fake: FakeGateway) -> None:
    result = await complete("demo/greet", INPUTS, Greeting)
    assert result.greeting == "Hello from the fixture file"


async def test_missing_canned_output(fake: FakeGateway) -> None:
    with pytest.raises(FakeOutputMissing, match="demo/user_only"):
        await complete("demo/user_only", {"question": "?"}, Greeting)


async def test_canned_output_not_matching_model_is_output_invalid(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi"})
    with pytest.raises(LLMOutputInvalid):
        await complete("demo/greet", INPUTS, Greeting)


async def test_prompt_errors_surface_through_the_fake(fake: FakeGateway) -> None:
    with pytest.raises(PromptInputError):
        await complete("demo/greet", {"name": "Ziad"}, Greeting)


async def test_calls_are_recorded(fake: FakeGateway) -> None:
    await complete("demo/greet", INPUTS, Greeting)
    [call] = fake.calls
    assert call.kind == "complete"
    assert call.prompt_id == "demo/greet"
    assert call.model_role == "analysis"
    assert call.inputs == INPUTS
    assert call.output_model is Greeting
    assert call.messages is not None
    assert call.messages[1] == {"role": "user", "content": "Say hello to Ziad."}


async def test_model_role_override(fake: FakeGateway) -> None:
    await complete("demo/greet", INPUTS, Greeting, model_role="extraction")
    assert fake.calls[0].model_role == "extraction"
    with pytest.raises(ConfigError, match="unknown model role"):
        await complete("demo/greet", INPUTS, Greeting, model_role="nope")


async def test_registered_error_is_raised_every_time(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi", "tone": "warm"})
    fake.register_error("demo/greet", LLMUnavailable("provider down"))
    for _ in range(3):
        with pytest.raises(LLMUnavailable):
            await complete("demo/greet", INPUTS, Greeting)


async def test_registered_error_with_times_then_answers(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi", "tone": "warm"})
    fake.register_error("demo/greet", LLMOutputInvalid("bad json"), times=2)
    for _ in range(2):
        with pytest.raises(LLMOutputInvalid):
            await complete("demo/greet", INPUTS, Greeting)
    assert (await complete("demo/greet", INPUTS, Greeting)).greeting == "Hi"


def test_register_error_rejects_zero_times(fake: FakeGateway) -> None:
    with pytest.raises(ValueError):
        fake.register_error("demo/greet", LLMUnavailable("x"), times=0)


def test_reset(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi", "tone": "warm"})
    complete_sync("demo/greet", INPUTS, Greeting)
    fake.reset()
    assert fake.calls == []
    assert complete_sync("demo/greet", INPUTS, Greeting).greeting == "Hello from the fixture file"


# ---------------------------------------------------------------- embed


async def test_embed_is_deterministic_normalised_and_ordered(fake: FakeGateway) -> None:
    texts = ["skills for marketing", "skills for data science"]
    first = await embed(texts)
    second = await embed(list(reversed(texts)))
    assert first == list(reversed(second))
    assert all(len(v) == 384 for v in first)
    assert all(math.isclose(math.sqrt(sum(x * x for x in v)), 1.0) for v in first)
    assert first[0] != first[1]


def test_fake_vector_is_stable_across_runs() -> None:
    # Pinned values: a change here means fake vectors moved and stored test data may break.
    assert fake_vector("skillforge", 4) == pytest.approx(
        [0.284195, -0.760941, -0.060405, -0.580132], abs=1e-6
    )
    assert fake_vector("skillforge", 4) != fake_vector("SkillForge", 4)


async def test_embed_dimensions_override_and_empty_list() -> None:
    with use_fake(FakeGateway(dimensions=8)):
        assert len((await embed(["a"]))[0]) == 8
        assert await embed([]) == []


async def test_embed_rejects_blank_texts(fake: FakeGateway) -> None:
    with pytest.raises(LLMInputError, match=r"indexes \[1\]"):
        await embed(["ok", "  "])


async def test_embed_registered_error(fake: FakeGateway) -> None:
    fake.register_error("embed", LLMUnavailable("down"), times=1)
    with pytest.raises(LLMUnavailable):
        await embed(["a"])
    assert len(await embed(["a"])) == 1
    assert [c.kind for c in fake.calls] == ["embed", "embed"]


def test_embed_sync(fake: FakeGateway) -> None:
    assert embed_sync(["a", "b"]) == embed_sync(["a", "b"])


async def test_embed_unknown_role(fake: FakeGateway) -> None:
    with pytest.raises(ConfigError):
        await embed(["a"], model_role="nope")


# ---------------------------------------------------------------- backend selection


def test_env_selects_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV, "fake")
    set_gateway(None)
    assert isinstance(get_gateway(), FakeGateway)


def test_env_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # The litellm (default) backend is covered in test_litellm_gateway.py.
    monkeypatch.setenv(BACKEND_ENV, "nope")
    set_gateway(None)
    with pytest.raises(ConfigError, match="unknown"):
        get_gateway()


def test_use_fake_restores_previous_gateway() -> None:
    outer = FakeGateway()
    set_gateway(outer)
    with use_fake() as inner:
        assert get_gateway() is inner
    assert get_gateway() is outer
