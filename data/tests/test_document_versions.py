"""A -> B -> A: a page returns to old content and the old document row must come back.

These tests load db/schema-draft.sql and then db/knowledge_views.sql into the local Postgres (root compose.yaml, port 5433)
inside one transaction and roll it back at the end. They run in a throwaway database that is created
and dropped by the tests, so the real database (where the root compose.yaml installs the schema) is never touched.
They are skipped only when the server is not reachable.
"""
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import psycopg.sql
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

DB_DIR = Path(__file__).resolve().parents[1] / "db"
# Order matters: the views read the tables, so knowledge_views.sql goes second.
SCHEMA_FILES = [DB_DIR / "schema-draft.sql", DB_DIR / "knowledge_views.sql"]
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://skillforge:skillforge_dev@localhost:5433/skillforge",
).replace("postgresql+psycopg://", "postgresql://")

HASH_A = "a" * 64
HASH_B = "b" * 64
T1 = datetime(2026, 11, 1, tzinfo=UTC)
T2 = T1 + timedelta(days=1)
T3 = T1 + timedelta(days=2)
CHUNK_CONFIG = '{"size": 500, "overlap": 50, "splitter": "sentence", "pipeline_version": "p1"}'


@pytest.fixture(scope="module")
def scratch_db_url():
    """A throwaway database on the same server, so the tests never touch the real 'knowledge' schema.

    The root compose.yaml installs the schema in the real database on its first start, so the tests
    cannot load it there. This database is created here and dropped when the module's tests are done.
    """
    try:
        admin = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    name = f"skillforge_test_{uuid.uuid4().hex[:8]}"
    admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    try:
        yield make_conninfo(DATABASE_URL, dbname=name)
    finally:
        admin.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
        admin.close()


@pytest.fixture
def db(scratch_db_url):
    conn = psycopg.connect(scratch_db_url, autocommit=False, connect_timeout=3)
    try:
        for sql_file in SCHEMA_FILES:
            conn.execute(sql_file.read_text(encoding="utf-8"))
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def source_id(db):
    return db.execute(
        "INSERT INTO knowledge.sources (url, host, source_type) "
        "VALUES ('https://example.com/p', 'example.com', 'web_page') RETURNING id"
    ).fetchone()[0]


def record(db, source_id, content_hash, fetched_at, title="Page"):
    return db.execute(
        "SELECT knowledge.record_document_version(%s, %s, %s, %s, 'MIT', 'p1')",
        (source_id, content_hash, fetched_at, title),
    ).fetchone()[0]


def doc(db, doc_id):
    return db.execute(
        "SELECT is_current, fetched_at, status FROM knowledge.documents WHERE id = %s",
        (doc_id,),
    ).fetchone()


def add_chunk(db, doc_id, chunk_id, text, index=0):
    return db.execute(
        "INSERT INTO knowledge.chunks "
        "(chunk_id, document_id, chunk_index, text, content_hash, chunk_config, chunk_config_hash) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'cfg') RETURNING id",
        (chunk_id, doc_id, index, text, "c" * 64, CHUNK_CONFIG),
    ).fetchone()[0]


def add_embedding(db, chunk_uuid):
    db.execute(
        "INSERT INTO knowledge.embeddings "
        "(chunk_id, embedding, embedding_model, embedding_version, domains) "
        "VALUES (%s, l2_normalize(array_fill(0.1::real, ARRAY[384])::vector), "
        "'local/BAAI/bge-small-en-v1.5', 'v1', ARRAY['technology/ai'])",
        (chunk_uuid,),
    )


def activate(db):
    db.execute(
        "INSERT INTO knowledge.active_config (chunk_config_hash, embedding_version) VALUES ('cfg', 'v1')"
    )


def view_chunk_ids(db):
    return [r[0] for r in db.execute("SELECT chunk_id FROM knowledge.knowledge_chunks").fetchall()]


def test_same_content_again_only_refreshes_fetched_at(db, source_id):
    a1 = record(db, source_id, HASH_A, T1)
    a2 = record(db, source_id, HASH_A, T2)
    assert a1 == a2
    assert doc(db, a1)[:2] == (True, T2)
    assert db.execute("SELECT count(*) FROM knowledge.documents").fetchone()[0] == 1


