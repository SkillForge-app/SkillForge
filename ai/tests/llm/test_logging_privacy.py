"""The LLM layer logs metadata only: never prompt text, inputs, texts, outputs or error messages.

Checked for both backends: the fake, and the real LiteLLM gateway with litellm mocked.
"""

import json
import logging
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from core.llm import CallRecord, FakeGateway, LLMUnavailable, complete, embed, set_gateway
from tests.llm.helpers import Greeting

if TYPE_CHECKING:
    from tests.llm.litellm_mock import FakeLiteLLM

SECRET_INPUT = "SENTINEL-INPUT-7f3a"
SECRET_TEXT = "SENTINEL-EMBED-TEXT-91c2"
SECRET_OUTPUT = "SENTINEL-OUTPUT-4be0"
SECRET_ERROR = "SENTINEL-ERROR-MESSAGE-d81e"
SENTINELS = [SECRET_INPUT, SECRET_TEXT, SECRET_OUTPUT, SECRET_ERROR]
# Words from the fixture prompt template itself must not leak either.
PROMPT_TEXT = "short greetings"

METADATA_FIELDS = {"call_id", "kind", "model_role", "model", "latency_ms", "status"}
INPUTS = {"name": SECRET_INPUT, "platform": SECRET_INPUT}


def llm_calls(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """Check every captured log record (any logger, e.g. LiteLLM's too), return our call logs."""
    for record in caplog.records:
        logged = record.getMessage() + repr(record.__dict__)
        for secret in [*SENTINELS, PROMPT_TEXT]:
            assert secret not in logged, f"{secret} leaked via logger {record.name}"
    calls = []
    for record in caplog.records:
        if record.name == "skillforge.llm" and record.getMessage().startswith("{"):
            call = json.loads(record.getMessage())
            assert call.keys() >= METADATA_FIELDS
            assert record.llm_call == call  # type: ignore[attr-defined]
            calls.append(call)
    return calls


async def test_fake_backend_logs_no_content(
    fake: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake.register("demo/greet", {"greeting": SECRET_OUTPUT, "tone": SECRET_OUTPUT})

    await complete("demo/greet", INPUTS, Greeting)
    await embed([SECRET_TEXT])
    fake.register_error("demo/greet", LLMUnavailable(SECRET_ERROR))
    fake.register_error("embed", LLMUnavailable(SECRET_ERROR))
    with pytest.raises(LLMUnavailable):
        await complete("demo/greet", INPUTS, Greeting)
    with pytest.raises(LLMUnavailable):
        await embed([SECRET_TEXT])

    calls = llm_calls(caplog)
    assert [(c["kind"], c["status"]) for c in calls] == [
        ("complete", "ok"),
        ("embed", "ok"),
        ("complete", "error"),
        ("embed", "error"),
    ]
    assert calls[0]["prompt_id"] == "demo/greet"
    assert calls[0]["prompt_version"] == 1
    assert calls[1]["n_texts"] == 1
    assert calls[2]["error_type"] == "LLMUnavailable"


async def test_litellm_backend_logs_no_content(
    llm: "FakeLiteLLM", caplog: pytest.LogCaptureFixture
) -> None:
    import litellm

    from tests.llm.litellm_mock import chat, config_with, embeddings, make_gateway, provider_error

    caplog.set_level(logging.DEBUG)  # all loggers, including LiteLLM's own
    config = config_with(analysis={"num_retries": 0}, embedding={"num_retries": 0})
    set_gateway(make_gateway(config))
    good = json.dumps({"greeting": SECRET_OUTPUT, "tone": SECRET_OUTPUT})
    auth = litellm.exceptions.AuthenticationError
    llm.completions = [
        chat(f"not json {SECRET_OUTPUT}"),
        chat(good),
        provider_error(auth, SECRET_ERROR),
    ]
    llm.embeddings = [embeddings, provider_error(auth, SECRET_ERROR)]

    await complete("demo/greet", INPUTS, Greeting)  # includes one JSON repair round
    await embed([SECRET_TEXT])
    with pytest.raises(LLMUnavailable) as complete_error:
        await complete("demo/greet", INPUTS, Greeting)
    with pytest.raises(LLMUnavailable) as embed_error:
        await embed([SECRET_TEXT])

    assert SECRET_ERROR not in str(complete_error.value) + str(embed_error.value)
    calls = llm_calls(caplog)
    assert [(c["kind"], c["status"], c["error_type"]) for c in calls] == [
        ("complete", "error", "LLMOutputInvalid"),
        ("complete", "ok", None),
        ("embed", "ok", None),
        ("complete", "error", "AuthenticationError"),
        ("embed", "error", "AuthenticationError"),
    ]
    assert all(c["model"] != "fake" for c in calls)


def test_call_record_rejects_content_fields() -> None:
    with pytest.raises(ValidationError):
        CallRecord(
            call_id="x",
            kind="complete",
            model_role="default",
            model="m",
            latency_ms=1.0,
            status="ok",
            prompt_text="hello",  # type: ignore[call-arg]
        )
