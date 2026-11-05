from pathlib import Path

import pytest

from core.llm import (
    ConfigError,
    FakeGateway,
    LLMUnavailable,
    complete_sync,
    load_config,
    track_usage,
)
from core.llm.usage import CallRecord, log_call
from tests.llm.helpers import Greeting

INPUTS = {"name": "Ziad", "platform": "Claude"}


def test_default_config_has_the_contract_roles() -> None:
    config = load_config()
    assert {"default", "analysis", "extraction", "judge", "embedding"} <= config.roles.keys()
    assert config.role("embedding").dimensions == 384
    assert config.role("analysis").model == "openrouter/anthropic/claude-sonnet-5.5"
    assert config.role("extraction").model == "openrouter/anthropic/claude-haiku-5.5"


def test_claude_roles_follow_claude_5_5_rules() -> None:
    config = load_config()
    for name, role in config.roles.items():
        if "claude-" in role.model and ("5-5" in role.model or "5.5" in role.model):
            assert role.temperature is None, f"{name}: Claude 5.5 rejects temperature"
            assert (role.max_tokens or 0) >= 16000, f"{name}: thinking needs room"
            assert config.info_for(role.model) is not None, f"{name}: no model_info (no cost)"


def test_every_role_has_a_known_key_and_a_price() -> None:
    from core.llm.config import LOCAL_PREFIX, key_env_for

    config = load_config()
    for name, role in config.roles.items():
        if role.model.startswith(LOCAL_PREFIX):  # runs in-process: no key, no price
            assert role.local is not None and role.dimensions, name
            continue
        assert key_env_for(role.model), f"{name}: unknown provider for {role.model}"
        if role.dimensions is None:  # chat roles must be priced by us
            assert config.info_for(role.model) is not None, f"{name}: no price"


def test_model_info_has_prices() -> None:
    for model, info in load_config().model_info.items():
        assert info["input_cost_per_token"] > 0 and info["output_cost_per_token"] > 0, model
        assert info["litellm_provider"] and info["mode"] == "chat", model


def test_env_overrides_one_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLFORGE_MODEL_ANALYSIS", "openai/some-model")
    load_config.cache_clear()
    config = load_config()
    assert config.role("analysis").model == "openai/some-model"
    assert config.role("analysis").max_tokens == 16000
    assert config.role("extraction").model.startswith("openrouter/anthropic/")
    assert config.model_info  # overrides keep the model_info block


def test_unknown_role() -> None:
    with pytest.raises(ConfigError, match="known roles: .*analysis"):
        load_config().role("nope")


def test_bad_config_file(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text("roles:\n  default:\n    temperature: 0.1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot load"):
        load_config(path)


def test_track_usage_adds_up_nested_blocks(fake: FakeGateway) -> None:
    fake.register("demo/greet", {"greeting": "Hi", "tone": "warm"})
    with track_usage() as run:
        complete_sync("demo/greet", INPUTS, Greeting)
        with track_usage() as skill:
            log_call(
                CallRecord(
                    call_id="x",
                    kind="complete",
                    model_role="analysis",
                    model="m",
                    input_tokens=100,
                    output_tokens=20,
                    cost_usd=0.5,
                    latency_ms=1,
                    status="ok",
                )
            )
            fake.register_error("demo/greet", LLMUnavailable("down"), times=1)
            with pytest.raises(LLMUnavailable):
                complete_sync("demo/greet", INPUTS, Greeting)
    assert (skill.calls, skill.errors, skill.input_tokens, skill.cost_usd) == (2, 1, 100, 0.5)
    assert (run.calls, run.errors, run.output_tokens, run.cost_usd) == (3, 1, 20, 0.5)
