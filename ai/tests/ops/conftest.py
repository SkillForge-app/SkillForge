from collections.abc import Iterator

import pytest

from core.llm import FakeGateway, Limits, load_config, set_gateway, set_limits, use_fake
from core.llm.prompts import clear_prompt_cache
from core.ops.events import set_sample_rate
from core.ops.settings import BACKEND_VARS, BRAVE_KEY_ENV, ENV_VAR, PGVECTOR_DSN_ENV

KEYS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", BRAVE_KEY_ENV)


@pytest.fixture(autouse=True)
def _clean_ops_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No profile, limits, sample rate, backend variables or keys leak in or out of a test."""
    for var in (ENV_VAR, PGVECTOR_DSN_ENV, *BACKEND_VARS, *KEYS):
        monkeypatch.delenv(var, raising=False)
    clear_prompt_cache()
    load_config.cache_clear()
    previous = set_limits(Limits())
    set_sample_rate(0.0)
    yield
    set_limits(previous)
    set_sample_rate(0.0)
    set_gateway(None)
    load_config.cache_clear()


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    with use_fake(FakeGateway()) as gateway:
        yield gateway
