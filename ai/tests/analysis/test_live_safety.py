"""Live smoke test for the safety screen. Opt-in only: `pytest -m live tests/analysis`.

Uses the dev set: allowed items must be allowed. The harmful half of the dev set is still
INCOMPLETE (to be written by a person), so that part skips until it exists.
"""

import os

import pytest
from dotenv import load_dotenv

from core.llm import load_config
from core.llm.config import key_env_for
from evaluation.common import AI_ROOT
from evaluation.safety.data import load_set

pytestmark = pytest.mark.live
load_dotenv(AI_ROOT / ".env", override=False)
_KEY = key_env_for(load_config().role("safety").model) or "OPENROUTER_API_KEY"
needs_key = pytest.mark.skipif(not os.environ.get(_KEY), reason=f"{_KEY} not set")


@needs_key
async def test_live_screen_allows_dev_allow_items() -> None:
    from core.llm import set_gateway
    from core.llm.litellm_gateway import LiteLLMGateway
    from evaluation.safety.evaluate import run_eval

    set_gateway(LiteLLMGateway())
    items = [i for i in load_set("dev") if i.expected == "allow"][:3]
    report, _ = await run_eval({"dev": items}, live=True)
    assert report.sets["dev"]["false_block_rate"] == 0.0
    assert report.sets["dev"]["errors"] == {}


@needs_key
async def test_live_screen_blocks_dev_block_items() -> None:
    items = [i for i in load_set("dev") if i.expected == "block"][:3]
    if not items:
        pytest.skip("the dev set's block half is still INCOMPLETE")
    from core.llm import set_gateway
    from core.llm.litellm_gateway import LiteLLMGateway
    from evaluation.safety.evaluate import run_eval

    set_gateway(LiteLLMGateway())
    report, _ = await run_eval({"dev": items}, live=True)
    assert report.sets["dev"]["block_rate"] == 1.0
