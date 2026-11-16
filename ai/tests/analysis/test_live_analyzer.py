"""Live smoke test for the Request Analyzer: 5 dev requests against the real model.

Never runs in the normal test run (pyproject sets -m 'not live'). Run on purpose with
`pytest -m live tests/analysis`. The full measurement is `python -m evaluation.analyzer run --live`.
"""

import os

import pytest
from dotenv import load_dotenv

from core.llm import load_config
from core.llm.config import key_env_for
from evaluation.analyzer.data import ANALYZER_DIR, load_set

pytestmark = pytest.mark.live
_KEY = key_env_for(load_config().role("analysis").model) or "OPENROUTER_API_KEY"
load_dotenv(ANALYZER_DIR.parents[1] / ".env", override=False)


@pytest.mark.skipif(not os.environ.get(_KEY), reason=f"{_KEY} not set")
async def test_live_analyzer_on_five_dev_requests() -> None:
    from core.llm import set_gateway
    from core.llm.litellm_gateway import LiteLLMGateway
    from evaluation.analyzer.evaluate import run_eval

    set_gateway(LiteLLMGateway())
    report, _ = await run_eval({"dev": load_set("dev")[:5]}, live=True)
    metrics = report.sets["dev"]
    assert metrics["errors"] == {}
    assert report.usage["cost_usd"] > 0
