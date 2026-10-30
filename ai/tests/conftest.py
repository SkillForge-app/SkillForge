"""Test-wide guards. Tests use the fake retriever, a throwaway index folder and no real
embedding model, unless a test opts in (`pytest -m model` for the real local model)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.knowledge import set_retriever
from core.knowledge.retrieval import BACKEND_ENV
from core.knowledge.store import INDEX_PATH_ENV, STORE_ENV


@pytest.fixture(autouse=True)
def _fake_retrieval_and_no_local_model(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    monkeypatch.setenv(BACKEND_ENV, "fake")  # the default is "real"; tests keep the fake
    monkeypatch.setenv(INDEX_PATH_ENV, str(tmp_path / "index"))  # never the dev index
    monkeypatch.delenv(STORE_ENV, raising=False)
    if request.node.get_closest_marker("model") is None:

        def no_model(*args: object, **kwargs: object) -> None:
            raise AssertionError("tests must not load a real embedding model; mark it `model`")

        monkeypatch.setattr("core.llm.local_embed._load", no_model)
    set_retriever(None)
    yield
    set_retriever(None)
