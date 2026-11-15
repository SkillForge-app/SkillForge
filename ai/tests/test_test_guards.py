"""The suite's own guards (tests/conftest.py): no real LLM backend and no outbound network,
unless a test is marked `live` (or `pgvector`, for its database)."""

import socket

import pytest

from core.llm import FakeGateway, get_gateway


def test_the_llm_backend_is_the_fake_by_default() -> None:
    # The real default (litellm) loads ai/.env, whose keys would make any forgotten call paid.
    assert isinstance(get_gateway(), FakeGateway)


def test_outbound_network_is_blocked() -> None:
    with pytest.raises(OSError, match="outbound network is blocked in tests"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(OSError, match="outbound network is blocked in tests"):
        socket.create_connection(("192.0.2.1", 443), timeout=1)


def test_loopback_still_works() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        with socket.create_connection(server.getsockname()[:2], timeout=2):
            pass
