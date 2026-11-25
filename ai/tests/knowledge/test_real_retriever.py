"""RealRetriever and ingest (AI-11) on deterministic fake vectors: no model, no network.

FakeGateway's vectors are a hash of the text, so the same text gives the same vector: asking
with a chunk's exact text must find that chunk first. Semantic quality is measured by the
recall evaluation (evaluation/retrieval), not here.
"""

import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from core.knowledge import RetrievalInputError, get_retriever, retrieve
from core.knowledge.ingest import IngestReport, Page, ingest_pages
from core.knowledge.real import EMPTY_INDEX, INFO_TTL_S, RealRetriever
from core.knowledge.retrieval import BACKEND_ENV
from core.knowledge.store import ChunkRecord, LocalStore, StoreInfo
from core.llm import ConfigError, FakeGateway, load_config, use_fake
from core.llm.config import ModelConfig
from evaluation.extraction.data import PageLabel, load_pages

LABELS = {label.file: label for label in load_pages()}
MODEL = load_config().role("embedding").model


def page(file: str, domain: str = "marketing", html: bytes | None = None) -> Page:
    label: PageLabel = LABELS[file]
    return Page(html or label.path.read_bytes(), str(label.url), label.retrieved, domain)


def no_prefix() -> ModelConfig:
    config = load_config()
    role = config.role("embedding").model_copy(update={"query_prefix": ""})
    return config.model_copy(update={"roles": {**config.roles, "embedding": role}})


@pytest.fixture
def fake() -> Iterator[FakeGateway]:
    with use_fake() as gateway:
        yield gateway


@pytest.fixture
async def indexed(fake: FakeGateway) -> tuple[LocalStore, IngestReport]:
    store = LocalStore()
    report = await ingest_pages(
        [
            page("synthetic-subscriber-footer.html"),
            page("synthetic-short-faq.html", "customer-support"),
            page("synthetic-stub.html"),  # rejected: too short
        ],
        store=store,
    )
    return store, report


async def test_ingest_indexes_ok_pages_and_reports_rejected_ones(
    indexed: tuple[LocalStore, IngestReport],
) -> None:
    store, report = indexed
    assert set(report.chunks) == {
        str(LABELS["synthetic-subscriber-footer.html"].url),
        str(LABELS["synthetic-short-faq.html"].url),
    }
    assert report.rejected == {str(LABELS["synthetic-stub.html"].url): ("too_short",)}
    assert store.info().count == report.total_chunks > 0
    assert store.info().model == load_config().role("embedding").model
    assert {d for r in store.records() for d in r.domains} == {"marketing", "customer-support"}


async def test_an_exact_chunk_text_finds_that_chunk_first(
    indexed: tuple[LocalStore, IngestReport],
) -> None:
    store, _ = indexed
    retriever = RealRetriever(store, model_config=no_prefix())
    for chunk in store.records():
        found = await retriever.retrieve(chunk.text, chunk.domains[0], 3)
        assert found[0].chunk_id == chunk.chunk_id
        assert found[0] == chunk.to_passage()  # the A4 Passage, citation fields intact


async def test_the_query_prefix_is_put_before_the_query(
    indexed: tuple[LocalStore, IngestReport], fake: FakeGateway
) -> None:
    store, _ = indexed
    await RealRetriever(store).retrieve("double opt-in", "marketing", 2)
    prefix = load_config().role("embedding").query_prefix
    assert fake.calls[-1].texts == [prefix + "double opt-in"]


async def test_a4_rules_hold(indexed: tuple[LocalStore, IngestReport]) -> None:
    store, _ = indexed
    retriever = RealRetriever(store)
    assert len(await retriever.retrieve("gift cards", "customer-support", 20)) <= store.info().count
    assert await retriever.retrieve("gift cards", "legal/contracts", 5) == []  # no match: []
    for query, domain, k in (("", "marketing", 5), ("q", "astrology", 5), ("q", "marketing", 0)):
        with pytest.raises(RetrievalInputError):
            await retriever.retrieve(query, domain, k)


async def test_an_empty_index_raises_config_error(fake: FakeGateway) -> None:
    with pytest.raises(ConfigError, match="empty"):
        await RealRetriever(LocalStore()).retrieve("anything", "marketing", 5)
    assert "run ingest" in EMPTY_INDEX


async def test_an_index_from_another_model_is_refused(
    indexed: tuple[LocalStore, IngestReport],
) -> None:
    store, _ = indexed
    config = load_config()
    other = config.role("embedding").model_copy(
        update={"model": "openai/text-embedding-3-small", "local": None}
    )
    with pytest.raises(ConfigError, match="rebuild the index"):
        await RealRetriever(
            store,
            model_config=config.model_copy(update={"roles": {**config.roles, "embedding": other}}),
        ).retrieve("anything", "marketing", 5)


