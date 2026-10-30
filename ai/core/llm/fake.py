"""FakeGateway: a network-free LLMGateway for tests and for coding against the contract.

    fake = FakeGateway()
    fake.register("analysis/request", {"kind": "role", "domain": "marketing"})
    fake.register_error("analysis/request", LLMUnavailable("provider down"), times=1)
    with use_fake(fake):
        ...

It loads and renders the real prompt file, so prompt bugs still fail tests. It validates canned
outputs against `output_model` and raises LLMOutputInvalid on mismatch, like the real gateway.
`embed` returns deterministic unit vectors derived from a hash of each text.

Production behaviour (AI-21), without a network:
    fake.fail_model("openrouter/anthropic/claude-sonnet-5.5")   # the primary is down: the role's
                                                               # fallback answers, as in production
    FakeGateway(cost_usd=0.40)          # every answer costs this much, to exercise skill budgets
The skill budget (core.llm.usage.skill_run) and the input-size cap (core.llm.limits) apply here
too, so pipeline tests see BudgetExceeded and LLMInputError exactly as with the real gateway.
"""

import hashlib
import json
import math
import random
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from core.llm.config import ModelConfig, load_config
from core.llm.errors import LLMError, LLMOutputInvalid, LLMUnavailable
from core.llm.gateway import EMBEDDING_ROLE, check_texts, set_gateway
from core.llm.limits import check_input_size
from core.llm.prompts import Message, load_prompt
from core.llm.usage import CallRecord, check_budget, current_skill_id, log_call, new_call_id

T = TypeVar("T", bound=BaseModel)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"
EMBED_KEY = "embed"
DEFAULT_DIMENSIONS = 384
FAKE_MODEL = "fake"


class FakeOutputMissing(LLMError):
    """The fake has no registered output or fixture file for this prompt."""


@dataclass(frozen=True)
class FakeCall:
    kind: Literal["complete", "embed"]
    model_role: str
    prompt_id: str | None = None
    inputs: dict[str, Any] | None = None
    messages: list[Message] | None = None
    output_model: type[BaseModel] | None = None
    texts: list[str] | None = None


@dataclass
class _ErrorRule:
    error: Exception
    remaining: int | None  # None: raise on every call


