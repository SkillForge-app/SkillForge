"""Contract A4 in fake mode: Passage, retrieve(), FakeRetriever and its fixture passages."""

import json
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.knowledge import (
    MAX_K,
    FakeRetriever,
    Passage,
    RetrievalCall,
    RetrievalInputError,
    Retriever,
    get_retriever,
    retrieve,
    retrieve_sync,
    set_retriever,
    to_source,
)
from core.knowledge.retrieval import BACKEND_ENV, FIXTURES_PATH, load_fixtures
from core.llm import ConfigError, LLMInputError
from core.spec import validate_spec
from tests.spec.helpers import example

# Every fixture URL was opened and checked; the value is the page's own title.
VERIFIED_SOURCES = dict(
    [
        (
            "https://www.ftc.gov/business-guidance/advertising-marketing",
            "Advertising and Marketing | Federal Trade Commission",
        ),
        (
            "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking",
            "FTC's Endorsement Guides: What People Are Asking",
        ),
        (
            "https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business",
            "CAN-SPAM Act: A Compliance Guide for Business | Federal Trade Commission",
        ),
        (
            "https://www.asa.org.uk/codes-and-rulings/advertising-codes/non-broadcast-code.html",
            "Non-broadcast Code",
        ),
        (
            "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
            "SEO Starter Guide: The Basics",
        ),
        (
            "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
            "Creating Helpful, Reliable, People-First Content",
        ),
        (
            "https://arxiv.org/abs/2005.11401",
            "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        ),
        (
            "https://platform.claude.com/docs/en/test-and-evaluate/develop-tests",
            "Define success criteria and build evaluations",
        ),
        (
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview",
            "Prompt engineering overview",
        ),
        (
            "https://www.nist.gov/itl/ai-risk-management-framework",
            "AI Risk Management Framework | NIST",
        ),
        (
            "https://arxiv.org/abs/2307.03172",
            "Lost in the Middle: How Language Models Use Long Contexts",
        ),
        (
            "https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
            "LLM01:2025 Prompt Injection - OWASP Gen AI Security Project",
        ),
        (
            "https://arxiv.org/abs/1908.10084",
            "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
        ),
    ]
)
SEED_DOMAINS = ("marketing", "technology/ai")

GOOD = {
    "chunk_id": "mkt-example-01",
    "text": "  A short summary of what the page says.  ",
    "source_url": "https://www.ftc.gov/business-guidance/advertising-marketing",
    "title": "Advertising and Marketing | Federal Trade Commission",
    "retrieved": "2026-10-23",
}


def passage(**changes: object) -> Passage:
    return Passage.model_validate_json(json.dumps({**GOOD, **changes}))


@pytest.fixture(autouse=True)
def _fresh_retriever(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(BACKEND_ENV, "fake")  # these tests are about the A4 call and the fake
    set_retriever(None)
    yield
    set_retriever(None)


@pytest.fixture(scope="module")
def fake() -> FakeRetriever:
    return FakeRetriever()


# ------------------------------------------------------------------ Passage


def test_passage_has_exactly_the_contract_fields() -> None:
    assert set(Passage.model_fields) == {"chunk_id", "text", "source_url", "title", "retrieved"}


def test_passage_trims_text_and_parses_types() -> None:
    p = passage()
    assert p.text == "A short summary of what the page says."
    assert p.retrieved == date(2026, 10, 23)
    assert str(p.source_url) == GOOD["source_url"]


def test_passage_round_trips_through_json() -> None:
    p = passage()
    assert Passage.model_validate_json(p.model_dump_json()) == p


def test_passage_is_frozen() -> None:
    with pytest.raises(ValidationError):
        passage().text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": "field"},
        {"source_url": "ftp://example.com/file"},
        {"source_url": "not a url"},
        {"chunk_id": "Has Spaces"},
        {"chunk_id": "ab"},
        {"text": "   "},
        {"text": "x" * 2001},
        {"title": ""},
        {"title": "t" * 201},
        {"retrieved": "yesterday"},
        {"retrieved": 20261023},
    ],
)
def test_passage_rejects_bad_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        passage(**changes)


def test_passage_requires_every_field() -> None:
    for name in GOOD:
        data = {k: v for k, v in GOOD.items() if k != name}
        with pytest.raises(ValidationError):
            Passage.model_validate_json(json.dumps(data))


