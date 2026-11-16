"""LiteLLMGateway against a mocked litellm: request shape, retries, fallbacks, repair, cost."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import litellm
import pytest

from core.llm import (
    ConfigError,
    LLMInputError,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
    get_gateway,
    load_config,
    set_gateway,
)
from core.llm.gateway import BACKEND_ENV
from core.llm.litellm_gateway import LITELLM_LOGGERS, LiteLLMGateway
from tests.llm.helpers import Greeting
from tests.llm.litellm_mock import (
    DIRECT_SONNET,
    EMBEDDING,
    HAIKU,
    SONNET,
    VALID,
    FakeLiteLLM,
    chat,
    config_with,
    embeddings,
    make_gateway,
    provider_error,
)

E = litellm.exceptions
INPUTS = {"name": "Ziad", "platform": "Claude"}


def records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "skillforge.llm"]


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="skillforge.llm")


# ---------------------------------------------------------------- normal calls


async def test_success_request_shape_and_cost(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [chat(prompt_tokens=100, completion_tokens=20)]
    result = await make_gateway().complete("demo/greet", INPUTS, Greeting)

    assert result == Greeting(greeting="Hi Ziad", tone="warm")
    [args] = llm.calls
    assert args["model"] == SONNET
    assert args["response_format"] is Greeting
    assert args["timeout"] == 120
    assert args["max_tokens"] == 16000
    assert args["num_retries"] == 0  # we retry ourselves, so every attempt is logged
    assert "temperature" not in args  # Claude 5.5 rejects non-default temperature
    assert "reasoning_effort" not in args
    assert args["messages"][1] == {"role": "user", "content": "Say hello to Ziad."}

    [rec] = records(caplog)
    assert rec["status"] == "ok"
    assert (rec["model"], rec["model_role"], rec["attempt"]) == (SONNET, "analysis", 1)
    assert (rec["input_tokens"], rec["output_tokens"]) == (100, 20)
    assert rec["cost_usd"] == pytest.approx(100 * 2e-6 + 20 * 1e-5)  # Sonnet 5.5: $2 / $10
    assert rec["finish_reason"] == "stop"
    assert (rec["prompt_id"], rec["prompt_version"]) == ("demo/greet", 1)


async def test_haiku_price_from_model_info(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [chat(model=HAIKU, prompt_tokens=1000, completion_tokens=200)]
    await make_gateway().complete("demo/greet", INPUTS, Greeting, model_role="extraction")
    assert llm.calls[0]["model"] == HAIKU
    assert records(caplog)[0]["cost_usd"] == pytest.approx(1000 * 1e-7 + 200 * 5e-7)


async def test_env_override_and_optional_role_params(
    llm: FakeLiteLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLFORGE_MODEL_ANALYSIS", HAIKU)
    load_config.cache_clear()
    llm.completions = [chat(model=HAIKU)]
    await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert llm.calls[0]["model"] == HAIKU

    llm.completions = [chat()]
    config = config_with(analysis={"model": SONNET, "reasoning_effort": "low", "temperature": 1.0})
    await make_gateway(config).complete("demo/greet", INPUTS, Greeting)
    assert (llm.calls[1]["reasoning_effort"], llm.calls[1]["temperature"]) == ("low", 1.0)


async def test_code_fenced_json_is_accepted(llm: FakeLiteLLM) -> None:
    llm.completions = [chat(f"```json\n{VALID}\n```")]
    assert (await make_gateway().complete("demo/greet", INPUTS, Greeting)).tone == "warm"


# ---------------------------------------------------------------- output problems


async def test_invalid_json_is_repaired_once(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [chat("Sure! Here is a greeting."), chat(VALID)]
    result = await make_gateway().complete("demo/greet", INPUTS, Greeting)

    assert result.greeting == "Hi Ziad"
    first, second = llm.calls
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][-2] == {"role": "assistant", "content": "Sure! Here is a greeting."}
    assert "did not match the required JSON schema" in second["messages"][-1]["content"]
    bad, good = records(caplog)
    assert (bad["status"], bad["error_type"], bad["attempt"]) == ("error", "LLMOutputInvalid", 1)
    assert bad["cost_usd"] > 0  # we paid for the bad reply, so it is counted
    assert (good["status"], good["attempt"]) == ("ok", 2)
    assert bad["call_id"] == good["call_id"]


async def test_invalid_json_twice_raises(llm: FakeLiteLLM) -> None:
    llm.completions = [chat("nope"), chat(json.dumps({"greeting": 1}))]
    with pytest.raises(LLMOutputInvalid, match="after one repair attempt"):
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 2


async def test_truncated_reply_fails_without_retry(llm: FakeLiteLLM) -> None:
    llm.completions = [chat('{"greeting": "Hi', finish="length")]
    with pytest.raises(LLMOutputInvalid, match="cut off at max_tokens") as info:
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert not isinstance(info.value, LLMRefused)
    assert len(llm.calls) == 1


# ---------------------------------------------------------------- refusals


async def test_refusal_without_fallback(llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture) -> None:
    llm.completions = [chat("", finish="content_filter")]
    with pytest.raises(LLMRefused) as info:
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert isinstance(info.value, LLMOutputInvalid)  # existing handlers keep working
    assert len(llm.calls) == 1  # a refusal is not retried on the same model
    [rec] = records(caplog)
    assert (rec["error_type"], rec["finish_reason"]) == ("LLMRefused", "content_filter")


async def test_refusal_moves_to_fallback(llm: FakeLiteLLM) -> None:
    config = config_with(analysis={"fallbacks": (HAIKU,)})
    llm.completions = [chat("", finish="content_filter"), chat(model=HAIKU)]
    assert (await make_gateway(config).complete("demo/greet", INPUTS, Greeting)).tone == "warm"
    assert [c["model"] for c in llm.calls] == [SONNET, HAIKU]


async def test_content_policy_errors_everywhere_is_a_refusal(llm: FakeLiteLLM) -> None:
    config = config_with(analysis={"fallbacks": (HAIKU,)})
    llm.completions = [provider_error(E.ContentPolicyViolationError)] * 2
    with pytest.raises(LLMRefused):
        await make_gateway(config).complete("demo/greet", INPUTS, Greeting)


# ---------------------------------------------------------------- provider errors


async def test_timeout_is_retried_then_succeeds(
    llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture
) -> None:
    llm.completions = [provider_error(E.Timeout), provider_error(E.Timeout), chat()]
    await make_gateway().complete("demo/greet", INPUTS, Greeting)
    recs = records(caplog)
    assert [(r["attempt"], r["status"], r["error_type"]) for r in recs] == [
        (1, "error", "Timeout"),
        (2, "error", "Timeout"),
        (3, "ok", None),
    ]
    assert len({r["call_id"] for r in recs}) == 1


async def test_rate_limit_exhausts_retries_then_falls_back(llm: FakeLiteLLM) -> None:
    config = config_with(analysis={"num_retries": 1, "fallbacks": (HAIKU,)})
    llm.completions = [provider_error(E.RateLimitError)] * 2 + [chat(model=HAIKU)]
    await make_gateway(config).complete("demo/greet", INPUTS, Greeting)
    assert [c["model"] for c in llm.calls] == [SONNET, SONNET, HAIKU]


async def test_5xx_api_error_is_retried(llm: FakeLiteLLM) -> None:
    error = E.APIError(status_code=503, message="busy", llm_provider="anthropic", model="m")
    llm.completions = [error, chat()]
    await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 2


@pytest.mark.parametrize(
    "error", [E.AuthenticationError, E.BadRequestError, E.NotFoundError, E.PermissionDeniedError]
)
async def test_non_transient_errors_skip_to_fallback(
    llm: FakeLiteLLM, error: type[Exception]
) -> None:
    config = config_with(analysis={"num_retries": 3, "fallbacks": (HAIKU,)})
    llm.completions = [provider_error(error), chat(model=HAIKU)]
    await make_gateway(config).complete("demo/greet", INPUTS, Greeting)
    assert [c["model"] for c in llm.calls] == [SONNET, HAIKU]


async def test_all_models_fail(llm: FakeLiteLLM) -> None:
    config = config_with(analysis={"num_retries": 0, "fallbacks": (HAIKU,)})
    secret = "SENTINEL-PROVIDER-MESSAGE-5a1c"
    llm.completions = [
        provider_error(E.ServiceUnavailableError, secret),
        provider_error(E.AuthenticationError, secret),
    ]
    with pytest.raises(LLMUnavailable) as info:
        await make_gateway(config).complete("demo/greet", INPUTS, Greeting)
    message = str(info.value)
    assert secret not in message  # provider text can echo the prompt
    assert "AuthenticationError" in message and SONNET in message and HAIKU in message
    assert isinstance(info.value.__cause__, E.AuthenticationError)  # kept for debugging


async def test_programming_errors_are_not_retried(llm: FakeLiteLLM) -> None:
    llm.completions = [TypeError("bad kwarg")]
    with pytest.raises(TypeError):
        await make_gateway().complete("demo/greet", INPUTS, Greeting)
    assert len(llm.calls) == 1


def test_backoff_grows_and_is_capped() -> None:
    gateway = LiteLLMGateway(backoff_s=1.0, max_backoff_s=4.0, env_file=None)
    assert 0.5 <= gateway._backoff(1) <= 1.0
    assert 1.0 <= gateway._backoff(2) <= 2.0
    assert 2.0 <= gateway._backoff(10) <= 4.0


# ---------------------------------------------------------------- embeddings


async def test_embed_batches_keep_order(llm: FakeLiteLLM, caplog: pytest.LogCaptureFixture) -> None:
    llm.embeddings = [embeddings] * 3
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = await make_gateway(embed_batch_size=2).embed(texts)

    assert [v[0] for v in vectors] == [1, 2, 3, 4, 5]
    assert all(len(v) == 384 for v in vectors)
    assert [c["input"] for c in llm.calls] == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert all(c["model"] == EMBEDDING and c["dimensions"] == 384 for c in llm.calls)
    recs = records(caplog)
    assert [r["n_texts"] for r in recs] == [2, 2, 1]
    assert all(r["kind"] == "embed" and r["cost_usd"] > 0 for r in recs)
    assert len({r["call_id"] for r in recs}) == 1


async def test_embed_wrong_dimensions(llm: FakeLiteLLM) -> None:
    llm.embeddings = [lambda kwargs: embeddings(kwargs, size=1536)]
    with pytest.raises(LLMOutputInvalid, match="expected 1 of 384"):
        await make_gateway().embed(["a"])


async def test_embed_retries_transient_errors(llm: FakeLiteLLM) -> None:
    llm.embeddings = [provider_error(E.Timeout), embeddings]
    assert len(await make_gateway().embed(["a"])) == 1
    assert len(llm.calls) == 2


async def test_embed_input_and_role_checks(llm: FakeLiteLLM) -> None:
    gateway = make_gateway()
    assert await gateway.embed([]) == []
    with pytest.raises(LLMInputError):
        await gateway.embed(["ok", " "])
    with pytest.raises(ConfigError, match="no `dimensions`"):
        await gateway.embed(["a"], model_role="analysis")
    assert llm.calls == []


# ---------------------------------------------------------------- config and startup


def test_embedding_role_cannot_have_fallbacks(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(
        "roles:\n  embedding:\n    model: openai/a\n    dimensions: 8\n    fallbacks: [openai/b]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="cannot have fallbacks"):
        load_config(path)


def test_startup_registers_model_info_and_privacy_settings() -> None:
    LiteLLMGateway(env_file=None)
    info = litellm.get_model_info(HAIKU)
    assert (info["input_cost_per_token"], info["output_cost_per_token"]) == (1e-7, 5e-7)
    assert litellm.get_model_info(SONNET)["supports_response_schema"] is True
    assert litellm.get_model_info(DIRECT_SONNET)["supports_native_structured_output"] is True
    assert litellm.turn_off_message_logging is True
    assert all(logging.getLogger(name).level == logging.WARNING for name in LITELLM_LOGGERS)


def test_litellm_builds_a_valid_claude_request() -> None:
    """Checks the request LiteLLM would send for our registered Sonnet 5.5 (no network).

    Native structured output, no forced tool call, and no temperature: Claude 5.5 rejects
    the last two. Re-run after every LiteLLM upgrade; it reads LiteLLM internals on purpose.
    """
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    LiteLLMGateway(env_file=None)
    params = litellm.get_optional_params(
        model="claude-sonnet-5-5",
        custom_llm_provider="anthropic",
        response_format=Greeting,
        max_tokens=16000,
    )
    body = AnthropicConfig().transform_request(
        model="claude-sonnet-5-5",
        messages=[{"role": "user", "content": "hi"}],
        optional_params=params,
        litellm_params={},
        headers={},
    )
    assert body["output_format"]["type"] == "json_schema"
    assert "tool_choice" not in body and "tools" not in body
    assert "temperature" not in body
    with pytest.raises(E.UnsupportedParamsError):
        litellm.get_optional_params(
            model="claude-sonnet-5-5", custom_llm_provider="anthropic", temperature=0.2
        )


def test_openrouter_request_carries_the_schema_and_no_temperature() -> None:
    """What LiteLLM sends to OpenRouter for our roles: a JSON schema, no sampling params."""
    LiteLLMGateway(env_file=None)
    params = litellm.get_optional_params(
        model=SONNET.split("/", 1)[1],
        custom_llm_provider="openrouter",
        response_format=Greeting,
        max_tokens=16000,
    )
    assert params["response_format"]["type"] == "json_schema"
    assert "temperature" not in params and "top_p" not in params


def test_cost_for_openrouter_and_direct_names() -> None:
    gateway = LiteLLMGateway(env_file=None)
    for model, expected in ((SONNET, 0.004), (HAIKU, 0.0002), (DIRECT_SONNET, 0.004)):
        response = chat(model=model, prompt_tokens=1000, completion_tokens=200)
        assert gateway._cost(response, model) == pytest.approx(expected), model


def test_cost_reported_by_openrouter_wins() -> None:
    response = chat(model=SONNET, prompt_tokens=1000, completion_tokens=200)
    response._hidden_params["additional_headers"] = {"llm_provider-x-litellm-response-cost": 0.0123}
    assert LiteLLMGateway(env_file=None)._cost(response, SONNET) == 0.0123


def test_a_zero_price_for_a_paid_call_is_reported_as_unknown() -> None:
    model = "openrouter/vendor/unknown-model"
    assert LiteLLMGateway(env_file=None)._cost(chat(model=model), model) is None


def test_env_file_is_loaded_without_overriding_real_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("SKILLFORGE_TEST_FROM_FILE=file\nSKILLFORGE_TEST_REAL=file\n", encoding="utf-8")
    monkeypatch.delenv("SKILLFORGE_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("SKILLFORGE_TEST_REAL", "real")
    LiteLLMGateway(env_file=env)
    assert os.environ["SKILLFORGE_TEST_FROM_FILE"] == "file"
    assert os.environ["SKILLFORGE_TEST_REAL"] == "real"


@pytest.mark.parametrize("value", [None, "litellm", " LiteLLM "])
def test_default_backend_is_litellm(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(BACKEND_ENV, raising=False)
    else:
        monkeypatch.setenv(BACKEND_ENV, value)
    set_gateway(None)
    assert isinstance(get_gateway(), LiteLLMGateway)


async def test_no_key_fails_before_any_network_call(
    llm: FakeLiteLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing key is caught by the gateway itself: LiteLLM is never called."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = config_with(analysis={"num_retries": 0})
    with pytest.raises(LLMUnavailable, match="MissingApiKey"):
        await make_gateway(config).complete("demo/greet", INPUTS, Greeting)
    assert llm.calls == []
