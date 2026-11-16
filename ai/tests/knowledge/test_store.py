"""The knowledge index (AI-11): LocalStore behaviour and persistence, and the pgvector SQL."""

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import pytest
from pydantic import HttpUrl

from core.knowledge.ingest import Page, ingest_pages
from core.knowledge.retrieval import RetrievalInputError
from core.knowledge.store import (
    INDEX_PATH_ENV,
    PGVECTOR_DSN_ENV,
    PGVECTOR_TABLE_ENV,
    PGVECTOR_WRITABLE_ENV,
    STORE_ENV,
    ChunkRecord,
    LocalStore,
    PgVectorStore,
    pg_name,
    pg_schema,
    pg_search_params,
    pg_search_sql,
    pg_view_sql,
    store_from_env,
)
from core.llm import ConfigError

MODEL = "local/BAAI/bge-small-en-v1.5"


def record(url: str, n: int, *domains: str) -> ChunkRecord:
    text = f"Chunk {n} of {url} says one thing."
    return ChunkRecord(
        chunk_id=f"example.org-{n:08d}-{hashlib.sha256(url.encode()).hexdigest()[:8]}",
        source_url=HttpUrl(url),
        title="Example",
        retrieved=date(2026, 10, 25),
        text=text,
        section=["Heading"],
        concepts=["thing"],
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        domains=list(domains or ["marketing"]),
    )


A, B, C = "https://a.example/", "https://b.example/", "https://c.example/"


def filled(path: Path | None = None) -> LocalStore:
    store = LocalStore(path)
    store.replace_source(A, [record(A, 1), record(A, 2)], [[1, 0, 0], [0.9, 0.1, 0]], model=MODEL)
    store.replace_source(B, [record(B, 3, "marketing/email")], [[0, 1, 0]], model=MODEL)
    store.replace_source(C, [record(C, 4, "technology/ai")], [[1, 0, 0]], model=MODEL)
    return store


def ids(results: list[tuple[ChunkRecord, float]]) -> list[str]:
    return [r.chunk_id[:20] for r, _ in results]


def test_search_ranks_by_cosine_within_the_domain() -> None:
    store = filled()
    results = store.search([1, 0, 0], "marketing", 5)
    assert [str(r.source_url) for r, _ in results] == [A, A, B]  # C is technology/ai
    assert results[0][1] == pytest.approx(1.0)
    assert results[0][1] >= results[1][1] >= results[2][1]
    # "marketing/email" also matches pages indexed as "marketing" (a path prefix), not C.
    assert {str(r.source_url) for r, _ in store.search([0, 1, 0], "marketing/email", 5)} == {A, B}
    assert store.search([1, 0, 0], "legal", 5) == []
    assert len(store.search([1, 0, 0], "marketing", 1)) == 1


def test_domains_match_by_path_prefix_like_a4() -> None:
    store = filled()
    assert {str(r.source_url) for r, _ in store.search([1, 0, 0], "marketing/strategy", 5)} == {A}
    assert {str(r.source_url) for r, _ in store.search([1, 0, 0], "technology", 5)} == {C}


def test_a_chunk_with_several_domains_matches_any_of_them() -> None:
    store = LocalStore()
    both = record(A, 1, "marketing/strategy", "legal/contracts")
    store.replace_source(A, [both], [[1, 0]], model=MODEL)
    for domain in ("marketing", "marketing/strategy", "legal", "legal/contracts"):
        assert [r.chunk_id for r, _ in store.search([1, 0], domain, 5)] == [both.chunk_id]
    assert store.search([1, 0], "marketing/email", 5) == []  # a sibling, not a prefix
    assert store.search([1, 0], "technology", 5) == []
    assert both.to_passage() == record(A, 1).to_passage()  # the A4 Passage is unchanged


def test_domains_are_checked() -> None:
    with pytest.raises(ValueError, match="known area"):
        record(A, 1, "astrology")
    with pytest.raises(ValueError, match="repeated"):
        record(A, 1, "marketing", "marketing")
    with pytest.raises(ValueError):
        ChunkRecord.model_validate({**record(A, 1).model_dump(), "domains": []})