def test_to_source_maps_a_passage_to_a_skillspec_source() -> None:
    source = to_source(passage(), "src-ftc-advertising")
    assert source.id == "src-ftc-advertising"
    assert source.url == passage().source_url
    assert source.retrieved == date(2026, 10, 23)
    assert source.title == GOOD["title"]
    with pytest.raises(ValidationError):
        to_source(passage(), "Not Kebab")


# ------------------------------------------------------------------ fixture passages


def test_fixtures_cover_both_seed_domains(fake: FakeRetriever) -> None:
    counts = Counter(e.domain for e in fake.entries)
    assert len(fake.entries) >= 20
    assert set(counts) == set(SEED_DOMAINS)
    assert all(counts[d] >= 10 for d in SEED_DOMAINS), counts


def test_fixtures_are_unique(fake: FakeRetriever) -> None:
    ids = [e.passage.chunk_id for e in fake.entries]
    texts = [e.passage.text for e in fake.entries]
    assert len(set(ids)) == len(ids)
    assert len(set(texts)) == len(texts)


def test_fixture_ids_follow_the_domain_prefix(fake: FakeRetriever) -> None:
    prefix = {"marketing": "mkt-", "technology/ai": "ai-"}
    for e in fake.entries:
        assert e.passage.chunk_id.startswith(prefix[e.domain]), e.passage.chunk_id


def test_fixtures_cite_only_verified_sources_with_their_own_titles(fake: FakeRetriever) -> None:
    for e in fake.entries:
        url = str(e.passage.source_url)
        assert url in VERIFIED_SOURCES, url
        assert e.passage.title == VERIFIED_SOURCES[url], e.passage.chunk_id


