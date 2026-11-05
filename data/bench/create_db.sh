#!/usr/bin/env bash
# DE-02 benchmark: create the separate database skillforge_bench on the local container and load
# the schema + views into it. The real database (skillforge) is never touched.
# Run from the repo root or anywhere: bash data/bench/create_db.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1
here="$(cd "$(dirname "$0")/.." && pwd)"          # data/
# BENCH_CONTAINER: which container to use (default: the local stack; DE-02 used a separate one on port 5434)
CONTAINER="${BENCH_CONTAINER:-skillforge-postgres}"
psql_c() { docker exec -i "$CONTAINER" psql -v ON_ERROR_STOP=1 -U skillforge "$@"; }

psql_c -d postgres -c "CREATE DATABASE skillforge_bench"
cat "$here/db/schema-draft.sql" "$here/db/knowledge_views.sql" | psql_c -d skillforge_bench -q
# Benchmark tables only: UNLOGGED removes the WAL for the two big tables (and their indexes), which
# saves disk and time. Query speed is the same. embeddings first: a logged table may not reference
# an unlogged one.
psql_c -d skillforge_bench -q <<'SQL'
ALTER TABLE knowledge.embeddings SET UNLOGGED;
ALTER TABLE knowledge.chunks SET UNLOGGED;
SQL
echo "skillforge_bench created"
