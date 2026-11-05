"""DE-03: object storage interface, keys, the S3 adapter (fake client, no network) and the daily job (real Postgres)."""
import uuid
from datetime import timedelta

import pytest
from fakes import T0, FakeEmbed, FakeExtract, fake_normalise_url, page_bytes

from skillforge_data.pipeline.config import PipelineConfig
from skillforge_data.pipeline.process import RawPage, process_document
from skillforge_data.storage import (
    BUCKET_CLEAN,
    BUCKET_RAW,
    MemoryStorage,
    ObjectNotFound,
    clean_key,
    raw_key,
)
from skillforge_data.storage.jobs import (
    expire_raw,
    reconcile_raw,
    run_daily_storage_job,
    sweep_orphans,
)
from skillforge_data.storage.s3 import S3Storage

H = "ab" * 32


# ----------------------------------------------------------------------------------------------- keys
def test_raw_and_clean_keys_follow_the_layout_document():
    assert raw_key("Docs.Python.org", H, "text/html; charset=utf-8") == f"docs.python.org/ab/{H}.html"
    assert raw_key("example.org", H, "application/pdf").endswith(".pdf")
    assert raw_key("example.org", H, None).endswith(".bin")
    doc = uuid.uuid4()
    assert clean_key(doc, "f" * 64) == f"{doc}/{'f' * 64}.txt"
    assert clean_key(doc, None) == f"{doc}/v0.txt"
    with pytest.raises(ValueError):
        raw_key("example.org", "short")


# ------------------------------------------------------------------------------------- memory storage
def test_put_never_overwrites_and_keeps_the_first_upload_time():
    times = iter([T0, T0 + timedelta(days=5)])
    storage = MemoryStorage(clock=lambda: next(times))
    assert storage.put("b", "k", b"one") is True
    assert storage.put("b", "k", b"two") is False
    assert storage.get("b", "k") == b"one"
    assert storage.head("b", "k").last_modified == T0


def test_get_of_a_missing_key_raises_and_delete_of_a_missing_key_does_not():
    storage = MemoryStorage()
    with pytest.raises(ObjectNotFound):
        storage.get("b", "nope")
    storage.delete("b", "nope")
    assert storage.head("b", "nope") is None and not storage.exists("b", "nope")


def test_list_returns_only_the_prefix_of_the_bucket():
    storage = MemoryStorage()
    for bucket, key in (("b", "a/1"), ("b", "a/2"), ("b", "c/1"), ("other", "a/9")):
        storage.put(bucket, key, b"x")
    assert [o.key for o in storage.list("b", "a/")] == ["a/1", "a/2"]
    assert [o.key for o in storage.list("b")] == ["a/1", "a/2", "c/1"]


# ----------------------------------------------------------------------------------------- S3 adapter
class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    """The few boto3 client calls S3Storage uses."""

    def __init__(self):
        self.objects = {}
        self.put_calls = 0

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("404")
        body, modified = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "LastModified": modified}

    def put_object(self, Bucket, Key, Body, **extra):
        self.put_calls += 1
        self.objects[(Bucket, Key)] = (Body, T0)

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey")
        body = self.objects[(Bucket, Key)][0]
        return {"Body": type("Body", (), {"read": lambda self: body})()}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for (b, k) in client.objects if b == Bucket and k.startswith(Prefix))
                for start in range(0, max(len(keys), 1), 2):            # two keys per page
                    yield {"Contents": [{"Key": k, "Size": len(client.objects[(Bucket, k)][0]),
                                         "LastModified": T0} for k in keys[start:start + 2]]}

        return Paginator()


def test_the_s3_adapter_puts_once_gets_lists_and_deletes():
    client = FakeS3Client()
    storage = S3Storage(client)
    assert storage.put("b", "x/1", b"one", content_type="text/plain", metadata={"k": "v"}) is True
    assert storage.put("b", "x/1", b"two") is False and client.put_calls == 1
    assert storage.get("b", "x/1") == b"one"
    assert storage.head("b", "x/1").size == 3 and storage.exists("b", "x/1")
    for i in range(2, 6):
        storage.put("b", f"x/{i}", b"z")
    assert [o.key for o in storage.list("b", "x/")] == [f"x/{i}" for i in range(1, 6)], "all pages are read"
    storage.delete("b", "x/1")
    storage.delete("b", "x/1")
    assert not storage.exists("b", "x/1")
    with pytest.raises(ObjectNotFound):
        storage.get("b", "x/1")


