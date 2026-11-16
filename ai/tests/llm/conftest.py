from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from core.llm import FakeGateway, load_config, set_gateway, use_fake
from core.llm.prompts import clear_prompt_cache
from tests.llm.helpers import OUTPUTS, PROMPTS

if TYPE_CHECKING:
    from tests.llm.litellm_mock import FakeLiteLLM


@pytest.fixture(autouse=True)
def _fresh_llm_state() -> Iterator[None]:
    clear_prompt_cache()
    load_config.cache_clear()
    yield
    set_gateway(None)
    clear_prompt_cache()
    load_config.cache_clear()


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    with use_fake(FakeGateway(prompts_root=PROMPTS, fixtures_dir=OUTPUTS)) as gateway:
        yield gateway


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> "FakeLiteLLM":
    """Replace litellm.acompletion / aembedding with a scripted fake (see litellm_mock.py).

    Imported lazily so tests that only use the fake gateway do not pay LiteLLM's import time.
    """
    import litellm

    from tests.llm.litellm_mock import FakeLiteLLM

    fake = FakeLiteLLM()
    # Placeholder keys so the gateway's key check passes; the mock never reaches the network.
    for env in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(env, "test-placeholder-not-a-key")
    monkeypatch.setattr(litellm, "acompletion", fake.acompletion)
    monkeypatch.setattr(litellm, "aembedding", fake.aembedding)
    return fake