def test_new_content_replaces_the_current_version(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    b = record(db, source_id, HASH_B, T2)
    assert a != b
    assert doc(db, a)[0] is False
    assert doc(db, b)[0] is True


def test_a_b_a_brings_the_old_row_back(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    b = record(db, source_id, HASH_B, T2)
    a_again = record(db, source_id, HASH_A, T3)

    assert a_again == a, "the old row is reused, not duplicated"
    assert doc(db, a)[:2] == (True, T3), "old row is current again with the new fetched_at"
    assert doc(db, b)[0] is False
    assert db.execute("SELECT count(*) FROM knowledge.documents").fetchone()[0] == 2
    assert db.execute(
        "SELECT count(*) FROM knowledge.documents WHERE source_id = %s AND is_current", (source_id,)
    ).fetchone()[0] == 1


def test_a_b_a_makes_the_old_chunks_retrievable_again(db, source_id):
    a = record(db, source_id, HASH_A, T1, title="A")
    chunk_a = add_chunk(db, a, "chunk-a", "text of A")
    b = record(db, source_id, HASH_B, T2, title="B")
    add_chunk(db, b, "chunk-b", "text of B")
    db.execute("INSERT INTO knowledge.active_config (chunk_config_hash, embedding_version) VALUES ('cfg', 'v1')")

    def visible():
        return {r[0] for r in db.execute("SELECT chunk_id FROM knowledge.retrievable_chunks").fetchall()}

    assert visible() == {"chunk-b"}
    record(db, source_id, HASH_A, T3, title="A")
    assert visible() == {"chunk-a"}, "after A -> B -> A only A's text is retrievable"
    assert chunk_a is not None


def test_restored_document_whose_clean_text_was_deleted_is_reprocessed(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    db.execute(
        "UPDATE knowledge.documents SET status = 'embedded', clean_object_key = 'clean/a', "
        "clean_deleted_at = now() WHERE id = %s",
        (a,),
    )
    record(db, source_id, HASH_B, T2)
    record(db, source_id, HASH_A, T3)
    status, key, deleted_at = db.execute(
        "SELECT status, clean_object_key, clean_deleted_at FROM knowledge.documents WHERE id = %s", (a,)
    ).fetchone()
    assert (status, key, deleted_at) == ("fetched", None, None)


# ---- chunk_id and quality (written 28 Oct while Docker was off: not run against the database yet)


def test_the_same_chunk_id_twice_on_one_page_is_rejected(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    add_chunk(db, a, "host-aaaaaaaa-bbbbbbbb", "repeated paragraph", index=0)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_chunk(db, a, "host-aaaaaaaa-bbbbbbbb", "repeated paragraph", index=1)


def test_the_same_chunk_id_in_an_old_and_a_new_version_is_shown_once(db, source_id):
    a = record(db, source_id, HASH_A, T1, title="A")
    b = record(db, source_id, HASH_B, T2, title="B")
    for doc_id in (a, b):  # unchanged text keeps its id across versions
        add_embedding(db, add_chunk(db, doc_id, "host-aaaaaaaa-bbbbbbbb", "same text"))
    activate(db)
    assert view_chunk_ids(db) == ["host-aaaaaaaa-bbbbbbbb"]


def test_a_page_that_becomes_a_paywall_loses_its_chunks_from_the_view(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    add_embedding(db, add_chunk(db, a, "host-aaaaaaaa-bbbbbbbb", "article text"))
    activate(db)
    assert view_chunk_ids(db) == ["host-aaaaaaaa-bbbbbbbb"]
    # New bytes: the paywall page becomes the current document and has no chunks.
    paywall = record(db, source_id, HASH_B, T2, title="Sign in")
    db.execute(
        "UPDATE knowledge.documents SET quality_ok = false, quality_reasons = '{paywall_or_login}' WHERE id = %s",
        (paywall,),
    )
    assert view_chunk_ids(db) == []


def test_same_bytes_but_rejected_now_hides_the_chunks_at_once(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    add_embedding(db, add_chunk(db, a, "host-aaaaaaaa-bbbbbbbb", "article text"))
    activate(db)
    assert view_chunk_ids(db) == ["host-aaaaaaaa-bbbbbbbb"]
    # AI's thresholds changed: same HTML, new verdict. The document stays current.
    db.execute(
        "UPDATE knowledge.documents SET quality_ok = false, quality_reasons = '{too_short}' WHERE id = %s", (a,)
    )
    assert view_chunk_ids(db) == []
    db.execute("UPDATE knowledge.documents SET quality_ok = true, quality_reasons = '{}' WHERE id = %s", (a,))
    assert view_chunk_ids(db) == ["host-aaaaaaaa-bbbbbbbb"]


def test_a_page_rejected_for_injection_is_stored_with_its_screening_and_leaves_the_view(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    add_embedding(db, add_chunk(db, a, "host-aaaaaaaa-bbbbbbbb", "article text"))
    activate(db)
    assert view_chunk_ids(db) == ["host-aaaaaaaa-bbbbbbbb"]

    hostile = record(db, source_id, HASH_B, T2, title="Hostile page")
    # The shape of AI's ScreeningReport (findings, removed, invisible_chars, rejected). The database does not look inside it.
    screening = {
        "findings": [{"code": "ignore_instructions", "severity": "high", "position": 12}],
        "removed": 1,
        "invisible_chars": 0,
        "rejected": True,
    }
    db.execute(
        "UPDATE knowledge.documents SET quality_ok = false, quality_reasons = %s, screening = %s WHERE id = %s",
        (["injection"], Jsonb(screening), hostile),
    )

    assert view_chunk_ids(db) == [], "no chunks, and the old page's chunks are gone from the view"
    reasons, stored = db.execute(
        "SELECT quality_reasons, screening FROM knowledge.documents WHERE id = %s", (hostile,)
    ).fetchone()
    assert reasons == ["injection"]
    assert stored == screening, "screening is stored exactly as returned"


def test_quality_reasons_are_not_a_closed_list_but_may_not_be_blank(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    db.execute(
        "UPDATE knowledge.documents SET quality_ok = false, quality_reasons = %s WHERE id = %s",
        (["injection", "a_reason_added_next_year"], a),
    )
    for bad in ([""], ["   "], ["injection", None]):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute("UPDATE knowledge.documents SET quality_reasons = %s WHERE id = %s", (bad, a))
    # rejected, but no reason given
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE knowledge.documents SET quality_reasons = '{}' WHERE id = %s", (a,))


FINGERPRINT = "f33bf1b5f2bab420ecf719317d4e792bedd401f8957c9503cea0814553545483"  # AI's default ExtractConfig


def test_chunk_config_accepts_the_optional_fifth_key_extract_fingerprint(db, source_id):
    a = record(db, source_id, HASH_A, T1)
    five_keys = Jsonb(
        {"size": 500, "overlap": 50, "splitter": "sentence", "pipeline_version": "p1", "extract_fingerprint": FINGERPRINT}
    )
    sql = (
        "INSERT INTO knowledge.chunks (chunk_id, document_id, chunk_index, text, content_hash, chunk_config, "
        "chunk_config_hash) VALUES ('host-aaaaaaaa-bbbbbbbb', %s, 0, 'text', %s, %s, 'cfg')"
    )
    db.execute(sql, (a, "c" * 64, five_keys))
    # the four-key form still works, and anything else is still refused
    add_chunk(db, a, "host-aaaaaaaa-cccccccc", "other text", index=1)
    base = {"size": 500, "overlap": 50, "splitter": "sentence", "pipeline_version": "p1"}
    for bad in (
        {**base, "extract_fingerprint": "not-a-hash"},
        {**base, "extract_fingerprint": 123},
        {**base, "fingerprint": FINGERPRINT},  # any other name is a sixth key
        {**base, "extract_fingerprint": FINGERPRINT, "extra": 1},
    ):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(sql.replace("'host-aaaaaaaa-bbbbbbbb'", "'host-aaaaaaaa-dddddddd'"), (a, "c" * 64, Jsonb(bad)))
