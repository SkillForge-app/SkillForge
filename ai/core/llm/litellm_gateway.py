"""LiteLLMGateway: the real LLMGateway (AI-02), calling providers through LiteLLM.

What one `complete` call does:
- Render the prompt, resolve the model role, then try `[role.model, *role.fallbacks]` in order.
- Transient errors (timeout, rate limit, connection, 5xx) are retried on the same model with
  exponential backoff, `role.num_retries` times. Other provider errors (auth, bad request,
  not found) skip straight to the next fallback. When every model failed: LLMUnavailable.
- A refusal moves to the next fallback; if all refuse: LLMRefused. A reply cut off at
  max_tokens raises LLMOutputInvalid at once.
- A reply that does not validate against `output_model` gets one repair attempt (the bad reply
  and the validation errors are sent back); if that fails too: LLMOutputInvalid.
- Every attempt is logged as one CallRecord (metadata only), sharing the call's call_id.

LiteLLM's own retries are switched off (num_retries=0) so every attempt is visible and costed.
"""

import asyncio
import logging
import os
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

# Use the price map bundled with the pinned LiteLLM instead of downloading it on import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
import openai  # noqa: E402  (LiteLLM's errors subclass the openai SDK's error classes)
from dotenv import load_dotenv  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from core.llm.config import (  # noqa: E402
    LOCAL_PREFIX,
    ModelConfig,
    ModelRole,
    key_env_for,
    load_config,
)
from core.llm.errors import (  # noqa: E402
    ConfigError,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
)
from core.llm.gateway import EMBEDDING_ROLE, check_texts  # noqa: E402
from core.llm.limits import capped_max_tokens, check_input_size, limiter  # noqa: E402
from core.llm.local_embed import embed_local  # noqa: E402
from core.llm.prompts import Message, load_prompt  # noqa: E402
from core.llm.usage import (  # noqa: E402
    CallRecord,
    check_budget,
    current_skill_id,
    log_call,
    new_call_id,
)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
REFUSAL_FINISH_REASONS = frozenset({"content_filter", "refusal"})
LITELLM_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy")

_E = litellm.exceptions
RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    _E.Timeout,
    _E.RateLimitError,
    _E.APIConnectionError,
    _E.ServiceUnavailableError,
    _E.InternalServerError,
    _E.BadGatewayError,
)

logger = logging.getLogger("skillforge.llm")
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def configure_litellm(config: ModelConfig) -> None:
    """Process-wide LiteLLM settings: privacy first, then our model-map entries."""
    litellm.turn_off_message_logging = True  # callbacks never see prompt or output text
    litellm.suppress_debug_info = True
    for name in LITELLM_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)  # LiteLLM debug logs include prompts
    if config.model_info:
        litellm.register_model(config.model_info)


class MissingApiKey(Exception):
    """No API key is set for this model's provider: fail before making any network call."""


def _require_key(model: str) -> None:
    env = key_env_for(model)
    if env and not os.environ.get(env):
        raise MissingApiKey(f"{env} is not set")


class _TryNextModel(Exception):
    """The model answered but refused: move to the next fallback without retrying."""


class _BadOutput(Exception):
    """The reply did not validate; carries what the repair attempt needs."""

    def __init__(self, reply: str, error: ValidationError) -> None:
        super().__init__("reply did not validate")
        self.reply = reply
        self.error = error


@dataclass
class _Call:
    """State shared by every attempt of one logical call."""

    role_name: str
    role: ModelRole
    fields: dict[str, Any]
    call_id: str = field(default_factory=new_call_id)
    attempts: int = 0
    chain: tuple[str, ...] = ()  # the models tried in order: the role's model, then fallbacks

    def record(self, model: str, start: float, error: str | None = None, **metrics: Any) -> None:
        log_call(
            CallRecord(
                call_id=self.call_id,
                model_role=self.role_name,
                model=model,
                attempt=self.attempts,
                fallback=self.chain.index(model) if model in self.chain else 0,
                skill_run=current_skill_id(),
                latency_ms=(time.perf_counter() - start) * 1000,
                status="error" if error else "ok",
                error_type=error,
                **self.fields,
                **metrics,
            )
        )


