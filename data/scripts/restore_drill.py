"""DE-14: a backup and restore drill for the `knowledge` schema, on throwaway databases inside the EXISTING Postgres container.

    python scripts/restore_drill.py [--chunks 2000] [--container skillforge-postgres]

What it does (all inside the one container; no new container, no network):
  1. creates a source database `drill_src_<id>`, loads `db/schema-draft.sql` + `db/knowledge_views.sql`, loads a small data set with
     `bench/generate.sql` (random unit vectors, 10 chunks per document) and builds the HNSW index like the real schema does;
  2. `pg_dump -Fc -n knowledge` of the source (the backup);
  3. creates a second database `drill_dst_<id>`, `CREATE EXTENSION vector`, `pg_restore` (the restore, which rebuilds the HNSW index);
  4. checks: the row count of every table is equal; the HNSW index exists, is valid and is the one the planner uses; the views and
     `record_document_version()` exist; similarity queries give the same answers (the exact top 10 must be identical; the HNSW search must find the query's own
     chunk first and its recall must not drop: two builds of an HNSW graph are not the same graph, so the approximate sets can differ);
  5. drops both databases and the dump file, also when something fails.

It never touches the real database `skillforge`, and it only drops databases whose name starts with `drill_` and that it created itself.
Exit code 0 = the drill passed, 1 = it failed. The result is printed as a table (copy it into docs/backup-restore.md).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

DATA = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://skillforge:skillforge_dev@127.0.0.1:5433/skillforge").replace("postgresql+psycopg://", "postgresql://")
TABLES = ["sources", "source_domains", "crawl_runs", "documents", "chunks", "embeddings", "active_config"]
VIEWS = ["chunk_provenance", "retrievable_chunks", "knowledge_chunks"]
QUERIES = 10      # query vectors: the first 10 stored embeddings, by chunk id


def docker(container: str, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", "exec", *(["-i"] if stdin is not None else []), container, *args], input=stdin,
                          capture_output=True, check=False, env={**os.environ, "MSYS_NO_PATHCONV": "1"})


def must(done: subprocess.CompletedProcess[bytes], what: str) -> None:
    if done.returncode != 0:
        raise RuntimeError(f"{what} failed: {done.stderr.decode(errors='replace')[-600:]}")


def psql(container: str, database: str, *, sql_file: Path | None = None, command: str | None = None, variables: dict[str, str] | None = None):
    args = ["psql", "-U", "skillforge", "-d", database, "-v", "ON_ERROR_STOP=1", "-q"]
    for key, value in (variables or {}).items():
        args += ["-v", f"{key}={value}"]
    if command is not None:
        return docker(container, *args, "-c", command)
    assert sql_file is not None
    return docker(container, *args, stdin=sql_file.read_bytes())


def connect(name: str) -> psycopg.Connection:
    return psycopg.connect(make_conninfo(DATABASE_URL, dbname=name), autocommit=True, connect_timeout=5)


def counts(name: str) -> dict[str, int]:
    with connect(name) as conn:
        return {t: conn.execute(f"SELECT count(*) FROM knowledge.{t}").fetchone()[0] for t in TABLES}


def checks(src: str, dst: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    a, b = counts(src), counts(dst)
    results.append(("row counts equal in every table", a == b, ", ".join(f"{t}={a[t]}/{b[t]}" for t in TABLES)))
    with connect(dst) as conn:
        index = conn.execute(
            "SELECT i.indisvalid, am.amname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname = 'embeddings_hnsw_cosine_idx'").fetchone()
        results.append(("HNSW index exists and is valid", bool(index and index[0] and index[1] == "hnsw"), str(index)))
        conn.execute("ANALYZE knowledge.embeddings")
        plan = "\n".join(r[0] for r in conn.execute(
            "EXPLAIN SELECT chunk_id FROM knowledge.embeddings ORDER BY embedding <=> "
            "(SELECT embedding FROM knowledge.embeddings LIMIT 1) LIMIT 10").fetchall())
        results.append(("the planner uses the HNSW index", "embeddings_hnsw_cosine_idx" in plan,
                        next((x.strip()[:80] for x in plan.splitlines() if "embeddings_hnsw_cosine_idx" in x), "no index scan in the plan")))
        present = {r[0] for r in conn.execute("SELECT viewname FROM pg_views WHERE schemaname = 'knowledge'").fetchall()}
        results.append(("the three views exist", set(VIEWS) <= present, ", ".join(sorted(present))))
        function = conn.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('record_document_version', 'is_valid_chunk_config')").fetchone()[0]
        results.append(("the functions exist (record_document_version, is_valid_chunk_config)", function == 2, str(function)))
        constraint = conn.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'chunks_chunk_config_check'").fetchone()[0]
        results.append(("the five-key CHECK on chunk_config exists", constraint == 1, str(constraint)))
    exact_equal = True
    recalls: dict[str, float] = {}
    self_match = True
    for position in range(QUERIES):
        probe = f"(SELECT embedding FROM knowledge.embeddings ORDER BY chunk_id OFFSET {position} LIMIT 1)"
        query = ("SELECT c.chunk_id FROM knowledge.embeddings e JOIN knowledge.chunks c ON c.id = e.chunk_id "
                 f"ORDER BY e.embedding <=> {probe}, c.chunk_id LIMIT 10")
        exact, approx = {}, {}
        for name in (src, dst):
            with connect(name) as conn:
                conn.execute("SET enable_indexscan = off")
                conn.execute("SET enable_bitmapscan = off")
                exact[name] = [r[0] for r in conn.execute(query).fetchall()]
            with connect(name) as conn:
                conn.execute("SET hnsw.ef_search = 100")
                approx[name] = [r[0] for r in conn.execute(query).fetchall()]
        exact_equal &= exact[src] == exact[dst] and len(exact[src]) == 10
        self_match &= bool(approx[src]) and bool(approx[dst]) and approx[src][0] == approx[dst][0] == exact[src][0]
        for name in (src, dst):
            recalls[name] = recalls.get(name, 0.0) + len(set(approx[name]) & set(exact[name])) / 10 / QUERIES
    results.append((f"exact top-10 is identical in the source and the restore ({QUERIES} queries)", exact_equal, ""))
    results.append(("HNSW finds the query's own chunk first in both", self_match, ""))
    # An HNSW graph is rebuilt in another order by the restore, so the approximate top-10 of two builds is NOT expected to be the same set
    # (on random noise vectors it differs a lot). What must hold: the restored index finds the true neighbours about as well as the source.
    results.append(("HNSW recall@10 of the restore is not worse than the source's minus 0.2",
                    recalls[dst] >= recalls[src] - 0.2, f"source {recalls[src]:.2f}, restore {recalls[dst]:.2f}"))
    return results


def run(container: str, chunks: int) -> int:
    tag = uuid.uuid4().hex[:8]
    src, dst = f"drill_src_{tag}", f"drill_dst_{tag}"
    dump = f"/tmp/{src}.dump"
    created: list[str] = []
    timings: dict[str, float] = {}
    try:
        with psycopg.connect(make_conninfo(DATABASE_URL, dbname="postgres"), autocommit=True, connect_timeout=5) as admin:
            t = time.monotonic()
            admin.execute(f'CREATE DATABASE "{src}"')
            created.append(src)
            must(psql(container, src, sql_file=DATA / "db" / "schema-draft.sql"), "loading the schema")
            must(psql(container, src, sql_file=DATA / "db" / "knowledge_views.sql"), "loading the views")
            must(psql(container, src, sql_file=DATA / "bench" / "generate.sql", variables={"n_chunks": str(chunks)}), "generating data")
            must(psql(container, src, command="CREATE INDEX embeddings_hnsw_cosine_idx ON knowledge.embeddings USING hnsw "
                      "(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64); ANALYZE;"), "building the HNSW index")
            timings["prepare the source"] = time.monotonic() - t

            t = time.monotonic()
            must(docker(container, "pg_dump", "-U", "skillforge", "-d", src, "-Fc", "-n", "knowledge", "--no-owner", "--no-privileges",
                        "-f", dump), "pg_dump")
            timings["backup (pg_dump)"] = time.monotonic() - t
            size = docker(container, "stat", "-c", "%s", dump).stdout.decode().strip()

            admin.execute(f'CREATE DATABASE "{dst}"')
            created.append(dst)
            must(psql(container, dst, command="CREATE EXTENSION IF NOT EXISTS vector"), "creating the extension")
            t = time.monotonic()
            must(docker(container, "pg_restore", "-U", "skillforge", "-d", dst, "--no-owner", "--no-privileges", "--exit-on-error", dump),
                 "pg_restore")
            timings["restore (pg_restore, includes the HNSW rebuild)"] = time.monotonic() - t

        results = checks(src, dst)
    except Exception as exc:  # noqa: BLE001 - report, clean up, fail
        print(f"DRILL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return_code = 1
    else:
        print(f"\nRestore drill: {chunks} chunks, dump {int(size):,} bytes\n")
        print("| Check | Result | Detail |\n|---|---|---|")
        for name, ok, detail in results:
            print(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
        print("\n| Step | Seconds |\n|---|---|")
        for name, seconds in timings.items():
            print(f"| {name} | {seconds:.1f} |")
        return_code = 0 if all(ok for _, ok, _ in results) else 1
        print("\nDRILL " + ("PASSED" if return_code == 0 else "FAILED"))
    finally:
        with psycopg.connect(make_conninfo(DATABASE_URL, dbname="postgres"), autocommit=True, connect_timeout=5) as admin:
            for name in created:
                if name.startswith("drill_"):                       # never anything else
                    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        docker(container, "rm", "-f", dump)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", type=int, default=2000, help="size of the test data set (default 2000, 10 chunks per document)")
    parser.add_argument("--container", default="skillforge-postgres")
    args = parser.parse_args()
    return run(args.container, args.chunks)


if __name__ == "__main__":
    sys.exit(main())