def test_an_index_saved_with_one_domain_per_chunk_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "index"
    filled(path)
    lines = (path / "records.jsonl").read_text(encoding="utf-8").splitlines()
    old = []
    for line in lines:  # the format before `domains`: one `domain` string
        data = json.loads(line)
        data["domain"] = data.pop("domains")[0]
        old.append(json.dumps(data))
    (path / "records.jsonl").write_text("\n".join(old) + "\n", encoding="utf-8")
    reloaded = LocalStore(path)
    assert [r.domains for r in reloaded.records()][-1] == ["technology/ai"]
    assert reloaded.search([1, 0, 0], "marketing", 5) == filled().search([1, 0, 0], "marketing", 5)


def test_a_page_takes_one_or_more_domains() -> None:
    assert Page("", "https://a.example/", date(2026, 10, 26), "marketing").domains == ("marketing",)
    page = Page("", A, date(2026, 10, 26), ["legal/contracts", "marketing", "legal/contracts"])
    assert page.domains == ("legal/contracts", "marketing")  # repeats dropped, order kept


async def test_ingest_refuses_a_page_without_a_known_domain() -> None:
    for domains in ([], ["marketing", "astrology"]):
        with pytest.raises(RetrievalInputError):
            await ingest_pages([Page("", A, date(2026, 10, 26), domains)], store=LocalStore())


def test_ties_are_broken_by_chunk_id() -> None:
    store = LocalStore()
    store.replace_source(A, [record(A, 2), record(A, 1)], [[1, 0], [1, 0]], model=MODEL)
    assert [r.chunk_id for r, _ in store.search([1, 0], "marketing", 2)] == sorted(
        r.chunk_id for r in store.records()
    )


def test_replace_source_replaces_and_empty_records_remove_the_page() -> None:
    store = filled()
    store.replace_source(A, [record(A, 9)], [[0, 0, 1]], model=MODEL)
    assert [r.chunk_id for r in store.records() if str(r.source_url) == A] == [
        record(A, 9).chunk_id
    ]
    store.replace_source(A, [], [], model=MODEL)
    assert all(str(r.source_url) != A for r in store.records())
    assert store.info().count == 2


def test_vectors_of_another_model_are_refused() -> None:
    store = filled()
    with pytest.raises(ConfigError, match="rebuild the index"):
        store.replace_source(B, [record(B, 5)], [[0, 1, 0]], model="local/other/model")
    with pytest.raises(ConfigError, match="rebuild the index"):
        store.replace_source(B, [record(B, 5)], [[0, 1, 0, 0]], model=MODEL)  # 4 dimensions
    with pytest.raises(ConfigError, match="dimensions"):
        store.search([1, 0], "marketing", 5)
    with pytest.raises(ValueError):
        store.replace_source(B, [record(B, 5)], [], model=MODEL)


def test_info_of_an_empty_store() -> None:
    info = LocalStore().info()
    assert (info.count, info.model, info.dimensions) == (0, None, None)
    filled_info = filled().info()
    assert (filled_info.count, filled_info.model, filled_info.dimensions) == (4, MODEL, 3)


def test_a_saved_index_loads_again_with_the_same_results(tmp_path: Path) -> None:
    path = tmp_path / "index"
    before = filled(path).search([0.5, 0.5, 0], "marketing", 5)
    reloaded = LocalStore(path)
    assert reloaded.search([0.5, 0.5, 0], "marketing", 5) == before
    assert reloaded.info() == filled().info()
    assert sorted(p.name for p in path.iterdir()) == ["meta.json", "records.jsonl", "vectors.npy"]
    reloaded.replace_source(B, [], [], model=MODEL)  # saving again replaces existing files
    assert LocalStore(path).info().count == 3


