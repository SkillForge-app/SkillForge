#!/usr/bin/env bash
# DE-02 benchmark: create the database skillforge_bench in the BENCH container and load the schema + views into it.
# The local stack's container (skillforge-postgres) and its database (skillforge) are never touched: the script
# refuses to run on any container whose name does not contain "bench".
# Start the container first: see docs/de-02-benchmark.md, section 2.1.
# Run from anywhere: bash data/bench/create_db.sh
BENCH_CONTAINER="${BENCH_CONTAINER:-skillforge-bench-pg}"
set -euo pipefail
export MSYS_NO_PATHCONV=1
case "$BENCH_CONTAINER" in
  *bench*) ;;
  *) echo "refusing to use container '$BENCH_CONTAINER': its name must contain 'bench' (never skillforge-postgres)" >&2; exit 1 ;;
esac
here="$(cd "$(dirname "$0")/.." && pwd)"          # data/
psql_c() { docker exec -i "$BENCH_CONTAINER" psql -v ON_ERROR_STOP=1 -U skillforge "$@"; }

psql_c -d postgres -c "CREATE DATABASE skillforge_bench"
cat "$here/db/schema-draft.sql" "$here/db/knowledge_views.sql" | psql_c -d skillforge_bench -q
# Benchmark tables only: UNLOGGED removes the WAL for the two big tables (and their indexes), which
# saves disk and time. Query speed is the same. embeddings first: a logged table may not reference
# an unlogged one.
psql_c -d skillforge_bench -q <<'SQL'
ALTER TABLE knowledge.embeddings SET UNLOGGED;
ALTER TABLE knowledge.chunks SET UNLOGGED;
SQL
echo "skillforge_bench created in $BENCH_CONTAINER"
