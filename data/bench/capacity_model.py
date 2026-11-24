"""DE-15: the capacity model of docs/capacity-plan.md. Pure arithmetic, no database, no network.

Run: python bench/capacity_model.py   (prints the three scenarios as a Markdown table)
Every constant is either MEASURED (docs/de-02-benchmark.md) or an ASSUMPTION; the comments say which. Change them and re-run.
"""
from dataclasses import dataclass

KB, MB, GB = 1024, 1024**2, 1024**3

# ---- measured (docs/de-02-benchmark.md, 4 Nov 2026; benchmark chunks have about 400 characters of text)
TABLES_PER_CHUNK = 3.3 * GB / 1_000_000       # chunks + embeddings + their ordinary indexes, per chunk (1M rows: 3.3 GB)
HNSW_PER_VECTOR = 1.95 * KB                   # 195 MB per 100k, 977 MB per 500k (m=16, ef_construction=64)
VECTOR_BYTES = 384 * 4                        # vector(384) of float4 (contract); inside TABLES_PER_CHUNK already
# ---- assumptions
REAL_TEXT_EXTRA = 0.7 * KB                    # real chunks (about 180 words, 1,100 chars) have about 700 more chars than the benchmark's
RAW_PAGE = 100 * KB                           # average raw HTML of a page
CLEAN_PAGE = 20 * KB                          # clean text of a page
CHUNKS_PER_PAGE = 10                          # the benchmark used 10; real value comes from AI (see the input list)
CHANGED_PER_MONTH = 0.10                      # share of pages whose content changes in a month
RAW_KEEP_DAYS, REFRESH_DAYS = 30, 30          # raw retention and web freshness window (documents: retention and freshness.py)
DOC_ROW = 2 * KB                              # a documents + sources row set per page version (assumption)
SUPERSEDED_DAYS = 90                          # superseded documents rows are kept 90 days (retention table)
EMBED_CHUNKS_PER_SECOND = 30                  # CPU speed of the local embedding model on one worker
DUMP_RATIO = 0.5                              # compressed dump size / table size
MONTHS = 6


@dataclass
class Scenario:
    name: str
    pages: int                                 # current pages (sources) at the end of month 6


def model(s: Scenario) -> dict[str, float]:
    chunks = s.pages * CHUNKS_PER_PAGE
    tables = chunks * (TABLES_PER_CHUNK + REAL_TEXT_EXTRA)
    hnsw = chunks * HNSW_PER_VECTOR
    new_per_month = s.pages / MONTHS                       # linear growth
    changed_per_month = s.pages * CHANGED_PER_MONTH
    fetched_new_content = new_per_month + changed_per_month   # pages that store new raw bytes per month
    raw = fetched_new_content * RAW_KEEP_DAYS / 30 * RAW_PAGE
    clean = s.pages * CLEAN_PAGE
    superseded_rows = changed_per_month * SUPERSEDED_DAYS / 30 * DOC_ROW
    requests_per_day = (s.pages + new_per_month) / REFRESH_DAYS
    download_per_month = (s.pages + new_per_month) * RAW_PAGE   # no 304 savings assumed
    return {
        "pages": s.pages, "chunks": chunks,
        "tables_gb": tables / GB, "hnsw_gb": hnsw / GB, "db_gb": (tables + hnsw + superseded_rows) / GB,
        "ram_gb": hnsw / GB * 1.0 + 0.5,                    # the index cached + shared_buffers and the OS (assumption: +0.5 GB)
        "raw_gb": raw / GB, "clean_gb": clean / GB, "objects_gb": (raw + clean) / GB,
        "requests_per_day": requests_per_day, "download_gb_month": download_per_month / GB,
        "embed_first_load_h": chunks / EMBED_CHUNKS_PER_SECOND / 3600,
        "embed_month_h": fetched_new_content * CHUNKS_PER_PAGE / EMBED_CHUNKS_PER_SECOND / 3600,
        "dump_gb": tables * DUMP_RATIO / GB,
    }


SCENARIOS = [Scenario("small", 5_000), Scenario("medium", 50_000), Scenario("large", 500_000)]

if __name__ == "__main__":
    rows = [model(s) for s in SCENARIOS]
    keys = list(rows[0])
    print("| | " + " | ".join(s.name for s in SCENARIOS) + " |")
    print("|---|" + "---|" * len(SCENARIOS))
    for k in keys:
        print(f"| {k} | " + " | ".join(f"{r[k]:,.1f}" if r[k] < 1000 else f"{r[k]:,.0f}" for r in rows) + " |")
