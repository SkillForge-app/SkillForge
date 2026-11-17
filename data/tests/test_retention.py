"""DE-13: retention of superseded documents (90 days) and crawl runs (12 months), and the daily job that runs it beside the raw job."""
from datetime import UTC, datetime, timedelta

from skillforge_data.storage import BUCKET_CLEAN, BUCKET_RAW, MemoryStorage
from skillforge_data.storage.daily import run_daily_jobs
from skillforge_data.storage.retention import (
    delete_old_crawl_runs,
    delete_superseded_documents,
    run_daily_retention_job,
)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def add_source(db, n):
    return db.execute("INSERT INTO knowledge.sources (url, host, source_type) VALUES (%s, 'x.org', 'web_page') RETURNING id",
                      (f"https://x.org/{n}",)).fetchone()[0]


def add_doc(db, source, n, *, current, age_days, raw_key=None, clean_key=None, run=None):
    return db.execute(
        "INSERT INTO knowledge.documents (source_id, fetched_at, content_hash, pipeline_version, title, is_current, raw_object_key, "
        "clean_object_key, crawl_run_id) VALUES (%s, %s, %s, 'p1', 'T', %s, %s, %s, %s) RETURNING id",
        (source, NOW - age_days * DAY, f"{n:064x}", current, raw_key, clean_key, run)).fetchone()[0]


def add_chunk(db, doc, n):
    chunk = db.execute(
        "INSERT INTO knowledge.chunks (chunk_id, document_id, chunk_index, text, content_hash, chunk_config, chunk_config_hash) "
        "VALUES (%s, %s, 0, 't', %s, %s::jsonb, 'cfg') RETURNING id",
        (f"x-{n}", doc, f"{n:064x}",
         '{"size":1,"overlap":0,"splitter":"sentence","pipeline_version":"p","extract_fingerprint":"' + "a" * 64 + '"}')).fetchone()[0]
    db.execute("INSERT INTO knowledge.embeddings (chunk_id, embedding, embedding_model, embedding_version, domains) "
               "VALUES (%s, l2_normalize(array_fill(0.1::real, ARRAY[384])::vector), 'local/BAAI/bge-small-en-v1.5', 'v1', ARRAY['technology/ai'])", (chunk,))
    return chunk


def add_run(db, *, age_days, status="succeeded"):
    return db.execute(
        "INSERT INTO knowledge.crawl_runs (started_at, finished_at, status, user_agent, pipeline_version) "
        "VALUES (%s, %s, %s, 'ua', 'p1') RETURNING id",
        (NOW - age_days * DAY, None if status == "running" else NOW - age_days * DAY + timedelta(minutes=5), status)).fetchone()[0]


def count(db, table):
    return db.execute(f"SELECT count(*) FROM knowledge.{table}").fetchone()[0]


# ------------------------------------------------------------------------------------------ superseded documents
def test_superseded_documents_older_than_90_days_are_deleted_with_their_chunks_and_embeddings(db):
    source = add_source(db, 1)
    old = add_doc(db, source, 1, current=False, age_days=91)
    add_chunk(db, old, 1)
    report = delete_superseded_documents(db, None, now=NOW)
    assert report.documents_deleted == 1
    assert (count(db, "documents"), count(db, "chunks"), count(db, "embeddings")) == (0, 0, 0)


def test_a_superseded_document_inside_90_days_stays_and_the_boundary_is_exact(db):
    source = add_source(db, 1)
    add_doc(db, source, 1, current=False, age_days=89)
    exactly = add_doc(db, source, 2, current=False, age_days=90)
    assert delete_superseded_documents(db, None, now=NOW).documents_deleted == 0, "90 days exactly is kept: older than 90 is deleted"
    assert db.execute("SELECT count(*) FROM knowledge.documents WHERE id = %s", (exactly,)).fetchone()[0] == 1


def test_a_current_document_is_never_deleted_however_old(db):
    source = add_source(db, 1)
    add_doc(db, source, 1, current=True, age_days=400)
    assert delete_superseded_documents(db, None, now=NOW).documents_deleted == 0 and count(db, "documents") == 1


def test_the_database_goes_first_and_the_objects_after(db):
    storage = MemoryStorage()
    storage.put(BUCKET_RAW, "x.org/aa/raw1.html", b"raw")
    storage.put(BUCKET_CLEAN, "doc/clean1.txt", b"clean")
    source = add_source(db, 1)
    add_doc(db, source, 1, current=False, age_days=120, raw_key="x.org/aa/raw1.html", clean_key="doc/clean1.txt")
    seen = []

    class Watching(MemoryStorage):
        def delete(self, bucket, key):
            seen.append(db.execute("SELECT count(*) FROM knowledge.documents").fetchone()[0])   # the row is already gone
            super().delete(bucket, key)

    watching = Watching()
    watching._objects = storage._objects
    report = delete_superseded_documents(db, watching, now=NOW)
    assert seen == [0, 0] and report.objects_deleted == 2
    assert not storage.exists(BUCKET_RAW, "x.org/aa/raw1.html") and not storage.exists(BUCKET_CLEAN, "doc/clean1.txt")


