"""The vector index behind the real retriever (AI-11): one interface, two backends.

    store = store_from_env()        # SKILLFORGE_VECTOR_STORE=local (default) or pgvector
    store.replace_source(url, records, vectors, model="local/BAAI/bge-small-en-v1.5")
    store.search(query_vector, "marketing/strategy", k=5)   # [(record, cosine)], best first

- LocalStore: numpy in memory, saved to SKILLFORGE_INDEX_PATH (default ai/.data/index) when
  given a path. For development, tests and evaluation.
- PgVectorStore: PostgreSQL + pgvector, installed with `pip install -e ".[pgvector]"`. Data
  Engineering owns the database: their DE-05 pipeline writes the chunks (with our
  ingest_pages / extract_page / embed) and exposes a read-only view, SKILLFORGE_PGVECTOR_TABLE
  (default knowledge_chunks; schema-qualified works, e.g. knowledge.knowledge_chunks). This
  backend only reads it, as a read-only database user; writing is opt-in, for tests and local
  databases (SKILLFORGE_PGVECTOR_WRITABLE=1).

A chunk serves one or more domains. Both backends use the A4 domain rule on each of them
(equal, or one a path prefix of the other) and refuse vectors from a different embedding
model than the index holds: they would not be comparable.
"""

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
from pydantic import Field, HttpUrl, field_validator

from core.knowledge.retrieval import RetrievalInputError, check_domain, domains_match
from core.knowledge.types import ChunkId, Passage, PassageText
from core.llm.errors import ConfigError
from core.spec.models import Line, SpecModel

if TYPE_CHECKING:
    from core.knowledge.extract import Chunk

STORE_ENV = "SKILLFORGE_VECTOR_STORE"
INDEX_PATH_ENV = "SKILLFORGE_INDEX_PATH"
PGVECTOR_DSN_ENV = "SKILLFORGE_PGVECTOR_DSN"
PGVECTOR_TABLE_ENV = "SKILLFORGE_PGVECTOR_TABLE"
PGVECTOR_WRITABLE_ENV = "SKILLFORGE_PGVECTOR_WRITABLE"
DEFAULT_PG_TABLE = "knowledge_chunks"
DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[2] / ".data" / "index"


class ChunkRecord(SpecModel):
    """One indexed chunk: an AI-10 Chunk's citation fields plus the domains it serves."""

    chunk_id: ChunkId
    source_url: HttpUrl
    title: Line
    retrieved: date
    text: PassageText
    section: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    domains: list[str] = Field(min_length=1)  # SkillSpec domains or areas, no repeats

    @field_validator("domains")
    @classmethod
    def _known_domains(cls, domains: list[str]) -> list[str]:
        for domain in domains:
            try:
                check_domain(domain)
            except RetrievalInputError as exc:
                raise ValueError(str(exc)) from exc
        if len(set(domains)) != len(domains):
            raise ValueError(f"repeated domain in {domains}")
        return domains

    @classmethod
    def from_chunk(cls, chunk: "Chunk", domains: Sequence[str]) -> "ChunkRecord":
        return cls(
            chunk_id=chunk.chunk_id,
            source_url=chunk.source_url,
            title=chunk.title,
            retrieved=chunk.retrieved,
            text=chunk.text,
            section=chunk.section,
            concepts=chunk.concepts,
            content_hash=chunk.content_hash,
            domains=list(domains),
        )

    def serves(self, domain: str) -> bool:
        """The A4 domain rule, on any of the chunk's domains."""
        return any(domains_match(mine, domain) for mine in self.domains)

    def to_passage(self) -> Passage:
        return Passage(
            chunk_id=self.chunk_id,
            text=self.text,
            source_url=self.source_url,
            title=self.title,
            retrieved=self.retrieved,
        )


@dataclass(frozen=True)
class StoreInfo:
    count: int
    model: str | None  # the embedding model the index was built with; None while empty
    dimensions: int | None


class VectorStore(Protocol):
    def info(self) -> StoreInfo: ...

    def replace_source(
        self,
        url: str,
        records: Sequence[ChunkRecord],
        vectors: Sequence[Sequence[float]],
        *,
        model: str,
    ) -> None:
        """Drop every chunk of `url`, then add `records` (one vector each). Empty `records`
        just removes the page, e.g. when it turned into a paywall."""
        ...

    def search(
        self, vector: Sequence[float], domain: str, k: int
    ) -> list[tuple[ChunkRecord, float]]:
        """At most `k` chunks in `domain`, by cosine similarity, best first (ties by id)."""
        ...