def test_an_inconsistent_index_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "index"
    filled(path)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    (path / "meta.json").write_text(json.dumps({**meta, "count": 99}), encoding="utf-8")
    with pytest.raises(ConfigError, match="inconsistent"):
        LocalStore(path).info()


def test_a_record_cites_as_an_a4_passage() -> None:
    passage = record(A, 1).to_passage()
    assert set(passage.model_dump()) == {"chunk_id", "text", "source_url", "title", "retrieved"}


# ------------------------------------------------------------------ backends from env


def test_store_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(INDEX_PATH_ENV, str(tmp_path / "x"))
    store = store_from_env()
    assert isinstance(store, LocalStore) and store.path == tmp_path / "x"
    monkeypatch.setenv(STORE_ENV, "pgvector")
    monkeypatch.delenv(PGVECTOR_DSN_ENV, raising=False)
    with pytest.raises(ConfigError, match=PGVECTOR_DSN_ENV):
        store_from_env()
    monkeypatch.setenv(PGVECTOR_DSN_ENV, "postgresql://u@h/db")
    monkeypatch.delenv(PGVECTOR_TABLE_ENV, raising=False)
    monkeypatch.delenv(PGVECTOR_WRITABLE_ENV, raising=False)
    pg = store_from_env()
    assert isinstance(pg, PgVectorStore)
    assert (pg.table, pg.writable) == ("knowledge_chunks", False)  # read-only by default
    monkeypatch.setenv(PGVECTOR_TABLE_ENV, "knowledge.knowledge_chunks")
    monkeypatch.setenv(PGVECTOR_WRITABLE_ENV, "1")
    pg = store_from_env()
    assert isinstance(pg, PgVectorStore)
    assert (pg.name, pg.writable) == ('"knowledge"."knowledge_chunks"', True)
    monkeypatch.setenv(STORE_ENV, "faiss")
    with pytest.raises(ConfigError, match="unknown"):
        store_from_env()


# ------------------------------------------------------------------ pgvector SQL (no database)


def test_pgvector_schema_and_search_sql() -> None:
    schema = pg_schema("knowledge.ai_chunks", 384)
    assert 'CREATE SCHEMA IF NOT EXISTS "knowledge";' in schema
    assert 'CREATE TABLE IF NOT EXISTS "knowledge"."ai_chunks"' in schema
    assert "embedding       vector(384) NOT NULL" in schema
    assert "domains         text[] NOT NULL CHECK (cardinality(domains) > 0)" in schema
    assert 'ON "knowledge"."ai_chunks" USING hnsw (embedding vector_cosine_ops)' in schema
    assert '"ai_chunks_domains_idx" ON "knowledge"."ai_chunks" USING gin (domains)' in schema
    assert "CREATE SCHEMA" not in pg_schema("knowledge_chunks", 384)
    sql = pg_search_sql("knowledge.knowledge_chunks")
    assert 'FROM "knowledge"."knowledge_chunks" WHERE' in sql
    assert "ORDER BY embedding <=> %(vector)s, chunk_id LIMIT %(k)s" in sql
    assert "domains && %(domain_and_parents)s::text[]" in sql
    assert "unnest(domains) AS d WHERE d LIKE %(domain_prefix)s" in sql
    params = pg_search_params([1.0, 0.0], "marketing/email", 5)
    assert params["domain_and_parents"] == ["marketing", "marketing/email"]
    assert params["domain_prefix"] == "marketing/email/%" and params["k"] == 5
    assert pg_search_params([1.0], "legal", 1)["domain_and_parents"] == ["legal"]


@pytest.mark.parametrize(
    ("domains", "query", "matches"),
    [
        (["marketing/strategy", "legal/contracts"], "legal", True),  # a child of the query
        (["marketing/strategy", "legal/contracts"], "legal/contracts", True),  # equal
        (["marketing"], "marketing/email", True),  # a parent of the query
        (["marketing/strategy"], "marketing/email", False),  # a sibling
        (["legal/contracts"], "legal/contract", False),  # not a path prefix
    ],
)
def test_the_sql_domain_rule_agrees_with_the_local_store(
    domains: list[str], query: str, matches: bool
) -> None:
    """The two SQL conditions, evaluated in Python, match ChunkRecord.serves."""
    params = pg_search_params([1.0], query, 1)
    overlap = bool(set(domains) & set(params["domain_and_parents"]))
    under = any(d.startswith(params["domain_prefix"][:-1]) for d in domains)
    assert (overlap or under) is matches is record(A, 1, *domains).serves(query)


