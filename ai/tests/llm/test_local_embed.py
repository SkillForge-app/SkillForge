"""The local embedding path (AI-11): pinned files, the sha256 check, and the gateway routing.

No test here downloads or loads a real model; `pytest -m model` runs the one that does.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from core.llm import ConfigError, LLMOutputInvalid, load_config
from core.llm.config import LocalModel, ModelConfig, ModelRole
from core.llm.local_embed import CACHE_ENV, ensure_model, main, model_dir
from tests.llm.litellm_mock import FakeLiteLLM, make_gateway

CONTENT = b"not really an onnx model"
PIN = LocalModel(
    repo="Example/tiny-model-onnx",
    revision="0" * 40,
    file="model.onnx",
    sha256=hashlib.sha256(CONTENT).hexdigest(),
)
LOCAL_ROLE = ModelRole(model="local/BAAI/bge-small-en-v1.5", dimensions=4, local=PIN)


@pytest.fixture(autouse=True)
def _cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "models"))
    return tmp_path / "models"


def records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "skillforge.llm"]


def put_model(content: bytes = CONTENT) -> Path:
    folder = model_dir(PIN)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PIN.file).write_bytes(content)
    return folder


# ------------------------------------------------------------------ config


def test_the_embedding_role_is_a_pinned_local_model() -> None:
    role = load_config().role("embedding")
    assert role.model.startswith("local/") and role.local is not None
    assert role.dimensions == 384
    assert role.query_prefix.startswith("Represent this sentence")


@pytest.mark.parametrize(
    "fields",
    [
        {"model": "local/x/y", "dimensions": 4},  # local model without pins
        {
            "model": "openai/text-embedding-3-small",
            "dimensions": 4,
            "local": PIN,
        },  # pins, not local
        {"model": "local/x/y", "local": PIN},  # no dimensions
    ],
)
def test_bad_local_roles_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ModelRole.model_validate(fields)


@pytest.mark.parametrize("revision", ["main", "abc123", "Z" * 40])
def test_a_pin_must_be_a_full_commit(revision: str) -> None:
    with pytest.raises(ValidationError):
        LocalModel.model_validate({**PIN.model_dump(), "revision": revision})


# ------------------------------------------------------------------ files


def test_a_downloaded_file_with_the_right_hash_is_used() -> None:
    folder = put_model()
    assert ensure_model(PIN, download=False) == folder


def test_a_tampered_file_is_refused() -> None:
    put_model(b"something else entirely")
    with pytest.raises(ConfigError, match="sha256"):
        ensure_model(PIN)


def test_a_missing_file_is_downloaded_at_the_pinned_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_download(**kwargs: Any) -> str:
        calls.append(kwargs)
        Path(kwargs["local_dir"]).mkdir(parents=True, exist_ok=True)
        (Path(kwargs["local_dir"]) / PIN.file).write_bytes(CONTENT)
        return str(kwargs["local_dir"])

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
    with pytest.raises(ConfigError, match="not downloaded"):
        ensure_model(PIN, download=False)
    assert ensure_model(PIN) == model_dir(PIN)
    assert calls[0]["repo_id"] == PIN.repo and calls[0]["revision"] == PIN.revision
    assert PIN.file in calls[0]["allow_patterns"]


def test_download_cli_refuses_a_hosted_role(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["download", "--role", "analysis"]) == 2
    assert "not a local model" in capsys.readouterr().err


# ------------------------------------------------------------------ gateway routing


def local_config() -> ModelConfig:
    config = load_config()
    return config.model_copy(update={"roles": {**config.roles, "embedding": LOCAL_ROLE}})


async def test_the_gateway_embeds_locally_with_no_key_and_no_litellm(
    llm: FakeLiteLLM, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="skillforge.llm")
    for env in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    seen: list[tuple[str, list[str]]] = []

    def fake_local(model: str, local: LocalModel, texts: list[str]) -> list[list[float]]:
        seen.append((model, texts))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]

    monkeypatch.setattr("core.llm.litellm_gateway.embed_local", fake_local)
    vectors = await make_gateway(local_config(), embed_batch_size=2).embed(["a", "bb", "ccc"])
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    assert seen == [(LOCAL_ROLE.model, ["a", "bb"]), (LOCAL_ROLE.model, ["ccc"])]
    assert llm.calls == []  # LiteLLM was never called
    recs = records(caplog)
    assert [r["n_texts"] for r in recs] == [2, 1]
    assert all(r["cost_usd"] == 0.0 and r["model"] == LOCAL_ROLE.model for r in recs)


async def test_a_local_model_with_the_wrong_dimensions_is_an_output_error(
    llm: FakeLiteLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "core.llm.litellm_gateway.embed_local",
        lambda model, local, texts: [[0.0] * 7 for _ in texts],
    )
    with pytest.raises(LLMOutputInvalid, match="expected 1 of 4"):
        await make_gateway(local_config()).embed(["a"])


async def test_a_local_model_error_is_not_retried_or_hidden(
    llm: FakeLiteLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(model: str, local: LocalModel, texts: list[str]) -> list[list[float]]:
        raise ConfigError("files are missing")

    monkeypatch.setattr("core.llm.litellm_gateway.embed_local", broken)
    with pytest.raises(ConfigError, match="files are missing"):
        await make_gateway(local_config()).embed(["a"])


# ------------------------------------------------------------------ the real model (opt-in)


@pytest.mark.model
async def test_the_real_embedding_model_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in: `pytest -m model`. Needs `python -m core.llm.local_embed download` first."""
    from core.llm.litellm_gateway import LiteLLMGateway
    from core.llm.local_embed import DEFAULT_CACHE

    monkeypatch.setenv(CACHE_ENV, str(DEFAULT_CACHE))
    role = load_config().role("embedding")
    assert role.local is not None
    ensure_model(role.local, download=False)
    gateway = LiteLLMGateway(env_file=None)
    a, b, c = await gateway.embed(
        [
            "Influencers must disclose paid relationships with brands.",
            "Endorsers need to tell followers when a company pays them.",
            "The NIST framework helps organisations manage AI risk.",
        ]
    )

    def dot(x: list[float], y: list[float]) -> float:
        return sum(p * q for p, q in zip(x, y, strict=True))

    assert len(a) == role.dimensions
    assert abs(dot(a, a) - 1) < 1e-3  # unit length
    assert dot(a, b) > dot(a, c)  # a paraphrase is closer than an unrelated sentence