def check_model(info: StoreInfo, model: str, dimensions: int) -> None:
    """Raise ConfigError when vectors of `model` cannot go with what the index holds."""
    if info.count and (info.model != model or info.dimensions != dimensions):
        raise ConfigError(
            f"the index holds {info.dimensions}-dimension vectors from {info.model}, not "
            f"{dimensions}-dimension vectors from {model}; rebuild the index (ingest again)"
        )


def _unit(vectors: Any) -> Any:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


# ------------------------------------------------------------------ local backend


class LocalStore:
    """In-memory index; with a `path`, loaded from and saved to that folder on every change."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._records: list[ChunkRecord] = []
        self._vectors = np.zeros((0, 0), dtype=np.float32)
        self._model: str | None = None
        self._loaded = path is None

    def records(self) -> list[ChunkRecord]:
        self._load()
        return list(self._records)

    def info(self) -> StoreInfo:
        self._load()
        dims = int(self._vectors.shape[1]) if self._records else None
        return StoreInfo(len(self._records), self._model if self._records else None, dims)

    def replace_source(
        self,
        url: str,
        records: Sequence[ChunkRecord],
        vectors: Sequence[Sequence[float]],
        *,
        model: str,
    ) -> None:
        self._load()
        if len(records) != len(vectors):
            raise ValueError(f"{len(records)} records but {len(vectors)} vectors")
        new = _unit(vectors) if records else None
        if new is not None:
            check_model(self.info(), model, int(new.shape[1]))
        keep = [i for i, r in enumerate(self._records) if str(r.source_url) != url]
        self._records = [self._records[i] for i in keep] + list(records)
        old = self._vectors[keep] if keep else None
        parts = [m for m in (old, new) if m is not None and len(m)]
        self._vectors = np.vstack(parts) if parts else np.zeros((0, 0), dtype=np.float32)
        if records:
            self._model = model
        self._save()

    def search(
        self, vector: Sequence[float], domain: str, k: int
    ) -> list[tuple[ChunkRecord, float]]:
        self._load()
        candidates = [i for i, r in enumerate(self._records) if r.serves(domain)]
        if not candidates:
            return []
        if len(vector) != self._vectors.shape[1]:
            raise ConfigError(
                f"query vector has {len(vector)} dimensions, the index {self._vectors.shape[1]}"
            )
        scores = self._vectors[candidates] @ _unit(vector)
        ranked = sorted(
            zip(candidates, scores.tolist(), strict=True),
            key=lambda pair: (-round(pair[1], 6), self._records[pair[0]].chunk_id),
        )
        return [(self._records[i], float(score)) for i, score in ranked[:k]]

    # Files: records.jsonl (one ChunkRecord per line), vectors.npy (unit length, float32, same
    # order) and meta.json (model, dimensions, count). Each is written to a temporary name and
    # renamed, so a crash never leaves a half-written index.

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        assert self.path is not None
        meta_file = self.path / "meta.json"
        if not meta_file.is_file():
            return
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        lines = (self.path / "records.jsonl").read_text(encoding="utf-8").splitlines()
        self._records = [_read_record(line) for line in lines if line]
        self._vectors = np.load(self.path / "vectors.npy")
        self._model = meta["model"]
        if len(self._records) != meta["count"] or len(self._vectors) != meta["count"]:
            raise ConfigError(f"index at {self.path} is inconsistent; rebuild it (ingest again)")

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.mkdir(parents=True, exist_ok=True)
        records = "".join(r.model_dump_json() + "\n" for r in self._records)
        meta = {
            "model": self._model if self._records else None,
            "dimensions": int(self._vectors.shape[1]) if self._records else None,
            "count": len(self._records),
        }
        _atomic_write(self.path / "records.jsonl", records.encode("utf-8"))
        tmp = self.path / "vectors.npy.tmp"
        with tmp.open("wb") as f:
            np.save(f, self._vectors)
        os.replace(tmp, self.path / "vectors.npy")
        _atomic_write(self.path / "meta.json", json.dumps(meta, indent=2).encode("utf-8"))


def _read_record(line: str) -> ChunkRecord:
    """One records.jsonl line. Indexes saved before chunks had several domains hold one
    `domain` string: it is read as `domains: [domain]`."""
    if '"domain":' in line:
        data = json.loads(line)
        if "domain" in data and "domains" not in data:
            data["domains"] = [data.pop("domain")]
            line = json.dumps(data)
    return ChunkRecord.model_validate_json(line)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomic, and replaces an existing file on Windows too


# ------------------------------------------------------------------ pgvector backend

PG_COLUMNS = (
    "chunk_id", "source_url", "title", "retrieved", "text", "section", "concepts",
    "content_hash", "domains",
)  # fmt: skip
# The A4 domain rule in SQL, on each of a row's domains: a row matches when one of its domains
# is the query domain or a parent of it (`&&`, which a GIN index on the base table serves), or
# lies under it (LIKE). Domains are lowercase kebab-case paths, so they hold no LIKE wildcards.
PG_DOMAIN_CLAUSE = (
    "(domains && %(domain_and_parents)s::text[] "
    "OR EXISTS (SELECT 1 FROM unnest(domains) AS d WHERE d LIKE %(domain_prefix)s))"
)
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
READ_ONLY = (
    "this pgvector store is read-only: Data Engineering's DE-05 pipeline writes the chunks "
    "(with ingest_pages / extract_page / embed). For a test or local database, pass "
    f"writable=True or set {PGVECTOR_WRITABLE_ENV}=1"
)


def pg_name(name: str) -> str:
    """A table or view name, optionally schema-qualified, quoted for SQL:
    knowledge.knowledge_chunks -> "knowledge"."knowledge_chunks". Lowercase identifiers only
    (what unquoted names become in PostgreSQL), so quoting never changes which object it is."""
    parts = name.split(".")
    if not 1 <= len(parts) <= 2 or not all(_IDENTIFIER.match(p) for p in parts):
        raise ConfigError(
            f"bad table name {name!r}: use name or schema.name, lowercase letters, digits, _"
        )
    return ".".join(f'"{p}"' for p in parts)


def pg_schema(table: str, dimensions: int) -> str:
    """The base table for tests and local databases: one row per chunk. In production DE owns
    the tables and exposes a view with these columns (see pg_view_sql)."""
    name, base = pg_name(table), table.split(".")[-1]
    schema = table.split(".")[0] if "." in table else None
    create_schema = f'CREATE SCHEMA IF NOT EXISTS "{schema}";\n' if schema else ""
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
{create_schema}CREATE TABLE IF NOT EXISTS {name} (
    chunk_id        text PRIMARY KEY,
    source_url      text NOT NULL,
    title           text NOT NULL,
    retrieved       date NOT NULL,
    text            text NOT NULL,
    section         text[] NOT NULL DEFAULT '{{}}',
    concepts        text[] NOT NULL DEFAULT '{{}}',
    content_hash    char(64) NOT NULL,
    domains         text[] NOT NULL CHECK (cardinality(domains) > 0),
    embedding_model text NOT NULL,
    embedding       vector({dimensions}) NOT NULL
);
-- HNSW (cosine) on the base table: a view cannot be indexed, but a query through a plain
-- view (no GROUP BY or DISTINCT) still uses this index.
CREATE INDEX IF NOT EXISTS "{base}_embedding_idx"
    ON {name} USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS "{base}_source_idx" ON {name} (source_url);
-- GIN on domains: serves `domains && ARRAY[domain and its parents]`.
CREATE INDEX IF NOT EXISTS "{base}_domains_idx" ON {name} USING gin (domains);
""".strip()