class LiteLLMGateway:
    def __init__(
        self,
        *,
        config: ModelConfig | None = None,
        prompts_root: Path | None = None,
        backoff_s: float = 1.0,
        max_backoff_s: float = 20.0,
        embed_batch_size: int = 128,
        env_file: Path | None = ENV_FILE,
    ) -> None:
        if env_file is not None and env_file.exists():
            load_dotenv(env_file, override=False)  # real env vars win over .env
        self.config = config or load_config()
        self.prompts_root = prompts_root
        self.backoff_s = backoff_s
        self.max_backoff_s = max_backoff_s
        self.embed_batch_size = embed_batch_size
        self._unpriced: set[str] = set()
        configure_litellm(self.config)

    # ------------------------------------------------------------------ complete

    async def complete(
        self,
        prompt_id: str,
        inputs: Mapping[str, Any],
        output_model: type[T],
        *,
        model_role: str | None = None,
    ) -> T:
        prompt = load_prompt(prompt_id, self.prompts_root)
        messages = prompt.render(inputs)
        check_input_size(prompt_id, sum(len(str(m["content"])) for m in messages))
        role_name = model_role or prompt.meta.model_role
        call = _Call(
            role_name=role_name,
            role=self.config.role(role_name),
            fields={"kind": "complete", "prompt_id": prompt_id, "prompt_version": prompt.version},
        )
        try:
            return await self._complete_once(call, messages, output_model)
        except _BadOutput as bad:
            repair = [
                *messages,
                {"role": "assistant", "content": bad.reply},
                {"role": "user", "content": _repair_instruction(bad.error)},
            ]
        try:
            return await self._complete_once(call, repair, output_model)
        except _BadOutput as bad:
            raise LLMOutputInvalid(
                f"{prompt_id}: output did not match {output_model.__name__} "
                "after one repair attempt"
            ) from bad.error

    async def _complete_once(
        self, call: _Call, messages: list[Message], output_model: type[T]
    ) -> T:
        async def attempt(model: str) -> T:
            start = time.perf_counter()
            try:
                _require_key(model)
                response = await litellm.acompletion(
                    **_completion_args(call.role, model, messages, output_model)
                )
            except Exception as exc:
                call.record(model, start, error=type(exc).__name__)
                raise
            choice = response.choices[0]
            metrics = self._metrics(response, model)
            metrics["finish_reason"] = finish = choice.finish_reason
            if finish in REFUSAL_FINISH_REASONS:
                call.record(model, start, error=LLMRefused.__name__, **metrics)
                raise _TryNextModel(model)
            if finish == "length":
                call.record(model, start, error=LLMOutputInvalid.__name__, **metrics)
                raise LLMOutputInvalid(
                    f"{call.fields['prompt_id']}: reply cut off at max_tokens="
                    f"{capped_max_tokens(call.role.max_tokens)} on {model}"
                )
            reply = choice.message.content or ""
            try:
                result = output_model.model_validate_json(_strip_fences(reply))
            except ValidationError as exc:
                call.record(model, start, error=LLMOutputInvalid.__name__, **metrics)
                raise _BadOutput(reply, exc) from None
            call.record(model, start, **metrics)
            return result

        return await self._with_retries(call, [call.role.model, *call.role.fallbacks], attempt)

    # ------------------------------------------------------------------ embed

    async def embed(
        self, texts: Sequence[str], *, model_role: str = EMBEDDING_ROLE
    ) -> list[list[float]]:
        texts = check_texts(texts)
        role = self.config.role(model_role)
        if role.dimensions is None:
            raise ConfigError(f"role {model_role!r} has no `dimensions`; it cannot embed")
        if not texts:
            return []
        call = _Call(role_name=model_role, role=role, fields={"kind": "embed"})
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.embed_batch_size):
            batch = texts[i : i + self.embed_batch_size]
            vectors += await self._embed_batch(call, batch, role.dimensions)
        return vectors

    async def _embed_batch(
        self, call: _Call, batch: list[str], dimensions: int
    ) -> list[list[float]]:
        async def attempt(model: str) -> list[list[float]]:
            start = time.perf_counter()
            metrics: dict[str, Any] = {"n_texts": len(batch)}
            try:
                if model.startswith(LOCAL_PREFIX) and call.role.local is not None:
                    # In-process model (AI-11): no key, no network once downloaded, no cost.
                    vectors = await asyncio.to_thread(embed_local, model, call.role.local, batch)
                    metrics["cost_usd"] = 0.0
                else:
                    _require_key(model)
                    response = await litellm.aembedding(
                        model=model,
                        input=batch,
                        dimensions=dimensions,
                        timeout=call.role.timeout_s,
                        num_retries=0,
                    )
                    metrics |= self._metrics(response, model)
                    items = sorted(response.data, key=lambda item: _field(item, "index"))
                    vectors = [list(_field(item, "embedding")) for item in items]
            except Exception as exc:
                call.record(model, start, error=type(exc).__name__, **metrics)
                raise
            if len(vectors) != len(batch) or any(len(v) != dimensions for v in vectors):
                call.record(model, start, error=LLMOutputInvalid.__name__, **metrics)
                raise LLMOutputInvalid(
                    f"{model} returned {len(vectors)} vectors of sizes "
                    f"{sorted({len(v) for v in vectors})}; expected {len(batch)} of {dimensions}"
                )
            call.record(model, start, **metrics)
            return vectors

        return await self._with_retries(call, [call.role.model], attempt)

    # ------------------------------------------------------------------ shared

    async def _with_retries(
        self, call: _Call, models: list[str], attempt: Callable[[str], Awaitable[R]]
    ) -> R:
        """Try each model in order; retry transient errors on the same model with backoff.

        Before every attempt the skill's cost budget is checked (BudgetExceeded) and the role's
        rate limit takes a slot (LLMUnavailable when none frees up in time)."""
        last: Exception | None = None
        refused = False
        call.chain = tuple(models)
        for model in models:
            for retry in range(call.role.num_retries + 1):
                if retry:
                    await asyncio.sleep(self._backoff(retry))
                check_budget()
                call.attempts += 1
                try:
                    async with limiter(call.role_name).slot(call.role_name):
                        return await attempt(model)
                except _TryNextModel as exc:
                    last, refused = exc, True
                    break
                except Exception as exc:
                    action = _classify(exc)
                    if action is None:
                        raise
                    last = exc
                    refused = isinstance(exc, _E.ContentPolicyViolationError)
                    if action == "next_model":
                        break
        if refused:
            raise LLMRefused(f"role {call.role_name}: every model refused") from last
        raise LLMUnavailable(
            f"role {call.role_name}: all models failed ({', '.join(models)}); "
            f"last error {type(last).__name__}"
        ) from last

    def _backoff(self, retry: int) -> float:
        delay = min(self.max_backoff_s, self.backoff_s * 2.0 ** (retry - 1))
        return delay * random.uniform(0.5, 1.0)

    def _metrics(self, response: Any, model: str) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        return {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "cost_usd": self._cost(response, model),
        }

    def _cost(self, response: Any, model: str) -> float | None:
        # OpenRouter reports what it actually billed (LiteLLM keeps it in hidden params): exact,
        # including caching and reasoning tokens. Prefer it; price from the model map otherwise.
        reported = _reported_cost(response)
        if reported is not None:
            return reported
        provider = model.split("/", 1)[0] if "/" in model else None
        try:
            # The provider must be passed: an OpenRouter reply names the model without the
            # "openrouter/" prefix, and LiteLLM would otherwise price it as a direct provider.
            cost = float(
                litellm.completion_cost(
                    completion_response=response, model=model, custom_llm_provider=provider
                )
            )
        except Exception:
            cost = None
        usage = getattr(response, "usage", None)
        used_tokens = bool(
            getattr(usage, "prompt_tokens", 0) or getattr(usage, "completion_tokens", 0)
        )
        if cost is None or (cost == 0.0 and used_tokens):  # a 0.0 for a paid call means "unknown"
            if model not in self._unpriced:
                self._unpriced.add(model)
                logger.warning("no price for model %s; cost_usd will be null", model)
            return None
        return cost