async def test_the_default_retriever_is_real_and_reads_the_index_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake: FakeGateway
) -> None:
    monkeypatch.delenv(BACKEND_ENV)  # the conftest selects the fake; unset means real
    assert isinstance(get_retriever(), RealRetriever)
    with pytest.raises(ConfigError, match="empty"):  # the throwaway index path is empty
        await retrieve("influencer disclosure", "marketing")


async def test_reingesting_replaces_and_a_rejected_page_leaves_the_index(
    indexed: tuple[LocalStore, IngestReport],
) -> None:
    store, first = indexed
    again = await ingest_pages(
        [
            page("synthetic-subscriber-footer.html"),
            page("synthetic-short-faq.html", "customer-support"),
        ],
        store=store,
    )
    assert again.chunks == first.chunks and store.info().count == first.total_chunks
    # The same URL now serves a login wall: its chunks go.
    login = LABELS["synthetic-login-wall.html"].path.read_bytes()
    footer = page("synthetic-subscriber-footer.html", html=login)
    report = await ingest_pages([footer], store=store)
    assert footer.url in report.rejected
    assert all(str(r.source_url) != footer.url for r in store.records())


async def test_ingest_checks_domains_before_doing_any_work(fake: FakeGateway) -> None:
    with pytest.raises(RetrievalInputError):
        await ingest_pages(
            [page("synthetic-short-faq.html", "Customer Support")], store=LocalStore()
        )
    assert fake.calls == []


def test_build_index_cli_indexes_the_real_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evaluation.retrieval.__main__ import main

    monkeypatch.setattr("evaluation.retrieval.__main__.ensure_model", lambda local: None)
    with use_fake():
        assert main(["build-index", "--path", str(tmp_path / "dev")]) == 0
    store = LocalStore(tmp_path / "dev")
    hosts = {r.source_url.host for r in store.records()}
    assert hosts and not any(h and h.endswith(".example") for h in hosts)  # never synthetic
    assert "indexed" in capsys.readouterr().out


# ------------------------------------------------------------------ index check (review F6)


class WatchedStore(LocalStore):
    """A LocalStore that counts info() calls and records the thread of each store call."""

    def __init__(self) -> None:
        super().__init__()
        self.info_calls = 0
        self.threads: list[threading.Thread] = []

    def info(self) -> StoreInfo:
        self.info_calls += 1
        self.threads.append(threading.current_thread())
        return super().info()

    def search(
        self, vector: Sequence[float], domain: str, k: int
    ) -> list[tuple[ChunkRecord, float]]:
        self.threads.append(threading.current_thread())
        return super().search(vector, domain, k)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def watched(*pages: Page) -> WatchedStore:
    store = WatchedStore()
    if pages:
        await ingest_pages(list(pages), store=store)
    store.info_calls, store.threads = 0, []  # ingest calls info() itself
    return store


async def test_a_passed_index_check_is_trusted_for_a_minute(fake: FakeGateway) -> None:
    store = await watched(page("synthetic-subscriber-footer.html"))
    clock = Clock()
    retriever = RealRetriever(store, clock=clock)
    for _ in range(3):
        assert await retriever.retrieve("subscriber newsletter", "marketing", 3)
    assert store.info_calls == 1  # not one full count per query
    clock.now += INFO_TTL_S - 1
    await retriever.retrieve("subscriber newsletter", "marketing", 3)
    assert store.info_calls == 1
    clock.now += 2  # the minute is over: checked again
    await retriever.retrieve("subscriber newsletter", "marketing", 3)
    assert store.info_calls == 2


async def test_store_calls_run_off_the_event_loop(fake: FakeGateway) -> None:
    store = await watched(page("synthetic-subscriber-footer.html"))
    await RealRetriever(store).retrieve("subscriber newsletter", "marketing", 3)
    assert len(store.threads) == 2  # info, then search
    assert all(t is not threading.main_thread() for t in store.threads)


async def test_a_failed_index_check_is_never_trusted(fake: FakeGateway) -> None:
    store = await watched()
    retriever = RealRetriever(store, clock=Clock())
    for _ in range(2):
        with pytest.raises(ConfigError, match="empty"):
            await retriever.retrieve("anything", "marketing", 5)
    assert store.info_calls == 2
    await ingest_pages([page("synthetic-subscriber-footer.html")], store=store)
    assert await retriever.retrieve("subscriber newsletter", "marketing", 3)  # no wait


async def test_an_index_emptied_later_is_noticed_within_the_minute(fake: FakeGateway) -> None:
    store = await watched(page("synthetic-subscriber-footer.html"))
    clock = Clock()
    retriever = RealRetriever(store, clock=clock)
    assert await retriever.retrieve("subscriber newsletter", "marketing", 3)
    for url in {str(r.source_url) for r in store.records()}:
        store.replace_source(url, [], [], model=MODEL)
    assert await retriever.retrieve("subscriber newsletter", "marketing", 3) == []
    clock.now += INFO_TTL_S
    with pytest.raises(ConfigError, match="empty"):
        await retriever.retrieve("subscriber newsletter", "marketing", 3)
