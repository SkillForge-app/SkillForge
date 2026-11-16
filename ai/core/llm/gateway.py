"""The LLM gateway contract (AI-02, contract A1). Every LLM and embedding call goes through here.

    from core.llm import complete, embed

    result = await complete("analysis/request", {"request_text": text}, AnalyzedRequest)
    vectors = await embed(["first passage", "second passage"])

The backend is chosen by SKILLFORGE_LLM_BACKEND (`litellm` by default, or `fake`), or set
directly with `set_gateway()` in tests.
"""

import asyncio
import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from core.llm.errors import ConfigError, LLMInputError

T = TypeVar("T", bound=BaseModel)

BACKEND_ENV = "SKILLFORGE_LLM_BACKEND"
EMBEDDING_ROLE = "embedding"


class LLMGateway(Protocol):
    async def complete(
        self,
        prompt_id: str,
        inputs: Mapping[str, Any],
        output_model: type[T],
        *,
        model_role: str | None = None,
    ) -> T:
        """Render the prompt, call the model, return a validated `output_model` instance.

        `model_role` overrides the prompt file's `model_role`.
        Raises PromptNotFound, PromptInputError, ConfigError, LLMOutputInvalid, LLMUnavailable.
        """
        ...

    async def embed(
        self, texts: Sequence[str], *, model_role: str = EMBEDDING_ROLE
    ) -> list[list[float]]:
        """One vector per text, same order, each of the role's `dimensions`.

        An empty list returns an empty list. An empty or blank text raises LLMInputError.
        """
        ...


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = _gateway_from_env()
    return _gateway


def set_gateway(gateway: LLMGateway | None) -> LLMGateway | None:
    """Install a gateway and return the previous one. None means: rebuild from env on next use."""
    global _gateway
    previous, _gateway = _gateway, gateway
    return previous


def _gateway_from_env() -> LLMGateway:
    backend = os.environ.get(BACKEND_ENV, "litellm").strip().lower()
    if backend == "fake":
        from core.llm.fake import FakeGateway

        return FakeGateway()
    if backend == "litellm":
        from core.llm.litellm_gateway import LiteLLMGateway

        return LiteLLMGateway()
    raise ConfigError(f"unknown {BACKEND_ENV}={backend!r}; use 'litellm' or 'fake'")


def check_texts(texts: Sequence[str]) -> list[str]:
    """Shared `embed` input rules: returns the texts as a list; blank texts are an error."""
    texts = list(texts)
    blank = [i for i, text in enumerate(texts) if not text.strip()]
    if blank:
        raise LLMInputError(f"cannot embed empty texts (indexes {blank})")
    return texts


async def complete(
    prompt_id: str,
    inputs: Mapping[str, Any],
    output_model: type[T],
    *,
    model_role: str | None = None,
) -> T:
    return await get_gateway().complete(prompt_id, inputs, output_model, model_role=model_role)


async def embed(texts: Sequence[str], *, model_role: str = EMBEDDING_ROLE) -> list[list[float]]:
    return await get_gateway().embed(texts, model_role=model_role)


def complete_sync(
    prompt_id: str,
    inputs: Mapping[str, Any],
    output_model: type[T],
    *,
    model_role: str | None = None,
) -> T:
    """Blocking `complete` for scripts. In notebooks and async code, `await complete(...)`."""
    return asyncio.run(complete(prompt_id, inputs, output_model, model_role=model_role))


def embed_sync(texts: Sequence[str], *, model_role: str = EMBEDDING_ROLE) -> list[list[float]]:
    """Blocking `embed` for scripts. In notebooks and async code, `await embed(...)`."""
    return asyncio.run(embed(texts, model_role=model_role))