def _reported_cost(response: Any) -> float | None:
    hidden = getattr(response, "_hidden_params", None) or {}
    try:
        cost = litellm.cost_calculator.get_response_cost_from_hidden_params(hidden)
    except Exception:
        return None
    return None if cost is None else float(cost)


def _classify(exc: Exception) -> str | None:
    """'retry' (same model), 'next_model', or None for errors that are not provider errors."""
    if isinstance(exc, MissingApiKey):
        return "next_model"
    if isinstance(exc, RETRYABLE_ERRORS):
        return "retry"
    if isinstance(exc, openai.APIError) and (getattr(exc, "status_code", 0) or 0) >= 500:
        return "retry"
    if isinstance(exc, openai.OpenAIError):  # base of every LiteLLM provider error
        return "next_model"
    return None


def _completion_args(
    role: ModelRole, model: str, messages: list[Message], output_model: type[BaseModel]
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": output_model,
        "timeout": role.timeout_s,
        "num_retries": 0,
    }
    optional = {
        "max_tokens": capped_max_tokens(role.max_tokens),
        "temperature": role.temperature,
        "reasoning_effort": role.reasoning_effort,
    }
    args.update({key: value for key, value in optional.items() if value is not None})
    return args


def _repair_instruction(error: ValidationError) -> str:
    # Locations and messages only: the offending values are already in the reply above.
    problems = [
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in error.errors(include_url=False, include_input=False)
    ]
    return (
        "Your previous reply did not match the required JSON schema:\n"
        + "\n".join(problems[:20])
        + "\nReply again with only the corrected JSON object."
    )


def _strip_fences(reply: str) -> str:
    match = _FENCE.match(reply.strip())
    return match.group(1) if match else reply


def _field(item: Any, name: str) -> Any:
    return item[name] if isinstance(item, Mapping) else getattr(item, name)


__all__ = ["LiteLLMGateway", "configure_litellm"]