def test_the_s3_adapter_does_not_hide_other_errors():
    class Broken(FakeS3Client):
        def head_object(self, Bucket, Key):
            raise FakeClientError("AccessDenied")

    with pytest.raises(FakeClientError):
        S3Storage(Broken()).exists("b", "k")


def test_from_env_names_what_is_missing_and_needs_no_network():
    with pytest.raises(RuntimeError, match="S3_ENDPOINT.*S3_ACCESS_KEY.*S3_SECRET_KEY"):
        S3Storage.from_env({})


# ------------------------------------------------------------------------------------------ daily job
CONFIG = PipelineConfig(pipeline_version="p1", embedding_version="rev-1")


class World:
    """Pages processed into a real database with an in-memory storage whose clock the test controls."""

    def __init__(self, db):
        self.db = db
        self.now = T0
        self.storage = MemoryStorage(clock=lambda: self.now)
        self.extract, self.embed = FakeExtract(), FakeEmbed()

    def process(self, content, url="https://docs.example.org/a", days=0):
        self.now = T0 + timedelta(days=days)
        page = RawPage(url=url, content=content, fetched_at=self.now, domains=["technology/ai"], content_type="text/html")
        return process_document(self.db, page, config=CONFIG, extract=self.extract, embed=self.embed,
                                normalise_url=fake_normalise_url, storage=self.storage)

    def row(self, document_id):
        return self.db.execute(
            "SELECT raw_object_key, raw_deleted_at FROM knowledge.documents WHERE id = %s", (document_id,)).fetchone()


@pytest.fixture
def world(db):
    return World(db)


A = page_bytes(("alpha one",), title="A")
B = page_bytes(("bravo one",), title="B")


def test_raw_is_deleted_30_days_after_the_first_upload_and_the_row_stays(world):
    result = world.process(A)
    key = world.row(result.document_id)[0]
    young = expire_raw(world.db, world.storage, now=T0 + timedelta(days=29, hours=23))
    assert young.raw_expired == 0 and world.storage.exists(BUCKET_RAW, key)

    old = expire_raw(world.db, world.storage, now=T0 + timedelta(days=30))
    assert old.raw_expired == 1 and old.rows_cleared == 1
    assert world.row(result.document_id) == (None, T0 + timedelta(days=30)), "key cleared, deletion time set, row kept"
    assert not world.storage.exists(BUCKET_RAW, key)
    assert world.db.execute("SELECT count(*) FROM knowledge.chunks").fetchone()[0] == 1, "chunks are not affected"


def test_a_refetch_of_unchanged_content_does_not_extend_the_30_days(world):
    first = world.process(A)
    again = world.process(A, days=20)
    assert again.status == "unchanged"
    assert world.db.execute("SELECT fetched_at FROM knowledge.documents").fetchone()[0] == T0 + timedelta(days=20)
    report = expire_raw(world.db, world.storage, now=T0 + timedelta(days=31))
    assert report.raw_expired == 1 and world.row(first.document_id)[0] is None


def test_a_returning_version_does_not_restart_the_clock_while_its_raw_still_exists(world):
    first = world.process(A)
    world.process(B, days=10)
    world.process(A, days=20)                        # A, B, A: the upload of A is skipped, the object is the old one
    expire_raw(world.db, world.storage, now=T0 + timedelta(days=31))
    assert world.row(first.document_id)[0] is None, "30 days counted from the first upload (day 0)"


def test_when_the_raw_is_gone_a_returning_page_is_uploaded_again_with_its_own_30_days(world):
    first = world.process(A)
    world.process(B, days=1)
    expire_raw(world.db, world.storage, now=T0 + timedelta(days=31))
    back = world.process(A, days=40)
    key = world.row(back.document_id)[0]
    assert back.document_id == first.document_id and key is not None and world.row(back.document_id)[1] is None
    expire_raw(world.db, world.storage, now=T0 + timedelta(days=60))        # 20 days after the new upload
    assert world.storage.exists(BUCKET_RAW, key) and world.row(back.document_id)[0] == key
    expire_raw(world.db, world.storage, now=T0 + timedelta(days=71))        # 31 days after it
    assert not world.storage.exists(BUCKET_RAW, key) and world.row(back.document_id)[0] is None

