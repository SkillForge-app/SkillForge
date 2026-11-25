"""Test-wide guards. Tests use the fake retriever, a throwaway index folder and no real
embedding model, unless a test opts in (`pytest -m model` for the real local model). They also
use the fake LLM backend, unless marked `live` or `model` (the local model runs through the real
gateway), and have no outbound network, unless marked `live` (`pgvector` tests keep the
network for their database)."""

import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.knowledge import set_retriever
from core.knowledge.retrieval import BACKEND_ENV
from core.knowledge.store import INDEX_PATH_ENV, STORE_ENV
from core.llm import set_gateway
from core.llm.gateway import BACKEND_ENV as LLM_BACKEND_ENV

NETWORK_BLOCKED = "outbound network is blocked in tests; mark the test `live` if it needs it"
_getaddrinfo = socket.getaddrinfo
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


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


@pytest.fixture(autouse=True)
def _no_paid_calls_and_no_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """The real LLM backend loads ai/.env, so a test that forgot the fake would make paid calls.
    CI also cuts the network (ai.yml); this keeps a developer machine just as safe. `model`
    tests keep the real backend for the local embedding model, but not the network."""
    marked = {m.name for m in request.node.iter_markers()}
    if "live" not in marked:
        if "model" not in marked:
            monkeypatch.setenv(LLM_BACKEND_ENV, "fake")  # the default is "litellm"
        if "pgvector" not in marked:
            monkeypatch.setattr(socket, "getaddrinfo", _local_getaddrinfo)
            monkeypatch.setattr(socket.socket, "connect", _local_connect)
            monkeypatch.setattr(socket.socket, "connect_ex", _local_connect_ex)
    set_gateway(None)
    yield
    set_gateway(None)


def _is_local(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode()
    if not isinstance(host, str):
        return False
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _local_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if not _is_local(host):
        raise socket.gaierror(f"{NETWORK_BLOCKED} (lookup of {host!r})")
    return _getaddrinfo(host, *args, **kwargs)


def _local_connect(self: socket.socket, address: Any) -> None:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        raise OSError(f"{NETWORK_BLOCKED} (connect to {address!r})")
    _connect(self, address)


def _local_connect_ex(self: socket.socket, address: Any) -> int:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        raise OSError(f"{NETWORK_BLOCKED} (connect to {address!r})")
    return _connect_ex(self, address)
