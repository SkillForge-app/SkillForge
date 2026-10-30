"""Environments and the startup check (AI-21).

    profile = startup()                 # BE worker / API process, once, before serving
    python -m core.ops check            # the same check from a shell or a deploy step

SKILLFORGE_ENV picks dev (the default), staging or production from environments.yaml.
`apply_environment` sets the profile's backend variables as defaults (an explicit variable wins)
and installs its limits and quality-sample rate. `check_environment` lists problems:

- production: anything that would make the service fake, insecure or unbounded is an error;
  a missing ANTHROPIC_API_KEY (no direct-API hop for an OpenRouter outage) is a warning.
- staging: the same, but fakes and the direct key are warnings.
- dev: everything is a warning; startup never refuses.

Problems name variables and files, never their values.
"""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.llm import ConfigError, Limits, RoleLimit, load_config, set_limits
from core.llm.config import LOCAL_PREFIX, key_env_for
from core.llm.gateway import BACKEND_ENV as LLM_BACKEND_ENV
from core.llm.local_embed import ensure_model
from core.llm.prompt_lock import check_lock
from core.llm.prompts import PROMPTS_DIR
from core.ops.events import set_sample_rate

ENV_VAR = "SKILLFORGE_ENV"
ENVIRONMENTS_PATH = Path(__file__).with_name("environments.yaml")
EnvName = Literal["dev", "staging", "production"]

# The variables the modules read (core/llm/gateway.py, core/knowledge/retrieval.py, store.py,
# search.py). Named here, not imported, so this module stays importable from anywhere.
RETRIEVER_ENV = "SKILLFORGE_RETRIEVER"
STORE_ENV = "SKILLFORGE_VECTOR_STORE"
PGVECTOR_DSN_ENV = "SKILLFORGE_PGVECTOR_DSN"
SEARCH_ENV = "SKILLFORGE_SEARCH"
BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"
BACKEND_VARS = (LLM_BACKEND_ENV, RETRIEVER_ENV, STORE_ENV, SEARCH_ENV)


class StartupError(ConfigError):
    """The environment is not fit to start (staging or production): see `problems`."""

    def __init__(self, env: str, problems: list["Problem"]) -> None:
        self.problems = problems
        lines = "\n".join(f"  {p}" for p in problems)
        super().__init__(f"refusing to start in {env}:\n{lines}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleLimitSpec(_Model):
    max_concurrency: int | None = Field(default=None, gt=0)
    requests_per_minute: int | None = Field(default=None, gt=0)


class LimitsSpec(_Model):
    max_output_tokens: int = Field(gt=0)
    max_input_chars: int = Field(gt=0)
    max_wait_s: float = Field(gt=0)
    skill_budget_usd: float = Field(gt=0)
    step_budget_usd: dict[Literal["analyze", "clarify", "design"], float]
    default_role: RoleLimitSpec
    roles: dict[str, RoleLimitSpec] = {}

    def to_limits(self) -> Limits:
        return Limits(
            max_output_tokens=self.max_output_tokens,
            max_input_chars=self.max_input_chars,
            max_wait_s=self.max_wait_s,
            roles={name: RoleLimit(**r.model_dump()) for name, r in self.roles.items()},
            default_role=RoleLimit(**self.default_role.model_dump()),
            skill_budget_usd=self.skill_budget_usd,
            step_budget_usd={str(step): usd for step, usd in self.step_budget_usd.items()},
        )


class Profile(_Model):
    backends: dict[str, str]
    limits: LimitsSpec
    quality_sample_rate: float = Field(ge=0, le=1)
    daily_spend_usd: float = Field(gt=0)


class Environments(_Model):
    version: int
    environments: dict[EnvName, Profile]


@cache
def load_environments(path: Path = ENVIRONMENTS_PATH) -> Environments:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        envs = Environments.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"cannot load environments {path}: {exc}") from exc
    for name, profile in envs.environments.items():
        unknown = sorted(set(profile.backends) - set(BACKEND_VARS))
        if unknown:
            raise ConfigError(f"{path}: {name} sets unknown backend variables {unknown}")
    return envs


