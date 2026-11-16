"""Live smoke tests against real providers. They spend a few cents.

They never run in the normal test run (pyproject sets `-m 'not live'`). Run them on purpose:

    .venv/Scripts/python -m pytest -m live -v

Each test is also skipped when its provider key is missing (env var or ai/.env).
"""

import json
import logging
import os

import pytest
from dotenv import load_dotenv

from core.llm import load_config, track_usage
from core.llm.config import key_env_for
from tests.llm.helpers import PROMPTS, Greeting

pytestmark = pytest.mark.live
_KEY = key_env_for(load_config().role("analysis").model) or "OPENROUTER_API_KEY"

load_dotenv(PROMPTS.parents[3] / ".env", override=False)  # ai/.env


@pytest.mark.skipif(not os.environ.get(_KEY), reason=f"{_KEY} not set")
async def test_live_complete_logs_model_tokens_and_cost(caplog: pytest.LogCaptureFixture) -> None:
    from core.llm.litellm_gateway import LiteLLMGateway

    caplog.set_level(logging.INFO, logger="skillforge.llm")
    gateway = LiteLLMGateway(prompts_root=PROMPTS)
    with track_usage() as usage:
        result = await gateway.complete(
            "demo/greet", {"name": "Ziad", "platform": "Claude"}, Greeting
        )

    assert result.greeting
    calls = [json.loads(r.getMessage()) for r in caplog.records if r.name == "skillforge.llm"]
    ok = [c for c in calls if c["status"] == "ok"]
    assert len(ok) == 1
    assert ok[0]["model"] == load_config().role("analysis").model
    assert ok[0]["input_tokens"] > 0 and ok[0]["output_tokens"] > 0
    assert ok[0]["cost_usd"] > 0  # AI-02 done-when: model, tokens and cost on every call
    assert usage.cost_usd == pytest.approx(sum(c["cost_usd"] or 0 for c in calls))


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_live_embed_returns_vectors_of_the_configured_size() -> None:
    from core.llm.litellm_gateway import LiteLLMGateway

    vectors = await LiteLLMGateway().embed(["skills for marketing", "skills for data science"])
    assert [len(v) for v in vectors] == [384, 384]
    assert vectors[0] != vectors[1]