def pg_view_sql(view: str, table: str) -> str:
    """Example of the read-only view AI reads, over a base table with the same columns."""
    columns = ",\n    ".join((*PG_COLUMNS, "embedding_model", "embedding"))
    return (
        f"CREATE OR REPLACE VIEW {pg_name(view)} AS\nSELECT\n    {columns}\nFROM {pg_name(table)};"
    )


def pg_search_sql(table: str) -> str:
    columns = ", ".join(PG_COLUMNS)
    return (
        f"SELECT {columns}, 1 - (embedding <=> %(vector)s) AS score FROM {pg_name(table)} "
        f"WHERE {PG_DOMAIN_CLAUSE} ORDER BY embedding <=> %(vector)s, chunk_id LIMIT %(k)s"
    )


def pg_search_params(vector: Sequence[float], domain: str, k: int) -> dict[str, Any]:
    parts = domain.split("/")
    return {
        "vector": np.asarray(vector, dtype=np.float32),
        "domain_and_parents": ["/".join(parts[: i + 1]) for i in range(len(parts))],
        "domain_prefix": f"{domain}/%",
        "k": k,
    }


class PgVectorStore:
    """Reads chunks from PostgreSQL + pgvector. `dsn` is a libpq connection string
    (SKILLFORGE_PGVECTOR_DSN), for a read-only database user in production; `table` is a
    table or view, optionally schema-qualified (SKILLFORGE_PGVECTOR_TABLE).

    Read-only unless `writable`: every transaction is READ ONLY, and replace_source and
    create_schema refuse. Production writes go through Data Engineering's pipeline.

    With filtered HNSW search, pgvector may return fewer than `k` rows; pgvector 0.8+ fixes
    this with `SET hnsw.iterative_scan = relaxed_order` (see docs/ai/retrieval.md).
    """

    def __init__(self, dsn: str, *, table: str = DEFAULT_PG_TABLE, writable: bool = False) -> None:
        self.dsn, self.table, self.writable = dsn, table, writable
        self.name = pg_name(table)

    def _connect(self) -> Any:
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:  # the optional extra is not installed
            raise ConfigError('install the pgvector extra: pip install -e ".[pgvector]"') from exc
        conn = psycopg.connect(self.dsn)
        conn.read_only = not self.writable  # a second guard on top of a read-only user
        register_vector(conn)
        return conn

    def _check_writable(self) -> None:
        if not self.writable:
            raise ConfigError(READ_ONLY)

    def create_schema(self, dimensions: int) -> None:
        self._check_writable()
        with self._connect() as conn:
            conn.execute(pg_schema(self.table, dimensions))

    def info(self) -> StoreInfo:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT count(*), min(embedding_model), max(vector_dims(embedding)) "
                f"FROM {self.name}"
            ).fetchone()
        count, model, dims = row
        return StoreInfo(int(count), model, int(dims) if dims is not None else None)

    def replace_source(
        self,
        url: str,
        records: Sequence[ChunkRecord],
        vectors: Sequence[Sequence[float]],
        *,
        model: str,
    ) -> None:
        self._check_writable()
        if len(records) != len(vectors):
            raise ValueError(f"{len(records)} records but {len(vectors)} vectors")
        if records:
            check_model(self.info(), model, len(vectors[0]))
        placeholders = ", ".join(f"%({c})s" for c in (*PG_COLUMNS, "embedding_model", "embedding"))
        insert = (
            f"INSERT INTO {self.name} ({', '.join(PG_COLUMNS)}, embedding_model, embedding) "
            f"VALUES ({placeholders}) ON CONFLICT (chunk_id) DO UPDATE SET "
            + ", ".join(
                f"{c} = EXCLUDED.{c}" for c in (*PG_COLUMNS[1:], "embedding_model", "embedding")
            )
        )
        rows = [
            {
                **record.model_dump(mode="json"),
                "retrieved": record.retrieved,
                "embedding_model": model,
                "embedding": vector,
            }
            for record, vector in zip(records, _unit(vectors) if records else [], strict=True)
        ]
        with self._connect() as conn, conn.transaction():
            conn.execute(f"DELETE FROM {self.name} WHERE source_url = %s", (url,))
            if rows:
                conn.cursor().executemany(insert, rows)

    def search(
        self, vector: Sequence[float], domain: str, k: int
    ) -> list[tuple[ChunkRecord, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                pg_search_sql(self.table), pg_search_params(vector, domain, k)
            ).fetchall()
        results = []
        for row in rows:
            data = dict(zip(PG_COLUMNS, row[:-1], strict=True))
            data["retrieved"] = str(data["retrieved"])
            data["content_hash"] = data["content_hash"].strip()
            results.append((ChunkRecord.model_validate_json(json.dumps(data)), float(row[-1])))
        return results


def store_from_env() -> VectorStore:
    backend = os.environ.get(STORE_ENV, "local").strip().lower()
    if backend == "local":
        return LocalStore(Path(os.environ.get(INDEX_PATH_ENV) or DEFAULT_INDEX_PATH))
    if backend == "pgvector":
        dsn = os.environ.get(PGVECTOR_DSN_ENV)
        if not dsn:
            raise ConfigError(f"{STORE_ENV}=pgvector needs {PGVECTOR_DSN_ENV}")
        table = os.environ.get(PGVECTOR_TABLE_ENV, "").strip() or DEFAULT_PG_TABLE
        writable = os.environ.get(PGVECTOR_WRITABLE_ENV, "").strip().lower() in {"1", "true", "yes"}
        return PgVectorStore(dsn, table=table, writable=writable)
    raise ConfigError(f"unknown {STORE_ENV}={backend!r}; use 'local' or 'pgvector'")
