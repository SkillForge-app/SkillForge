#!/usr/bin/env bash
# DE-02 benchmark in one go, on the separate bench container (port 5434):
#   bash data/bench/run.sh <n_chunks> <label> [out_dir]
# Loads the data, builds the HNSW index, runs the queries. Logs go to <out_dir>/<label>-*.log.
set -euo pipefail
export MSYS_NO_PATHCONV=1
n="${1:?n_chunks}"; label="${2:?label}"; out="${3:-.}"
here="$(cd "$(dirname "$0")" && pwd)"
C="${BENCH_CONTAINER:-skillforge-bench-pg}"
psql_c() { docker exec -i "$C" psql -U skillforge -d skillforge_bench "$@"; }

t0=$(date +%s)
psql_c -v n_chunks="$n" < "$here/generate.sql" > "$out/$label-generate.log" 2>&1
t1=$(date +%s); echo "generate: $((t1 - t0)) s" | tee -a "$out/$label-times.log"
psql_c -v mwm="${MWM:-1GB}" -v workers="${WORKERS:-2}" < "$here/build_index.sql" > "$out/$label-build.log" 2>&1
t2=$(date +%s); echo "build_index: $((t2 - t1)) s" | tee -a "$out/$label-times.log"
cd "$here/.."
.venv/Scripts/python bench/queries.py --out "$(cygpath -m "$out" 2>/dev/null || echo "$out")/$label-result.json" > "$out/$label-queries.log" 2>&1
t3=$(date +%s); echo "queries: $((t3 - t2)) s" | tee -a "$out/$label-times.log"
