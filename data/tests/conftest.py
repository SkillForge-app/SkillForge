"""Shared fixtures: a throwaway Postgres database with the schema loaded (never the real database).

The root compose.yaml installs the schema in the real database on its first start, so tests cannot load it
there. A database is created once per test session on the same server, the schema and the views are loaded
into it (committed), and it is dropped at the end. Each test gets a connection inside a transaction that is
rolled back, so tests do not see each other's rows. Tests are skipped only if the server is not reachable.
"""
import os
import uuid
from pathlib import Path

import psycopg
import psycopg.sql
import pytest
from psycopg.conninfo import make_conninfo

DB_DIR = Path(__file__).resolve().parents[1] / "db"
# Order matters: the views read the tables, so knowledge_views.sql goes second.
SCHEMA_FILES = [DB_DIR / "schema-draft.sql", DB_DIR / "knowledge_views.sql"]
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://skillforge:skillforge_dev@127.0.0.1:5433/skillforge",
).replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session")
def scratch_db_url():
    try:
        admin = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    name = f"skillforge_test_{uuid.uuid4().hex[:8]}"
    admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = make_conninfo(DATABASE_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as setup:
            for sql_file in SCHEMA_FILES:
                setup.execute(sql_file.read_text(encoding="utf-8"))
        yield url
    finally:
        admin.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
        admin.close()


@pytest.fixture
def db(scratch_db_url):
    conn = psycopg.connect(scratch_db_url, autocommit=False, connect_timeout=3)
    try:
        # Open the transaction now: code under test that uses `conn.transaction()` then gets a savepoint,
        # not its own COMMIT, and the rollback below removes everything the test wrote.
        conn.execute("SELECT 1")
        yield conn
    finally:
        conn.rollback()
        conn.close()
