"""Model roles and LiteLLM model info loaded from models.yaml, with per-role env overrides."""

import os
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.llm.errors import ConfigError

CONFIG_PATH = Path(__file__).with_name("models.yaml")
MODEL_ENV_PREFIX = "SKILLFORGE_MODEL_"
# The environment variable that holds the API key for each LiteLLM provider prefix.
PROVIDER_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def key_env_for(model: str) -> str | None:
    """The env var that must hold the API key for a LiteLLM model string, if we know it."""
    return PROVIDER_KEYS.get(model.split("/", 1)[0])


ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]


LOCAL_PREFIX = "local/"  # a model run in-process (core/llm/local_embed.py), not via LiteLLM


class LocalModel(BaseModel):
    """Where a local model's files come from, pinned: a commit (never a branch) and a hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")  # Hugging Face repo with the ONNX export
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    file: str = Field(pattern=r"^[\w./-]+\.onnx$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelRole(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    temperature: float | None = None  # leave unset for Claude 5.5 models
    max_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: ReasoningEffort | None = None
    timeout_s: float = Field(default=60, gt=0)
    num_retries: int = Field(default=2, ge=0)
    fallbacks: tuple[str, ...] = ()
    dimensions: int | None = Field(default=None, gt=0)  # embedding roles only
    local: LocalModel | None = None  # required for a "local/..." model
    query_prefix: str = ""  # embedding roles: put before a search query (e.g. BGE's instruction)

    @model_validator(mode="after")
    def _no_embedding_fallbacks(self) -> "ModelRole":
        if self.dimensions is not None and self.fallbacks:
            raise ValueError(
                "embedding roles cannot have fallbacks: another model's vectors are not "
                "comparable and would corrupt the index"
            )
        if self.model.startswith(LOCAL_PREFIX) != (self.local is not None):
            raise ValueError(f"a {LOCAL_PREFIX!r} model needs `local` pins, and only it")
        if self.local is not None and self.dimensions is None:
            raise ValueError("local models are embedding models: set `dimensions`")
        return self


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    roles: dict[str, ModelRole]
    model_info: dict[str, dict[str, Any]] = {}  # LiteLLM model-map overrides

    def role(self, name: str) -> ModelRole:
        try:
            return self.roles[name]
        except KeyError:
            known = ", ".join(sorted(self.roles))
            raise ConfigError(f"unknown model role {name!r}; known roles: {known}") from None

    def info_for(self, model: str) -> dict[str, Any] | None:
        """Our model_info entry for a model: by full name (OpenRouter), else by bare name."""
        return self.model_info.get(model) or self.model_info.get(model.split("/", 1)[-1])


@cache
def load_config(path: Path = CONFIG_PATH) -> ModelConfig:
    """Load models.yaml once. Call `load_config.cache_clear()` after changing env overrides."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = ModelConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"cannot load model config {path}: {exc}") from exc
    roles = {}
    for name, role in config.roles.items():
        override = os.environ.get(MODEL_ENV_PREFIX + name.upper())
        roles[name] = role.model_copy(update={"model": override}) if override else role
    return config.model_copy(update={"roles": roles})
