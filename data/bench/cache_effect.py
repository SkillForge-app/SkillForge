"""DE-02 benchmark: how much of the latency is disk reads and not the index itself.

Runs the same 100 queries twice in a row for three cases and prints p50 / p95 for each pass.
Pass 1 is "cold-ish" (it reads pages from disk that the 500k data does not leave in cache);
pass 2 repeats the same queries, so the pages they touch are in cache.
Run from data/:  .venv\\Scripts\\python bench\\cache_effect.py
"""
from __future__ import annotations

import random

import psycopg
import queries as q

DSN = q.DSN


def main() -> None:
    rng = random.Random(7)                       # other vectors than queries.py, so nothing is cached yet
    vectors = [q.unit_vector(rng) for _ in range(100)]
    cases = [
        ("hnsw, no filter, ef=40", lambda v: q.sql_for(v, None), (40, "off")),
        ("hnsw, legal/contracts, ef=100, relaxed_order", lambda v: q.sql_for(v, "legal/contracts"), (100, "relaxed_order")),
        ("gin, legal/contracts", lambda v: q.gin_sql_for(v, "legal/contracts"), (40, "off")),
    ]
    with psycopg.connect(DSN, autocommit=True, prepare_threshold=None) as conn:
        n = conn.execute("SELECT count(*) FROM knowledge.embeddings").fetchone()[0]
        print(f"{n:,} embeddings")
        for name, make, (ef, iterative) in cases:
            q.configure(conn, ef, iterative)
            sqls = [make(v) for v in vectors]
            for label in ("pass 1", "pass 2"):
                times, rows = q.timed(conn, sqls)
                s = q.summary({}, times, rows)
                print(f"{name:48} {label}: p50={s['p50']:8.1f} p95={s['p95']:8.1f} p99={s['p99']:8.1f} ms  rows={s['avg_rows']:.1f}")


if __name__ == "__main__":
    main()