def env_name(value: str | None = None) -> EnvName:
    name = (value if value is not None else os.environ.get(ENV_VAR, "dev")).strip().lower()
    if name not in ("dev", "staging", "production"):
        raise ConfigError(f"unknown {ENV_VAR}={name!r}; use dev, staging or production")
    return name  # type: ignore[return-value]


def profile(name: EnvName | None = None) -> Profile:
    return load_environments().environments[name or env_name()]


def apply_environment(name: EnvName | None = None) -> Profile:
    """Set the profile's backend defaults, limits and sample rate for this process."""
    chosen = profile(name)
    for var, value in chosen.backends.items():
        os.environ.setdefault(var, value)
    set_limits(chosen.limits.to_limits())
    set_sample_rate(chosen.quality_sample_rate)
    load_config.cache_clear()  # role overrides (SKILLFORGE_MODEL_*) are read on load
    return chosen


# ------------------------------------------------------------------ the check


@dataclass(frozen=True)
class Problem:
    severity: Literal["error", "warning"]
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity:7} {self.code}: {self.message}"


def check_environment(name: EnvName | None = None) -> list[Problem]:
    """Problems with the current process environment for profile `name`."""
    env = name or env_name()
    strict = env == "production"
    out: list[Problem] = []

    def add(code: str, message: str, *, error: bool) -> None:
        out.append(Problem("error" if error and env != "dev" else "warning", code, message))

    backend = {var: os.environ.get(var, "").strip().lower() for var in BACKEND_VARS}
    for var, fake in ((LLM_BACKEND_ENV, "fake"), (RETRIEVER_ENV, "fake"), (SEARCH_ENV, "fake")):
        if backend[var] == fake:
            add(f"backend.{var.lower()}", f"{var} is '{fake}'", error=strict)
    if backend[STORE_ENV] in ("", "local"):
        add("backend.vector_store", f"{STORE_ENV} is the local file index", error=strict)
    if backend[STORE_ENV] == "pgvector" and not os.environ.get(PGVECTOR_DSN_ENV):
        add("key.pgvector_dsn", f"{PGVECTOR_DSN_ENV} is not set", error=True)
    if backend[SEARCH_ENV] == "brave" and not os.environ.get(BRAVE_KEY_ENV):
        add("key.brave", f"{BRAVE_KEY_ENV} is not set", error=True)

    config = load_config()
    llm_live = backend[LLM_BACKEND_ENV] != "fake"
    primary_keys, fallback_keys = set(), set()
    for role_name, role in config.roles.items():
        if not role.model.startswith(LOCAL_PREFIX):
            primary_keys.add(key_env_for(role.model))
            fallback_keys |= {key_env_for(m) for m in role.fallbacks}
            if not role.fallbacks:
                add(f"roles.{role_name}.fallbacks", f"role {role_name} has no fallback", error=True)
        elif role.local is not None:
            try:
                ensure_model(role.local, download=False)
            except ConfigError:
                add(
                    f"roles.{role_name}.local_model",
                    f"the local model for role {role_name} is missing or fails its sha256; "
                    "run `python -m core.llm.local_embed download`",
                    error=True,
                )
    if llm_live:
        for key in sorted(k for k in primary_keys if k):
            if not os.environ.get(key):
                add(f"key.{key.lower()}", f"{key} is not set (primary models)", error=True)
        for key in sorted(k for k in fallback_keys - primary_keys if k):
            if not os.environ.get(key):
                add(
                    f"key.{key.lower()}",
                    f"{key} is not set: the direct-API fallback hop is skipped",
                    error=False,
                )

    lock = check_lock(PROMPTS_DIR)
    if lock:
        add("prompts.lock", f"{len(lock)} prompt(s) differ from prompts.lock.json", error=True)
    return out


def startup(name: EnvName | None = None) -> Profile:
    """Apply the profile and check it. Raises StartupError in staging and production when
    there is any error; in dev the problems are only returned by check_environment."""
    env = name or env_name()
    chosen = apply_environment(env)
    errors = [p for p in check_environment(env) if p.severity == "error"]
    if errors and env != "dev":
        raise StartupError(env, errors)
    return chosen
