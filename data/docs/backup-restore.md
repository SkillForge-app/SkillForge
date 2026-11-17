# DE-14: backup and restore of the knowledge data

Status: draft of 17 November 2026. Written for DevOps (OPS-12) and the owner. **Only the drill on a throwaway database has been done.** The "Done when"
of DE-14 ("restore drill passed", with DevOps) is **not met yet**: no production database, no scheduled backup and no real restore exist.

## 1. What has to be backed up

| What | Where | How | Status |
|---|---|---|---|
| Schema `knowledge`: sources, documents, chunks, embeddings (vectors), `active_config`, `crawl_runs`, views, functions | PostgreSQL | logical dump of the schema (`pg_dump -Fc -n knowledge`); for production DevOps may prefer physical backup with WAL archiving (see questions) | drill done on a small data set |
| Raw pages, clean text | object storage (`skillforge-raw`, `skillforge-clean`) | bucket versioning or replication (DevOps); raw expires after 30 days, so its backup is short-lived | not done; needs production storage |
| Compiled skill packages | `skillforge-packages` | belongs to Backend and DevOps | not ours |
| Roles and passwords | the server | `db/roles-local.sql` is for local use only; production roles are DevOps's | not covered by the drill |

What **can be rebuilt**: the HNSW index (rebuilt by the restore), and chunks and embeddings from the clean text (re-embedding). What **cannot**: the crawl history
(`crawl_runs`), licence and robots flags, and documents whose raw page has expired (the clean text can stand in for the raw page).

## 2. The drill: `scripts/restore_drill.py`

```
python scripts/restore_drill.py --chunks 2000       # from data/, with the local container running
```

It uses the **existing** container (`skillforge-postgres`), creates two throwaway databases named `drill_src_<id>` and `drill_dst_<id>`, and drops them (and the dump file)
when it ends, also on failure. It never touches the database `skillforge` and only drops names starting with `drill_`. No network.

Steps: load the schema and the views; load a small data set with `bench/generate.sql` (random unit vectors, 10 chunks per document); build the HNSW index; `pg_dump -Fc -n knowledge`;
create the second database with `CREATE EXTENSION vector`; `pg_restore --exit-on-error`; compare.

### Result (17 November 2026, PostgreSQL 18.6, pgvector 0.8.6, this laptop)

| Check | 2,000 chunks | 20,000 chunks |
|---|---|---|
| Row counts equal in every table | pass | pass |
| HNSW index exists, is valid, and the planner uses it | pass | pass |
| The three views, `record_document_version()`, `is_valid_chunk_config()` and the five-key CHECK exist | pass | pass |
| Exact top-10 identical in source and restore (10 queries) | pass | pass |
| HNSW finds the query's own chunk first, in both | pass | pass |
| HNSW recall@10 of the restore is not worse than the source's minus 0.2 | pass (1.00 / 1.00) | pass (0.53 / 0.50) |
| Dump size | 4.5 MB | 45 MB |
| Backup time | 2.7 s | 11.0 s |
| Restore time (includes the HNSW rebuild) | 2.9 s | 22.0 s |

Things to know about this result:
- **The HNSW top-10 sets of the source and the restore are not the same, and are not expected to be.** The restore rebuilds the graph in another order. My first version of the
  check required equal sets and failed at 20,000 chunks (overlap 4 of 10). The drill therefore compares what must hold: exact search identical, the nearest chunk found first, recall not
  worse. Recall is low (0.5) because the test vectors are random noise, which is harder for HNSW than real embeddings (`de-02-benchmark.md`); it says nothing about production quality.
- **Restore time is dominated by the index rebuild and grows faster than the data.** The benchmark measured 40 s for 100k vectors, 23.7 min for 500k and an estimated **more than 5 hours**
  for 1M on a small machine (`de-02-benchmark.md`). A real restore of a large database must plan for that downtime, or restore from a physical backup that includes the index.
- The drill is small (at most 20,000 chunks). It proves the procedure and the checks, **not** the timing at production size.
- Not covered: object storage, roles and grants, `pg_dump` of other schemas, point-in-time recovery, restore into a different Postgres or pgvector version.

## 3. Procedure for a real restore (draft, to review with DevOps)

1. Create an empty database on a server with the same major version of PostgreSQL and **the same or newer pgvector**; `CREATE EXTENSION vector`.
2. `pg_restore --no-owner --exit-on-error -d <db> <dump>`. The HNSW index is rebuilt here: raise `maintenance_work_mem` (about 2.1 GB per million vectors to build in memory, see the benchmark) and `max_parallel_maintenance_workers`.
3. Create the roles and grants (DevOps's scripts): `UPDATE`/`DELETE` and `EXECUTE record_document_version()` are restricted to the pipeline's role.
4. Run the checks of the drill against the restored database (row counts against the backup's manifest, the index, a similarity query).
5. Restore object storage from its own backup; run `reconcile_raw` (it clears keys whose object is missing) and the orphan sweep.
6. Run `monitoring.run_checks` (DE-11): an empty or stale restore shows up as `no_new_data` or `no_recent_success`.

## 4. Questions for DevOps (OPS-12)

1. Which backup method will production use: logical dumps, physical base backups with WAL archiving (point-in-time recovery), or the cloud provider's snapshots? Physical backups keep the HNSW index and avoid the long rebuild.
2. How often, how long kept, and where? (The capacity plan's dump size is about 0.5 GB per 100k chunks, assumption of a 0.5 compression ratio: `capacity-plan.md`.)
3. What is the recovery objective: how much data may be lost (RPO) and how long may the restore take (RTO)? With the index rebuild, the RTO of a large database is hours.
4. Will there be a staging database that the drill can run against? It must have the same PostgreSQL major version and pgvector version as production (the CI uses pgvector 0.8.6 on PostgreSQL 18).
5. Object storage: versioning or replication for `skillforge-raw` and `skillforge-clean`, and the same for the restore test.
6. Who creates roles and grants in production, and where are the scripts (`db/roles-local.sql` is local only)?
7. Who runs the drill and how often (assumption: after every schema change and once a quarter), and where is the result kept?
8. Where will the scheduled backups run, and how will a failed backup alert (OPS-10; our `monitoring` package has the alert interface ready, with no notifier connected yet)?
