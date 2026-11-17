"""DE-01: every writer of knowledge.chunks sends the five-key chunk_config, extract_fingerprint included.

The CHECK (`is_valid_chunk_config`) refuses a row without a 64-hex extract_fingerprint. This audit lists the files that insert
into knowledge.chunks, so a new writer (a script, a benchmark) cannot be added without someone looking at its chunk_config.
"""
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1]
INSERT = re.compile(r"INSERT\s+INTO\s+knowledge\.chunks\b", re.IGNORECASE)
SKIP = {"__pycache__", ".venv", ".pytest_cache", ".ruff_cache", "node_modules"}

# file (relative to data/) -> where its chunk_config comes from
KNOWN_WRITERS = {
    "skillforge_data/pipeline/process.py": "PipelineConfig.chunk_config() (the pipeline)",
    "bench/generate.sql": "a literal with extract_fingerprint (the DE-02 benchmark data)",
    "tests/test_document_versions.py": "CHUNK_CONFIG / explicit jsonb in the tests",
}


def writers():
    found = set()
    for path in DATA.rglob("*"):
        if path.suffix not in {".py", ".sql", ".sh"} or SKIP & set(path.parts) or path.name == Path(__file__).name:
            continue
        if INSERT.search(path.read_text(encoding="utf-8", errors="ignore")):
            found.add(path.relative_to(DATA).as_posix())
    return found


def test_the_files_that_insert_chunks_are_the_known_ones():
    assert writers() == set(KNOWN_WRITERS), "a new writer of knowledge.chunks: check its chunk_config has the five keys, then list it"


def test_the_benchmark_data_has_the_extract_fingerprint():
    sql = (DATA / "bench" / "generate.sql").read_text(encoding="utf-8")
    assert '"extract_fingerprint"' in sql and "sha256('bench'" in sql


def test_the_test_helper_config_is_valid(db):
    from test_document_versions import CHUNK_CONFIG
    assert db.execute("SELECT knowledge.is_valid_chunk_config(%s::jsonb)", (CHUNK_CONFIG,)).fetchone()[0]