def test_fixtures_are_short_summaries_retrieved_in_the_past(fake: FakeRetriever) -> None:
    for e in fake.entries:
        assert 120 <= len(e.passage.text) <= 700, e.passage.chunk_id
        assert e.passage.retrieved <= date.today(), e.passage.chunk_id


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("passages: [{chunk_id: x}]", "domain"),
        ("passages:\n  - {domain: legal, chunk_id: x}", "invalid"),
        ("version: 1", "'passages' list"),
        ("[unclosed", "cannot read"),
    ],
)
def test_bad_fixture_files_raise_config_error(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "passages.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_fixtures(path)


def test_duplicate_chunk_ids_raise_config_error(tmp_path: Path) -> None:
    entry = {**GOOD, "domain": "marketing"}
    path = tmp_path / "passages.yaml"
    path.write_text(json.dumps({"passages": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ConfigError, match="listed twice"):
        load_fixtures(path)


# ------------------------------------------------------------------ retrieve


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("marketing", "marketing"),
        ("marketing/strategy", "marketing"),
        ("technology", "technology/ai"),
        ("technology/ai", "technology/ai"),
        ("technology/ai/rag", "technology/ai"),
    ],
)
async def test_retrieve_filters_by_domain_prefix(
    fake: FakeRetriever, domain: str, expected: str
) -> None:
    by_id = {e.passage.chunk_id: e.domain for e in fake.entries}
    passages = await fake.retrieve("guidance", domain, k=MAX_K)
    assert passages
    assert {by_id[p.chunk_id] for p in passages} == {expected}


@pytest.mark.parametrize("domain", ["legal/contracts", "technology/web", "medical"])
async def test_retrieve_returns_empty_for_domains_without_passages(
    fake: FakeRetriever, domain: str
) -> None:
    assert await fake.retrieve("anything at all", domain) == []


async def test_retrieve_respects_k(fake: FakeRetriever) -> None:
    assert len(await fake.retrieve("email", "marketing", k=1)) == 1
    assert len(await fake.retrieve("email", "marketing")) == 5
    in_domain = sum(e.domain == "marketing" for e in fake.entries)
    assert len(await fake.retrieve("email", "marketing", k=MAX_K)) == in_domain


@pytest.mark.parametrize(
    ("query", "domain", "first"),
    [
        ("endorsement disclosure", "marketing", "mkt-ftc-endorsements-01"),
        ("email opt-out unsubscribe deadline", "marketing", "mkt-can-spam-02"),
        (
            "relevant facts buried in the middle of a long context",
            "technology/ai",
            "ai-lost-in-middle-01",
        ),
        ("prompt injection through web pages and files", "technology/ai", "ai-owasp-llm01-01"),
        ("sentence embeddings cosine similarity", "technology", "ai-sbert-01"),
    ],
)
async def test_retrieve_ranks_the_relevant_passage_first(
    fake: FakeRetriever, query: str, domain: str, first: str
) -> None:
    passages = await fake.retrieve(query, domain, k=3)
    assert passages[0].chunk_id == first, [p.chunk_id for p in passages]


async def test_retrieve_is_deterministic(fake: FakeRetriever) -> None:
    first = await fake.retrieve("search ranking content quality", "marketing", k=8)
    again = await FakeRetriever().retrieve("search ranking content quality", "marketing", k=8)
    assert first == again


async def test_no_overlap_still_fills_k_in_chunk_id_order(fake: FakeRetriever) -> None:
    passages = await fake.retrieve("zzzz qqqq", "technology/ai", k=3)
    ids = sorted(e.passage.chunk_id for e in fake.entries if e.domain == "technology/ai")
    assert [p.chunk_id for p in passages] == ids[:3]


@pytest.mark.parametrize(
    ("query", "domain", "k"),
    [
        ("", "marketing", 5),
        ("   ", "marketing", 5),
        ("q", "astrology", 5),
        ("q", "Marketing", 5),
        ("q", "marketing/", 5),
        ("q", "marketing/Bad Sub", 5),
        ("q", "", 5),
        ("q", "marketing", 0),
        ("q", "marketing", MAX_K + 1),
        ("q", "marketing", -1),
        ("q", "marketing", True),
        ("q", "marketing", 2.0),
    ],
)
async def test_bad_input_raises_retrieval_input_error(
    fake: FakeRetriever, query: str, domain: str, k: int
) -> None:
    with pytest.raises(RetrievalInputError):
        await fake.retrieve(query, domain, k)


def test_retrieval_input_error_is_an_llm_input_error() -> None:
    assert issubclass(RetrievalInputError, LLMInputError)
    assert issubclass(RetrievalInputError, ValueError)


async def test_fake_records_calls() -> None:
    fake = FakeRetriever()
    await fake.retrieve("seo basics", "marketing", k=2)
    with pytest.raises(RetrievalInputError):
        await fake.retrieve("seo basics", "marketing", k=0)
    assert fake.calls == [RetrievalCall("seo basics", "marketing", 2)]


def test_fake_satisfies_the_retriever_protocol() -> None:
    retriever: Retriever = FakeRetriever()
    assert callable(retriever.retrieve)


# ------------------------------------------------------------------ module-level calls


async def test_retrieve_uses_the_installed_retriever() -> None:
    fake = FakeRetriever()
    previous = set_retriever(fake)
    assert previous is None
    passages = await retrieve("seo basics", "marketing", k=2)
    assert len(passages) == 2
    assert fake.calls == [RetrievalCall("seo basics", "marketing", 2)]
    assert get_retriever() is fake


def test_retrieve_sync_uses_the_selected_fake() -> None:
    passages = retrieve_sync("influencer disclosure", "marketing")
    assert len(passages) == 5
    assert isinstance(get_retriever(), FakeRetriever)
    assert get_retriever().path == FIXTURES_PATH  # type: ignore[attr-defined]


def test_env_selects_the_backend_and_real_is_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.knowledge.real import RealRetriever

    monkeypatch.setenv(BACKEND_ENV, " Fake ")
    assert isinstance(get_retriever(), FakeRetriever)
    for value in ("real", " REAL "):
        set_retriever(None)
        monkeypatch.setenv(BACKEND_ENV, value)
        assert isinstance(get_retriever(), RealRetriever)
    set_retriever(None)
    monkeypatch.delenv(BACKEND_ENV)
    assert isinstance(get_retriever(), RealRetriever)  # AI-11: real is the default
    set_retriever(None)
    monkeypatch.setenv(BACKEND_ENV, "pgvector")  # a store, not a retriever
    with pytest.raises(ConfigError, match="unknown"):
        get_retriever()


# ------------------------------------------------------------------ citing in a SkillSpec


async def test_retrieved_passages_cite_into_a_valid_skillspec(fake: FakeRetriever) -> None:
    passages = await fake.retrieve("prompt injection", "technology/ai", k=2)
    data = example("ai-engineer")
    sources = [to_source(p, f"src-retrieved-{i}") for i, p in enumerate(passages, 1)]
    data["sources"] += [s.model_dump(mode="json", exclude_none=True) for s in sources]
    data["knowledge"]["references"].append(
        {
            "id": "llm-security",
            "file": "references/llm-security.md",
            "title": "LLM security",
            "sources": [s.id for s in sources],
        }
    )
    data["procedures"][0]["uses"].append("llm-security")
    result = validate_spec(data)
    assert result.ok, [str(i) for i in result.errors]
    assert not [i for i in result.warnings if i.code == "unused_source"]
