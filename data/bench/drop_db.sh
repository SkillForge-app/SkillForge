#!/usr/bin/env bash
# Remove the benchmark database. Only skillforge_bench; the name is fixed on purpose.
set -euo pipefail
export MSYS_NO_PATHCONV=1
docker exec -i "${BENCH_CONTAINER:-skillforge-postgres}" psql -v ON_ERROR_STOP=1 -U skillforge -d postgres \
  -c "DROP DATABASE IF EXISTS skillforge_bench WITH (FORCE)"
