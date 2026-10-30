"""A scripted stand-in for litellm.acompletion / litellm.aembedding (no network, no API key).

Each call pops the next scripted item: a response object (returned), an exception (raised), or
a callable taking the call's kwargs and returning a response. Calls are recorded in `.calls`.
Responses are real LiteLLM objects, so cost is computed by LiteLLM itself.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import litellm

from core.llm import ModelConfig, ModelRole, load_config
from core.llm.litellm_gateway import LiteLLMGateway
from tests.llm.helpers import PROMPTS

SONNET = "openrouter/anthropic/claude-sonnet-5.5"
HAIKU = "openrouter/anthropic/claude-haiku-5.5"
DIRECT_SONNET = "anthropic/claude-sonnet-5-5"  # the commented alternative in models.yaml
EMBEDDING = "openai/text-embedding-3-small"
VALID = json.dumps({"greeting": "Hi Ziad", "tone": "warm"})

Script = list[Any]


class FakeLiteLLM:
    def __init__(self) -> None:
        self.completions: Script = []
        self.embeddings: Script = []
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any) -> Any:
        return self._next(self.completions, kwargs)

    async def aembedding(self, **kwargs: Any) -> Any:
        return self._next(self.embeddings, kwargs)

    def _next(self, script: Script, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        assert script, f"unexpected extra call with model={kwargs.get('model')}"
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(kwargs) if callable(item) else item


def chat(
    content: str = VALID,
    *,
    model: str = SONNET,
    finish: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
) -> Any:
    return litellm.ModelResponse(
        model=model.split("/", 1)[-1],
        choices=[
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content},
            }
        ],
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )


def embeddings(kwargs: dict[str, Any], *, size: int | None = None) -> Any:
    """Vector i starts with len(text i); items come back in reverse order to test sorting."""
    texts = kwargs["input"]
    dims = size or kwargs["dimensions"]
    data = [
        {"object": "embedding", "index": i, "embedding": [float(len(t))] + [0.0] * (dims - 1)}
        for i, t in enumerate(texts)
    ]
    return litellm.EmbeddingResponse(
        model="text-embedding-3-small",
        data=list(reversed(data)),
        usage={"prompt_tokens": 10 * len(texts), "total_tokens": 10 * len(texts)},
    )


def provider_error(cls: type[Exception], message: str = "provider said no") -> Exception:
    error: Callable[..., Exception] = cls
    if cls is litellm.exceptions.PermissionDeniedError:  # the only one that needs a response
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(403, request=request)
        return error(message=message, model="m", llm_provider="anthropic", response=response)
    return error(message=message, model="m", llm_provider="anthropic")


# These tests cover the LiteLLM path, so their embedding role is the hosted model; the local
# model path is tested in test_local_embed.py.
HOSTED_EMBEDDING = ModelRole(model=EMBEDDING, dimensions=384, timeout_s=30, num_retries=2)


def base_config() -> ModelConfig:
    """models.yaml, with the hosted embedding role in place of the local one and no fallbacks
    (a test that needs a chain sets it with config_with; tests/ops checks the real chains)."""
    config = load_config()
    roles = {name: role.model_copy(update={"fallbacks": ()}) for name, role in config.roles.items()}
    return config.model_copy(update={"roles": {**roles, "embedding": HOSTED_EMBEDDING}})


def config_with(**roles: dict[str, Any]) -> ModelConfig:
    """The test base config with some role fields changed."""
    base = base_config()
    changed: dict[str, ModelRole] = dict(base.roles)
    for name, update in roles.items():
        changed[name] = base.role(name).model_copy(update=update)
    return base.model_copy(update={"roles": changed})


def make_gateway(config: ModelConfig | None = None, **kwargs: Any) -> LiteLLMGateway:
    return LiteLLMGateway(
        config=config or base_config(),
        prompts_root=PROMPTS,
        backoff_s=0,
        env_file=None,
        **kwargs,
    )
