from collections.abc import Iterator

import pytest

from core.llm import FakeGateway, load_config, set_gateway, use_fake
from core.llm.prompts import clear_prompt_cache


@pytest.fixture(autouse=True)
def _fresh_state() -> Iterator[None]:
    clear_prompt_cache()
    load_config.cache_clear()
    yield
    set_gateway(None)


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    """The real prompt files and the default fixtures (tests/fixtures/llm/)."""
    with use_fake(FakeGateway()) as gateway:
        yield gateway