def test_the_example_view_exposes_our_columns() -> None:
    view = pg_view_sql("knowledge.knowledge_chunks", "knowledge.ai_chunks")
    assert view.startswith('CREATE OR REPLACE VIEW "knowledge"."knowledge_chunks" AS')
    assert view.endswith('FROM "knowledge"."ai_chunks";')
    for column in ("chunk_id", "domains", "embedding_model", "embedding"):
        assert f"    {column}" in view


@pytest.mark.parametrize(
    ("name", "quoted"),
    [
        ("knowledge_chunks", '"knowledge_chunks"'),
        ("knowledge.knowledge_chunks", '"knowledge"."knowledge_chunks"'),
        ("_x1", '"_x1"'),
    ],
)
def test_pgvector_names_are_quoted(name: str, quoted: str) -> None:
    assert pg_name(name) == quoted
    assert PgVectorStore("postgresql://u@h/db", table=name).name == quoted


@pytest.mark.parametrize(
    "name",
    [
        "chunks; DROP TABLE users",
        'knowledge"."x',
        "Knowledge.Chunks",  # quoting would make it case-sensitive: refuse, use lowercase
        "a.b.c",
        "",
        "1chunks",
        "knowledge.",
    ],
)
def test_pgvector_bad_names_are_refused(name: str) -> None:
    with pytest.raises(ConfigError, match="table name"):
        PgVectorStore("postgresql://u@h/db", table=name)


def test_pgvector_store_is_read_only_unless_asked() -> None:
    store = PgVectorStore("postgresql://u@h/db")  # never connects: the refusal comes first
    with pytest.raises(ConfigError, match="read-only"):
        store.replace_source(A, [record(A, 1)], [[1, 0]], model=MODEL)
    with pytest.raises(ConfigError, match="read-only"):
        store.create_schema(384)


@pytest.mark.pgvector
def test_pgvector_round_trip() -> None:
    """Opt-in: `pytest -m pgvector` with SKILLFORGE_PGVECTOR_DSN pointing at a test database
    whose user may create tables. Writes a base table, then reads it through a view."""
    dsn = os.environ.get(PGVECTOR_DSN_ENV)
    if not dsn:
        pytest.skip(f"{PGVECTOR_DSN_ENV} not set")
    store = PgVectorStore(dsn, table="skillforge_test_chunks", writable=True)
    store.create_schema(3)
    try:
        store.replace_source(A, [record(A, 1), record(A, 2)], [[1, 0, 0], [0, 1, 0]], model=MODEL)
        both = record(C, 4, "technology/ai", "legal/contracts")
        store.replace_source(C, [both], [[1, 0, 0]], model=MODEL)
        with store._connect() as conn:
            conn.execute(pg_view_sql("skillforge_test_view", "skillforge_test_chunks"))
        view = PgVectorStore(dsn, table="skillforge_test_view")  # read-only, like production
        results = view.search([1, 0, 0], "marketing/strategy", 5)
        assert [str(r.source_url) for r, _ in results] == [A, A]
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)
        assert [r.domains for r, _ in view.search([1, 0, 0], "legal", 5)] == [both.domains]
        assert view.info().count == 3 and view.info().model == MODEL
        with pytest.raises(ConfigError, match="read-only"):
            view.replace_source(A, [], [], model=MODEL)
    finally:
        with store._connect() as conn:
            conn.execute("DROP VIEW IF EXISTS skillforge_test_view")
            conn.execute("DROP TABLE IF EXISTS skillforge_test_chunks")
