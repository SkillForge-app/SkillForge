"""DE-02 benchmark: time AI's search query on knowledge.knowledge_chunks (database skillforge_bench).

Run from data/:  .venv\\Scripts\\python bench\\queries.py [--queries 100] [--recall-queries 20] [--out result.json]
The database is chosen with BENCH_DATABASE_URL (default: the separate bench container on port 5434).

Measures, per setting: p50 / p95 / p99 (client-side wall time, including the round trip to the container),
the average number of rows returned, and recall@10 against the exact search (the same search on the
embeddings table with every index switched off). It also times a second way to filter by domain: the GIN
index on embeddings.domains, with no HNSW, then an exact sort of the matching rows. Last, EXPLAIN
(ANALYZE, BUFFERS) for the fastest and the slowest case.
Query vectors are random unit vectors drawn like the data. Real queries are closer to real chunks, so
the numbers are pessimistic (see docs/de-02-benchmark.md).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import time

import psycopg

DSN = os.environ.get(
    "BENCH_DATABASE_URL",
    "postgresql://skillforge:skillforge_dev@127.0.0.1:5434/skillforge_bench",
)
DIM = 384
COLUMNS = (
    "chunk_id, source_url, title, retrieved, text, section, concepts, content_hash, domains, "
    "1 - (embedding <=> {v}) AS score"
)
# The filter is AI's: the query domain and its parents, or any child of the domain.
FILTER = (
    "(domains && {parents}::text[] "
    "OR EXISTS (SELECT 1 FROM unnest(domains) AS d WHERE d LIKE {domain} || '/%'))"
)
DOMAINS = {
    "technology/ai": ["technology", "technology/ai"],      # about 12% of the chunks
    "science/biology": ["science", "science/biology"],      # about 3%
    "legal/contracts": ["legal", "legal/contracts"],        # about 1%
}


def unit_vector(rng: random.Random) -> list[float]:
    v = [rng.random() - 0.5 for _ in range(DIM)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def vec_literal(v: list[float]) -> str:
    return "'[" + ",".join(f"{x:.7f}" for x in v) + "]'::vector"


def array_literal(domain: str) -> str:
    return "ARRAY[" + ",".join(f"'{p}'" for p in DOMAINS[domain]) + "]"


def where_for(domain: str | None) -> str:
    if not domain:
        return ""
    return "WHERE " + FILTER.format(parents=array_literal(domain), domain=f"'{domain}'")


def sql_for(v: list[float], domain: str | None, tiebreak: bool = True) -> str:
    """AI's query, exactly as in docs: through the view, ORDER BY embedding <=> v (, chunk_id)."""
    vec = vec_literal(v)
    order = f"ORDER BY embedding <=> {vec}" + (", chunk_id" if tiebreak else "")
    return f"SELECT {COLUMNS.format(v=vec)} FROM knowledge.knowledge_chunks {where_for(domain)} {order} LIMIT 10"


def gin_sql_for(v: list[float], domain: str) -> str:
    """The GIN way: only `domains && parents` (the part the GIN index can serve), and `+ 0` on the
    distance so the planner cannot use the HNSW index for the ORDER BY. It then reads the matching
    rows through the GIN index and sorts them by exact distance."""
    vec = vec_literal(v)
    return (f"SELECT {COLUMNS.format(v=vec)} FROM knowledge.knowledge_chunks "
            f"WHERE domains && {array_literal(domain)}::text[] "
            f"ORDER BY (embedding <=> {vec}) + 0, chunk_id LIMIT 10")


def truth_sql_for(v: list[float], domain: str | None) -> str:
    """Exact top 10 straight from embeddings (every document in the bench data is current)."""
    vec = vec_literal(v)
    where = where_for(domain)
    return ("SELECT c.chunk_id FROM (SELECT chunk_id FROM knowledge.embeddings "
            f"{where} ORDER BY embedding <=> {vec} LIMIT 10) t JOIN knowledge.chunks c ON c.id = t.chunk_id")


