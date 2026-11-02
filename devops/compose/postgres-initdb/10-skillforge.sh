#!/usr/bin/env bash
# First start of the local postgres (OPS-03, compose.yaml): the image runs this once, when the
# data volume is empty. It enables pgvector, then applies Data Engineering's SQL from data/db/
# (mounted read-only at /skillforge/data-db) in their documented order, if it is there.
#
# The image's entrypoint runs this file when it is executable and sources it when it is not
# (the exec bit can be lost on Windows checkouts), so it works both ways: no `exit`, no `set`,
# every name starts with skillforge_, and a failed step returns non-zero. A failure stops the
# container instead of leaving a half-built database.

skillforge_psql() {
    psql -v ON_ERROR_STOP=1 --no-psqlrc --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" "$@"
}

skillforge_init() {
    local db=/skillforge/data-db
    local f

    skillforge_psql -c 'CREATE EXTENSION IF NOT EXISTS vector;' || return 1

    if [ ! -f "$db/schema-draft.sql" ]; then
        echo "skillforge: data/db/schema-draft.sql not found; only pgvector is enabled"
        return 0
    fi

    # The order from data/CLAUDE.md. Tell DevOps when these names or this order change.
    for f in "$db"/init/*.sql "$db/schema-draft.sql" "$db/knowledge_views.sql" "$db/roles-local.sql"; do
        [ -f "$f" ] || continue
        echo "skillforge: applying data/db/${f#"$db"/}"
        skillforge_psql -f "$f" || return 1
    done
}

skillforge_init
