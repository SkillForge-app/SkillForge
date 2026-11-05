#!/usr/bin/env bash
# DE-02 benchmark in one go, on the BENCH container (port 5434, bound to 127.0.0.1):
#   bash data/bench/run.sh <n_chunks> <label> [out_dir]
# Loads the data, builds the HNSW index, runs the queries. Logs go to <out_dir>/<label>-*.log.
# Needs the database from create_db.sh. Refuses to run on any container whose name does not contain "bench".
BENCH_CONTAINER="${BENCH_CONTAINER:-skillforge-bench-pg}"
set -euo pipefail
export MSYS_NO_PATHCONV=1
case "$BENCH_CONTAINER" in
  *bench*) ;;
  *) echo "refusing to use container '$BENCH_CONTAINER': its name must contain 'bench' (never skillforge-postgres)" >&2; exit 1 ;;
esac
n="${1:?n_chunks}"; label="${2:?label}"; out="${3:-.}"
here="$(cd "$(dirname "$0")" && pwd)"
psql_c() { docker exec -i "$BENCH_CONTAINER" psql -U skillforge -d skillforge_bench "$@"; }

t0=$(date +%s)
psql_c -v n_chunks="$n" < "$here/generate.sql" > "$out/$label-generate.log" 2>&1
t1=$(date +%s); echo "generate: $((t1 - t0)) s" | tee -a "$out/$label-times.log"
psql_c -v mwm="${MWM:-1GB}" -v workers="${WORKERS:-2}" < "$here/build_index.sql" > "$out/$label-build.log" 2>&1
t2=$(date +%s); echo "build_index: $((t2 - t1)) s" | tee -a "$out/$label-times.log"
cd "$here/.."
.venv/Scripts/python bench/queries.py --out "$(cygpath -m "$out" 2>/dev/null || echo "$out")/$label-result.json" > "$out/$label-queries.log" 2>&1
t3=$(date +%s); echo "queries: $((t3 - t2)) s" | tee -a "$out/$label-times.log"
