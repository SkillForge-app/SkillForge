#!/usr/bin/env bash
# Remove the benchmark database skillforge_bench from the BENCH container (the name is fixed on purpose).
# It does not remove the container or its volume: see docs/de-02-benchmark.md, section 2.1.
# Like create_db.sh, it refuses to run on any container whose name does not contain "bench",
# so it can never drop anything in the local stack's skillforge-postgres.
BENCH_CONTAINER="${BENCH_CONTAINER:-skillforge-bench-pg}"
set -euo pipefail
export MSYS_NO_PATHCONV=1
case "$BENCH_CONTAINER" in
  *bench*) ;;
  *) echo "refusing to use container '$BENCH_CONTAINER': its name must contain 'bench' (never skillforge-postgres)" >&2; exit 1 ;;
esac
docker exec -i "$BENCH_CONTAINER" psql -v ON_ERROR_STOP=1 -U skillforge -d postgres \
  -c "DROP DATABASE IF EXISTS skillforge_bench WITH (FORCE)"
echo "skillforge_bench dropped from $BENCH_CONTAINER"