def test_a_raw_object_shared_with_a_remaining_document_is_kept(db):
    storage = MemoryStorage()
    storage.put(BUCKET_RAW, "x.org/aa/shared.html", b"same bytes")
    a, b = add_source(db, 1), add_source(db, 2)
    add_doc(db, a, 1, current=False, age_days=120, raw_key="x.org/aa/shared.html")
    add_doc(db, b, 2, current=True, age_days=1, raw_key="x.org/aa/shared.html")
    report = delete_superseded_documents(db, storage, now=NOW)
    assert report.documents_deleted == 1 and report.objects_deleted == 0
    assert storage.exists(BUCKET_RAW, "x.org/aa/shared.html")


def test_a_failed_object_delete_is_reported_and_the_row_is_already_gone(db):
    class Failing(MemoryStorage):
        def delete(self, bucket, key):
            raise ConnectionError("storage down")

    storage = Failing()
    storage.put(BUCKET_RAW, "x.org/aa/r.html", b"raw")
    add_doc(db, add_source(db, 1), 1, current=False, age_days=120, raw_key="x.org/aa/r.html")
    report = delete_superseded_documents(db, storage, now=NOW)
    assert report.documents_deleted == 1 and report.objects_deleted == 0 and "storage down" in report.errors[0]
    assert count(db, "documents") == 0 and storage.exists(BUCKET_RAW, "x.org/aa/r.html"), "an orphan for the sweep, not a dangling row"


def test_deleting_in_batches_deletes_everything(db):
    source = add_source(db, 1)
    for n in range(7):
        add_doc(db, source, n, current=False, age_days=100 + n)
    assert delete_superseded_documents(db, None, now=NOW, batch=3).documents_deleted == 7


def test_a_duplicate_pointing_at_a_deleted_document_survives_with_the_pointer_cleared(db):
    a, b = add_source(db, 1), add_source(db, 2)
    original = add_doc(db, a, 1, current=False, age_days=120)
    copy = add_doc(db, b, 2, current=True, age_days=1)
    db.execute("UPDATE knowledge.documents SET duplicate_of = %s WHERE id = %s", (original, copy))
    delete_superseded_documents(db, None, now=NOW)
    assert db.execute("SELECT duplicate_of FROM knowledge.documents WHERE id = %s", (copy,)).fetchone()[0] is None


# ----------------------------------------------------------------------------------------------- crawl runs
def test_crawl_runs_older_than_12_months_are_deleted_and_their_documents_stay(db):
    old, new = add_run(db, age_days=400), add_run(db, age_days=300)
    source = add_source(db, 1)
    doc = add_doc(db, source, 1, current=True, age_days=1, run=old)
    report = delete_old_crawl_runs(db, now=NOW)
    assert report.crawl_runs_deleted == 1
    assert db.execute("SELECT id FROM knowledge.crawl_runs").fetchone()[0] == new
    assert db.execute("SELECT crawl_run_id FROM knowledge.documents WHERE id = %s", (doc,)).fetchone()[0] is None


def test_a_running_run_is_not_deleted_and_the_boundary_is_365_days(db):
    add_run(db, age_days=500, status="running")
    add_run(db, age_days=365)
    add_run(db, age_days=366)
    assert delete_old_crawl_runs(db, now=NOW).crawl_runs_deleted == 1
    assert count(db, "crawl_runs") == 2


# ------------------------------------------------------------------------------------------------ daily job
def test_the_retention_job_is_idempotent(db):
    source = add_source(db, 1)
    add_doc(db, source, 1, current=False, age_days=120)
    add_run(db, age_days=400)
    first = run_daily_retention_job(db, None, now=NOW)
    second = run_daily_retention_job(db, None, now=NOW)
    assert (first.documents_deleted, first.crawl_runs_deleted) == (1, 1)
    assert (second.documents_deleted, second.crawl_runs_deleted, second.objects_deleted) == (0, 0, 0)


def test_the_daily_job_runs_the_raw_job_then_retention_then_the_sweep(db):
    storage = MemoryStorage(clock=lambda: NOW - 40 * DAY)                 # every object is 40 days old
    storage.put(BUCKET_RAW, "x.org/aa/old.html", b"raw")                  # 30-day rule: expires
    storage.put(BUCKET_CLEAN, "ffffffff-ffff-ffff-ffff-ffffffffffff/f.txt", b"orphan")   # no row: the sweep removes it
    source = add_source(db, 1)
    add_doc(db, source, 1, current=False, age_days=120, raw_key="x.org/aa/old.html")
    report = run_daily_jobs(db, storage, now=NOW)
    assert report.storage.raw_expired == 1 and report.retention.documents_deleted == 1 and report.storage.orphans_deleted == 1
    assert report.errors == [] and count(db, "documents") == 0
    assert list(storage.list(BUCKET_RAW)) == [] and list(storage.list(BUCKET_CLEAN)) == []