def test_two_documents_sharing_one_raw_object_are_both_cleared(world):
    first = world.process(A, url="https://docs.example.org/one")
    second = world.process(A, url="https://docs.example.org/two")    # same host, same bytes: the same raw key
    assert world.row(first.document_id)[0] == world.row(second.document_id)[0]
    report = expire_raw(world.db, world.storage, now=T0 + timedelta(days=31))
    assert report.raw_expired == 1 and report.rows_cleared == 2
    assert world.row(first.document_id)[0] is None and world.row(second.document_id)[0] is None


def test_the_database_is_cleared_before_the_object_is_deleted(world):
    seen = []

    class Spy(MemoryStorage):
        def delete(self, bucket, key):
            if bucket == BUCKET_RAW:
                seen.append(world.db.execute(
                    "SELECT raw_object_key FROM knowledge.documents WHERE raw_object_key = %s", (key,)).fetchall())
            super().delete(bucket, key)

    world.storage = Spy(clock=lambda: world.now)
    world.process(A)
    expire_raw(world.db, world.storage, now=T0 + timedelta(days=31))
    assert seen == [[]], "when the object was deleted, no row pointed to it any more"

def test_if_the_object_cannot_be_deleted_the_row_is_still_clean_and_the_sweep_finishes_the_job(world):
    class Flaky(MemoryStorage):
        fail_deletes = False

        def delete(self, bucket, key):
            if self.fail_deletes:
                raise OSError("storage unavailable")
            super().delete(bucket, key)

    world.storage = flaky = Flaky(clock=lambda: world.now)
    result = world.process(A)
    key = world.row(result.document_id)[0]
    flaky.fail_deletes = True
    report = expire_raw(world.db, flaky, now=T0 + timedelta(days=31))
    assert report.errors and world.row(result.document_id)[0] is None, "the row never points to a missing object"
    assert flaky.exists(BUCKET_RAW, key), "the object is left behind: an orphan"
    flaky.fail_deletes = False
    assert sweep_orphans(world.db, flaky, now=T0 + timedelta(days=32)).orphans_deleted == 1
    assert not flaky.exists(BUCKET_RAW, key)

def test_a_missing_raw_object_is_repaired_in_the_database(world):
    result = world.process(A)
    key = world.row(result.document_id)[0]
    world.storage.delete(BUCKET_RAW, key)                  # removed by the 35-day bucket rule, for example
    report = reconcile_raw(world.db, world.storage, now=T0 + timedelta(days=36))
    assert report.rows_cleared == 1 and world.row(result.document_id) == (None, T0 + timedelta(days=36))


def test_orphans_older_than_24_hours_are_swept_and_referenced_objects_are_not(world):
    result = world.process(A)
    raw = world.row(result.document_id)[0]
    clean = world.db.execute("SELECT clean_object_key FROM knowledge.documents").fetchone()[0]
    world.storage.put(BUCKET_RAW, "docs.example.org/zz/orphan.html", b"x")                 # no row points to it
    world.storage.put(BUCKET_CLEAN, f"{uuid.uuid4()}/v0.txt", b"x")                         # a document that does not exist
    other_extraction = f"{result.document_id}/{'e' * 64}.txt"
    world.storage.put(BUCKET_CLEAN, other_extraction, b"x")                                 # a live document, other version

    soon = sweep_orphans(world.db, world.storage, now=T0 + timedelta(hours=23))
    assert soon.orphans_deleted == 0, "too young: the upload may belong to a transaction that is still running"
    later = sweep_orphans(world.db, world.storage, now=T0 + timedelta(hours=25))
    assert later.orphans_deleted == 2
    assert world.storage.exists(BUCKET_RAW, raw) and world.storage.exists(BUCKET_CLEAN, clean)
    assert world.storage.exists(BUCKET_CLEAN, other_extraction), "kept until the rebuild switches versions"


def test_the_daily_job_runs_all_three_steps(world):
    result = world.process(A)
    world.now = T0 + timedelta(days=29)                  # an upload nobody references: 2 days old when the job runs
    world.storage.put(BUCKET_RAW, "docs.example.org/zz/orphan.html", b"x")
    report = run_daily_storage_job(world.db, world.storage, now=T0 + timedelta(days=31))
    assert (report.raw_expired, report.rows_cleared, report.orphans_deleted) == (1, 1, 1) and not report.errors
    assert world.row(result.document_id)[0] is None