@dataclass
class FakeGateway:
    prompts_root: Path | None = None
    fixtures_dir: Path | None = FIXTURES_DIR
    config: ModelConfig | None = None
    dimensions: int | None = None  # overrides the embedding role's `dimensions`
    cost_usd: float = 0.0  # logged cost of every successful `complete`
    calls: list[FakeCall] = field(default_factory=list, init=False)
    _outputs: dict[str, BaseModel | Mapping[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _errors: dict[str, _ErrorRule] = field(default_factory=dict, init=False, repr=False)
    _failing: dict[str, _ErrorRule] = field(default_factory=dict, init=False, repr=False)

    def register(self, prompt_id: str, output: BaseModel | Mapping[str, Any]) -> None:
        """Return `output` (validated against the caller's output_model) for this prompt."""
        self._outputs[prompt_id] = output

    def register_error(self, key: str, error: Exception, *, times: int | None = None) -> None:
        """Raise `error` for a prompt_id, or for embed calls with key "embed".

        With `times=n`, raise only on the next n calls, then answer normally. A registered
        error wins over a registered output.
        """
        if times is not None and times < 1:
            raise ValueError("times must be >= 1")
        self._errors[key] = _ErrorRule(error, times)

    def fail_model(
        self, model: str, error: Exception | None = None, *, times: int | None = None
    ) -> None:
        """Make every `complete` on `model` fail (the next `times` calls only, if given).

        While any model is failing, `complete` walks the role's real chain from models.yaml
        (its model, then `fallbacks`), logs an error CallRecord for each failing link and
        answers from the first working one, with `fallback` set to its position. When every
        link fails it raises LLMUnavailable, like the real gateway.
        """
        if times is not None and times < 1:
            raise ValueError("times must be >= 1")
        self._failing[model] = _ErrorRule(error or LLMUnavailable("simulated outage"), times)

    def reset(self) -> None:
        self.calls.clear()
        self._outputs.clear()
        self._errors.clear()
        self._failing.clear()

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
        role = model_role or prompt.meta.model_role
        role_config = self._config().role(role)
        self.calls.append(
            FakeCall(
                kind="complete",
                model_role=role,
                prompt_id=prompt_id,
                inputs=dict(inputs),
                messages=messages,
                output_model=output_model,
            )
        )
        record = {
            "kind": "complete",
            "model_role": role,
            "prompt_id": prompt_id,
            "prompt_version": prompt.version,
        }
        call_id = new_call_id()
        chain = (role_config.model, *role_config.fallbacks) if self._failing else (FAKE_MODEL,)
        last: Exception | None = None
        for index, model in enumerate(chain):
            check_budget()
            start = time.perf_counter()
            rule = self._failing.get(model)
            if rule is not None and _consume(rule, self._failing, model):
                _log(record, start, error=rule.error, model=model, call_id=call_id, fallback=index)
                last = rule.error
                continue
            try:
                self._raise_registered(prompt_id)
                result = self._canned_output(prompt_id, output_model)
            except Exception as exc:
                _log(record, start, error=exc, model=model, call_id=call_id, fallback=index)
                raise
            _log(
                record, start, cost_usd=self.cost_usd, model=model, call_id=call_id, fallback=index
            )
            return result
        raise LLMUnavailable(f"role {role}: all models failed ({', '.join(chain)})") from last

    async def embed(
        self, texts: Sequence[str], *, model_role: str = EMBEDDING_ROLE
    ) -> list[list[float]]:
        texts = check_texts(texts)
        role = self._config().role(model_role)
        if not texts:
            return []
        dimensions = self.dimensions or role.dimensions or DEFAULT_DIMENSIONS
        self.calls.append(FakeCall(kind="embed", model_role=model_role, texts=texts))
        record = {"kind": "embed", "model_role": model_role, "n_texts": len(texts)}
        start = time.perf_counter()
        try:
            self._raise_registered(EMBED_KEY)
        except Exception as exc:
            _log(record, start, error=exc)
            raise
        _log(record, start)
        return [fake_vector(text, dimensions) for text in texts]

    def _config(self) -> ModelConfig:
        return self.config or load_config()

    def _raise_registered(self, key: str) -> None:
        rule = self._errors.get(key)
        if rule is None:
            return
        if rule.remaining is not None:
            rule.remaining -= 1
            if rule.remaining == 0:
                del self._errors[key]
        raise rule.error

    def _canned_output(self, prompt_id: str, output_model: type[T]) -> T:
        raw: Any = self._outputs.get(prompt_id)
        if raw is None:
            raw = self._fixture(prompt_id)
        if isinstance(raw, output_model):
            return raw.model_copy(deep=True)
        if isinstance(raw, BaseModel):
            raw = raw.model_dump(mode="json")
        try:
            # JSON mode, like the real gateway (model_validate_json): strict models then accept
            # e.g. ISO date strings exactly as they would from a model reply.
            return output_model.model_validate_json(json.dumps(raw, default=str))
        except ValidationError as exc:
            raise LLMOutputInvalid(
                f"canned output for {prompt_id!r} does not match {output_model.__name__}"
            ) from exc

    def _fixture(self, prompt_id: str) -> Any:
        path = self.fixtures_dir / f"{prompt_id}.json" if self.fixtures_dir else None
        if path is None or not path.exists():
            raise FakeOutputMissing(
                f"no fake output for {prompt_id!r}: call fake.register(...) "
                f"or add {path or 'a fixture file'}"
            )
        return json.loads(path.read_text(encoding="utf-8"))


def fake_vector(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """A deterministic unit vector for `text`, the same on every run and machine."""
    rng = random.Random(hashlib.sha256(text.encode("utf-8")).digest())
    vector = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


@contextmanager
def use_fake(fake: FakeGateway | None = None) -> Iterator[FakeGateway]:
    """Install a FakeGateway for the block, then restore the previous gateway."""
    fake = fake or FakeGateway()
    previous = set_gateway(fake)
    try:
        yield fake
    finally:
        set_gateway(previous)


def _consume(rule: _ErrorRule, rules: dict[str, _ErrorRule], key: str) -> bool:
    """True when the rule fires for this call (and counts it down)."""
    if rule.remaining is not None:
        rule.remaining -= 1
        if rule.remaining == 0:
            del rules[key]
    return True


def _log(
    fields: dict[str, Any],
    start: float,
    error: Exception | None = None,
    *,
    model: str = FAKE_MODEL,
    call_id: str | None = None,
    fallback: int = 0,
    cost_usd: float = 0.0,
) -> None:
    log_call(
        CallRecord(
            call_id=call_id or new_call_id(),
            model=model,
            cost_usd=0.0 if error else cost_usd,
            latency_ms=(time.perf_counter() - start) * 1000,
            status="error" if error else "ok",
            error_type=type(error).__name__ if error else None,
            fallback=fallback,
            skill_run=current_skill_id(),
            **fields,
        )
    )