def percentile(sorted_ms: list[float], p: float) -> float:
    k = (len(sorted_ms) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_ms[lo] + (sorted_ms[hi] - sorted_ms[lo]) * (k - lo)


def configure(conn, ef: int, iterative: str, exact: bool = False) -> None:
    conn.execute(f"SET hnsw.ef_search = {ef}")
    conn.execute(f"SET hnsw.iterative_scan = {iterative}")
    conn.execute(f"SET enable_indexscan = {'off' if exact else 'on'}")
    conn.execute(f"SET enable_bitmapscan = {'off' if exact else 'on'}")


def timed(conn, sqls: list[str]) -> tuple[list[float], list[int]]:
    for s in sqls[:5]:                                      # warm-up, not timed
        conn.execute(s).fetchall()
    times, rows = [], []
    for s in sqls:
        t0 = time.perf_counter()
        res = conn.execute(s).fetchall()
        times.append((time.perf_counter() - t0) * 1000)
        rows.append(len(res))
    return sorted(times), rows


def summary(label: dict, times: list[float], rows: list[int]) -> dict:
    return {**label, "n": len(times), "p50": percentile(times, 0.50), "p95": percentile(times, 0.95),
            "p99": percentile(times, 0.99), "mean": statistics.fmean(times), "max": times[-1],
            "avg_rows": statistics.fmean(rows)}


def run_case(conn, queries, domain, ef, iterative, tiebreak=True):
    configure(conn, ef, iterative)
    times, rows = timed(conn, [sql_for(q, domain, tiebreak) for q in queries])
    return summary({"method": "hnsw", "domain": domain or "none", "ef_search": ef,
                    "iterative_scan": iterative, "tiebreak": tiebreak}, times, rows)


def run_gin_case(conn, queries, domain):
    configure(conn, 40, "off")
    times, rows = timed(conn, [gin_sql_for(q, domain) for q in queries])
    plan = "\n".join(r[0] for r in conn.execute("EXPLAIN " + gin_sql_for(queries[0], domain)).fetchall())
    uses_gin = "embeddings_domains_gin_idx" in plan
    uses_hnsw = "embeddings_hnsw_cosine_idx" in plan
    return summary({"method": "gin", "domain": domain, "ef_search": None, "iterative_scan": "-",
                    "tiebreak": True, "uses_gin": uses_gin, "uses_hnsw": uses_hnsw}, times, rows)


def explain(conn, sql: str) -> str:
    rows = conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql).fetchall()
    text = "\n".join(r[0] for r in rows)
    return re.sub(r"'\[[-0-9.e,]+\]'", "'[<384 floats>]'", text)      # keep the plan readable


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--recall-queries", type=int, default=20)
    ap.add_argument("--out", default="bench_result.json")
    args = ap.parse_args()

    rng = random.Random(20261104)
    queries = [unit_vector(rng) for _ in range(args.queries)]
    recall_queries = [unit_vector(rng) for _ in range(args.recall_queries)]

    # prepare_threshold=None: every query is planned on its own literal, like the EXPLAIN below.
    with psycopg.connect(DSN, autocommit=True, prepare_threshold=None) as conn:
        info = conn.execute(
            "SELECT version(), (SELECT extversion FROM pg_extension WHERE extname = 'vector'), "
            "(SELECT count(*) FROM knowledge.embeddings), "
            "pg_size_pretty(pg_relation_size('knowledge.embeddings_hnsw_cosine_idx')), "
            "current_setting('shared_buffers'), pg_size_pretty(pg_relation_size('knowledge.embeddings_domains_gin_idx'))"
        ).fetchone()
        print(f"{info[0].split(',')[0]}, pgvector {info[1]}, {info[2]:,} embeddings, "
              f"HNSW {info[3]}, GIN {info[5]}, shared_buffers {info[4]}")

        # One untimed pass over every query, so the first timed case does not pay for a cold cache.
        configure(conn, 100, "off")
        for q in queries:
            conn.execute(sql_for(q, None)).fetchall()

        results = []
        grid = [(None, (40, 100), ("off",)),
                ("technology/ai", (40, 100), ("off", "relaxed_order")),
                ("legal/contracts", (40, 100, 200), ("off", "relaxed_order"))]
        for domain, efs, iters in grid:
            for ef in efs:
                for iterative in iters:
                    r = run_case(conn, queries, domain, ef, iterative)
                    results.append(r)
                    print(f"hnsw {r['domain']:16} ef={ef:3} iter={iterative:13} p50={r['p50']:8.1f} "
                          f"p95={r['p95']:8.1f} p99={r['p99']:8.1f} ms  rows={r['avg_rows']:.1f}", flush=True)
        r = run_case(conn, queries, None, 40, "off", tiebreak=False)
        results.append(r)
        print(f"hnsw none (no tiebreak)  ef= 40 iter=off           p50={r['p50']:8.1f} p95={r['p95']:8.1f} "
              f"p99={r['p99']:8.1f} ms  rows={r['avg_rows']:.1f}", flush=True)

        print("\nGIN on domains, no HNSW (exact sort of the matching rows)")
        for domain in ("legal/contracts", "science/biology", "technology/ai"):
            r = run_gin_case(conn, queries, domain)
            results.append(r)
            print(f"gin  {domain:16} p50={r['p50']:8.1f} p95={r['p95']:8.1f} p99={r['p99']:8.1f} ms  "
                  f"rows={r['avg_rows']:.1f}  gin_index_used={r['uses_gin']} hnsw_used={r['uses_hnsw']}", flush=True)

        print(f"\nrecall@10 against the exact search ({len(recall_queries)} queries)")
        recalls = []
        for domain, efs, iters in grid:
            truth = []
            configure(conn, 40, "off", exact=True)
            for q in recall_queries:
                truth.append({r[0] for r in conn.execute(truth_sql_for(q, domain)).fetchall()})
            configure(conn, 40, "off")
            for ef in efs:
                for iterative in iters:
                    configure(conn, ef, iterative)
                    hits = total = 0
                    for q, tr in zip(recall_queries, truth, strict=True):
                        got = {r[0] for r in conn.execute(sql_for(q, domain)).fetchall()}
                        hits += len(tr & got)
                        total += len(tr)
                    rc = hits / total
                    recalls.append({"method": "hnsw", "domain": domain or "none", "ef_search": ef,
                                    "iterative_scan": iterative, "recall": rc})
                    print(f"hnsw {domain or 'none':16} ef={ef:3} iter={iterative:13} recall@10={rc:.3f}", flush=True)
        configure(conn, 40, "off")
        for domain in ("legal/contracts", "science/biology", "technology/ai"):
            hits = total = 0
            configure(conn, 40, "off", exact=True)
            truth = [{r[0] for r in conn.execute(truth_sql_for(q, domain)).fetchall()} for q in recall_queries]
            configure(conn, 40, "off")
            for q, tr in zip(recall_queries, truth, strict=True):
                got = {r[0] for r in conn.execute(gin_sql_for(q, domain)).fetchall()}
                hits += len(tr & got)
                total += len(tr)
            recalls.append({"method": "gin", "domain": domain, "ef_search": None, "iterative_scan": "-",
                            "recall": hits / total})
            print(f"gin  {domain:16} recall@10={hits / total:.3f}", flush=True)

        hnsw_cases = [r for r in results if r["method"] == "hnsw" and r["tiebreak"]]
        # "fastest" only counts cases that return a full page; a case that returns 0 rows is fast and useless
        fast = min((r for r in hnsw_cases if r["avg_rows"] >= 9.5), key=lambda r: r["p50"])
        slow = max(hnsw_cases, key=lambda r: r["p50"])
        plans = {}
        for label, r in (("fastest", fast), ("slowest", slow)):
            dom = None if r["domain"] == "none" else r["domain"]
            configure(conn, r["ef_search"], r["iterative_scan"])
            plans[label] = {"case": r, "plan": explain(conn, sql_for(recall_queries[0], dom))}
            print(f"\n=== EXPLAIN (ANALYZE, BUFFERS): {label}: {r['domain']} ef={r['ef_search']} "
                  f"iter={r['iterative_scan']}\n{plans[label]['plan']}")
        configure(conn, 40, "off")
        plans["gin_rare"] = {"case": {"domain": "legal/contracts"}, "plan": explain(conn, gin_sql_for(recall_queries[0], "legal/contracts"))}
        print(f"\n=== EXPLAIN (ANALYZE, BUFFERS): GIN, legal/contracts\n{plans['gin_rare']['plan']}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"info": list(info), "timings": results, "recall": recalls, "plans": plans}, f, indent=2, default=str)
    print(f"\nwritten {args.out}")


if __name__ == "__main__":
    main()
