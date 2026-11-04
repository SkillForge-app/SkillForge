# Object storage (DE-03)

Status: draft for review by Backend and DevOps. Owner: Data Engineering.

Postgres holds metadata, chunks and embeddings. Large files live in S3-compatible object storage:
raw pages, clean text and compiled skill packages. The database stores only the object key.

## 1. What goes where

| Data | Stored in | Why |
| --- | --- | --- |
| Raw fetched page (HTML, PDF, Markdown) | object storage, `raw` bucket | Large, binary, kept 30 days for re-processing and audits |
| Clean text from `extract_page()` | object storage, `clean` bucket | Input to chunking; kept until a newer version replaces it |
| Skill packages (`SKILL.md` + references) | object storage, `packages` bucket | Output of the Compilers, downloaded by users |
| Sources, documents, chunks, embeddings | Postgres (`knowledge` schema) | Queried, filtered and searched |

AI never reads object storage. It reads `knowledge_chunks` only.

## 2. Buckets and key layout

- **Raw pages are content-addressed** by the document's `content_hash` (sha256 of the fetched bytes). The same
  bytes from the same host always get the same key, so a re-run writes nothing new. This keeps DE-05 idempotent.
- **Clean text is keyed by document and extraction version,** not by content hash: `<document_id>/<extract_fingerprint>`.
  `extract_fingerprint` is AI's `ExtractConfig.fingerprint()` (the same value as in `chunk_config`). Until AI finishes
  that function, use the literal `v0`. Re-running the same document with the same extraction gives the same key.

| Bucket | Key pattern | Example |
| --- | --- | --- |
| `skillforge-raw` | `<host>/<hash[0:2]>/<hash>.<ext>` | `docs.python.org/3f/3f9a....html` |
| `skillforge-clean` | `<document_id>/<extract_fingerprint>.txt` | `3b9f2c1e-.../v0.txt` |
| `skillforge-packages` | `<skill_id>/<version>/package.zip` | `pandas-groupby/1.2.0/package.zip` |

- The 2-character prefix of raw keys spreads objects across prefixes.
- **Why the clean key has the document id.** Two documents can have the same `content_hash` (the same page text on two
  sources). With a hash-only key they would share one clean object, and deleting the old version of one document
  would delete the clean text the other still uses. With `<document_id>` in the key, every document owns its own
  objects, so deleting one can never touch another's.
- **Why the clean key has the extraction version.** The same document, extracted with another config (or after AI
  bumps `EXTRACTION_VERSION`), gives different clean text. A different `extract_fingerprint` is a different key, so the
  old and the new extraction sit side by side during a rebuild and never overwrite each other. Once the new
  extraction is live, DE-05 deletes the document's other `<document_id>/<old fingerprint>.txt` objects.
- Object metadata: `content-type`, `source-url` (normalised), `crawl-run-id`, `fetched-at`.
- `documents` already references the objects by key, in `schema-draft.sql`: `raw_object_key` and
  `clean_object_key` (text, NULL until the object exists), with `raw_deleted_at` and `clean_deleted_at`
  set when the object is removed. `record_document_version()` takes the raw key as `p_raw_object_key`.
  No column needs to be added. The packages bucket is not referenced from the `knowledge` schema.

## 3. Write order and consistency

Object storage and Postgres cannot share a transaction, so the pipeline follows one order.

**Writing (a fetched page):**

1. Upload the object. If the key already exists, skip the upload (the object keeps its first upload time).
2. In one Postgres transaction: `record_document_version()` and store the key.
3. If step 2 fails, the object stays as an orphan. A daily sweep deletes objects that no row
   references and that are older than 24 hours.

**Deleting raw (the daily job, DE-05):** the order is the reverse, database first:

1. Find raw objects whose first upload is more than 30 days old (the object's `LastModified`).
2. In one Postgres transaction, for every `documents` row with that `raw_object_key`: set `raw_deleted_at = now()` and
   `raw_object_key = NULL`. Update every row with the key, not one: two sources on the same host with the same bytes
   share a raw key.
3. After the commit, delete the object. If the delete fails, the object is an orphan and the orphan sweep removes it.

Because the row is cleared before the object goes, **a row never points to a missing object**: either the key is set
and the object exists, or the key is NULL and `raw_deleted_at` says it was removed. The bucket rule below is not part
of this guarantee. It is a safety net that should never fire.

**Re-fetching an unchanged page does not extend the 30 days.** `record_document_version()` refreshes `fetched_at`,
but the upload is skipped (step 1 above), so the object keeps its first upload time and the job counts 30 days from
that. The 30 days are from the first upload, not from `fetched_at`. If the raw object is already gone when the page
comes back (A, then B, then A again), the pipeline uploads it again, and that new object has its own 30 days; the
row gets the new key and `raw_deleted_at` is cleared.

## 4. Lifecycle (matches the agreed retention)

| Data | Rule | Who deletes |
| --- | --- | --- |
| Raw | Delete 30 days after the first upload | The daily DE-05 job: clears `raw_object_key`, sets `raw_deleted_at`, then deletes the object (section 3) |
| Raw (safety net) | Expire 35 days after upload | Bucket lifecycle rule. It only catches objects the job missed. If it ever fires, the next job run clears the key of any row whose object is gone |
| Clean text | Until a newer clean text replaces it | DE-05, in the transaction that deletes the old chunks and sets `clean_deleted_at` |
| Old chunks and embeddings | Deleted when newer clean text replaces it | DE-05 (`ON DELETE CASCADE` from chunks to embeddings) |
| Old `documents` rows | 90 days | DE-05 retention job |
| Packages | Every published version kept | Open question for Backend |
| Orphans | 24 hours | Daily sweep |

Clean text is deleted by the pipeline, not by a bucket rule, because it depends on database
state. A bucket rule would delete clean text that is still current.

## 5. Security

- All buckets are private. No public read, no public listing.
- Separate credentials per role:

| Role | raw | clean | packages |
| --- | --- | --- | --- |
| DE pipeline | read and write | read and write | none |
| Backend | none | none | read and write |
| AI | none | none | none |

- Users download packages through short-lived presigned URLs (for example 15 minutes) issued by Backend.
- Encryption at rest (server-side) and TLS in transit.
- Credentials come from environment variables, never from the repo.
- Raw pages are untrusted data. They are stored and parsed, never executed or rendered.
- Upload size limit per object (proposed: 20 MB). Larger files are skipped and logged.

## 6. Local development: MinIO (needs DevOps approval)

MinIO speaks the S3 API, so the same code runs locally and in production (AWS S3, Cloudflare R2
or similar). Proposed addition to the root `compose.yaml`, to be added by DevOps:

- Service `minio`, bound to `127.0.0.1` only.
- A one-off init step that creates the three buckets and the raw lifecycle rule.
- Throwaway local credentials in `.env.example`.

Environment variables the pipeline reads:

| Variable | Example (local) |
| --- | --- |
| `S3_ENDPOINT` | `http://127.0.0.1:9000` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | from `.env` |
| `S3_BUCKET_RAW` | `skillforge-raw` |
| `S3_BUCKET_CLEAN` | `skillforge-clean` |
| `S3_BUCKET_PACKAGES` | `skillforge-packages` |

## 7. Open questions

- Backend: do you own the `packages` bucket, and how many package versions do we keep?
- DevOps: approve MinIO in `compose.yaml`, and which provider is used for staging (OPS-06)?
- DevOps: the 20 MB size limit and the 15-minute presigned URL time are proposals.
- DevOps: the 35-day safety-net rule on the raw bucket, and that `LastModified` of an object is kept when the upload is skipped.
