"""Live smoke test for the Skill Architect. Opt-in only: `pytest -m live tests/agents`."""

import os

import pytest
from dotenv import load_dotenv

from core.llm import load_config
from core.llm.config import key_env_for
from evaluation.common import AI_ROOT

pytestmark = pytest.mark.live
_KEY = key_env_for(load_config().role("architect").model) or "OPENROUTER_API_KEY"
load_dotenv(AI_ROOT / ".env", override=False)


@pytest.mark.skipif(not os.environ.get(_KEY), reason=f"{_KEY} not set")
async def test_live_architect_designs_one_example() -> None:
    from core.agents import build_spec
    from core.llm import set_gateway
    from core.llm.litellm_gateway import LiteLLMGateway
    from core.pipeline import example_request

    set_gateway(LiteLLMGateway())
    result = await build_spec(example_request("review-nda"))
    assert result.ok, [str(i) for i in result.issues]
    assert result.spec is not None
    ids = {g.id for g in result.spec.guardrails}
    assert {"safety-professional-disclaimer", "safety-human-review"} <= ids
