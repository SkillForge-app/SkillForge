"""DE-06: every chunk is traceable to its source (URL, retrieval date, licence, content hash, crawl run)."""
import hashlib
from datetime import timedelta

import pytest
from fakes import T0, FakeEmbed, FakeExtract, fake_normalise_url, page_bytes

from skillforge_data.pipeline.config import PipelineConfig
from skillforge_data.pipeline.process import RawPage, process_document
from skillforge_data.provenance import check_provenance, get_provenance
from skillforge_data.storage import BUCKET_RAW, MemoryStorage
from skillforge_data.store import start_crawl_run

CONFIG = PipelineConfig(pipeline_version="p1", embedding_version="rev-1")
URL = "https://Docs.Example.org/guide/"
CANONICAL = "https://docs.example.org/guide"
CONTENT = page_bytes(("alpha one", "alpha two"), title="Guide")


@pytest.fixture
def world(db):
    class World:
        def __init__(self):
            self.db = db
            self.storage = MemoryStorage()
            self.extract, self.embed = FakeExtract(), FakeEmbed()

        def process(self, content=CONTENT, at=T0, **kw):
            page = RawPage(url=URL, content=content, fetched_at=at, domains=["technology/ai"], **kw)
            return process_document(db, page, config=CONFIG, extract=self.extract, embed=self.embed,
                                    normalise_url=fake_normalise_url, storage=self.storage)

    return World()


def test_a_chunk_leads_back_to_url_date_licence_hashes_and_run(world):
    run_id = start_crawl_run(world.db, user_agent="test", pipeline_version="p1", config={})
    result = world.process(license="MIT", license_source="page", crawl_run_id=run_id)
    [chunk_id] = [r[0] for r in world.db.execute("SELECT chunk_id FROM knowledge.chunks WHERE chunk_index = 0")]
    [trace] = get_provenance(world.db, chunk_id)
    assert trace.url == CANONICAL and trace.host == "docs.example.org"
    assert trace.retrieved_at == T0 and trace.license == "MIT"
    assert trace.document_id == result.document_id and trace.crawl_run_id == run_id and trace.title == "Guide"
    assert trace.chunk_hash == hashlib.sha256(b"alpha one").hexdigest()
    assert trace.document_hash == hashlib.sha256(CONTENT).hexdigest()


def test_the_retrieval_date_follows_the_latest_fetch_of_the_same_content(world):
    world.process()
    world.process(at=T0 + timedelta(days=3))
    [chunk_id] = [r[0] for r in world.db.execute("SELECT chunk_id FROM knowledge.chunks WHERE chunk_index = 0")]
    assert get_provenance(world.db, chunk_id)[0].retrieved_at == T0 + timedelta(days=3)


def test_every_chunk_of_a_healthy_database_is_traceable(world):
    run_id = start_crawl_run(world.db, user_agent="test", pipeline_version="p1", config={})
    world.process(crawl_run_id=run_id, license="Apache-2.0")
    report = check_provenance(world.db, world.storage)
    assert report.ok, report.problems
    assert report.chunks_checked == 2 and report.unknown_license == 0 and report.without_crawl_run == 0


def test_unknown_licence_and_a_missing_run_are_reported_but_are_not_problems(world):
    world.process()                                       # licence 'unknown', no crawl run
    report = check_provenance(world.db)
    assert report.ok and report.unknown_license == 2 and report.without_crawl_run == 2


def test_a_chunk_whose_hash_is_not_its_text_hash_is_a_problem(world):
    world.process()
    world.db.execute("UPDATE knowledge.chunks SET content_hash = %s WHERE chunk_index = 0", ("0" * 64,))
    report = check_provenance(world.db)
    assert not report.ok and "sha256 of its text" in report.problems[0]


def test_a_raw_object_that_does_not_match_its_hash_or_is_missing_is_a_problem(world):
    result = world.process()
    key = world.db.execute("SELECT raw_object_key FROM knowledge.documents WHERE id = %s", (result.document_id,)).fetchone()[0]
    assert check_provenance(world.db, world.storage).ok
    world.storage.delete(BUCKET_RAW, key)
    world.storage.put(BUCKET_RAW, key, b"tampered")
    assert "does not match" in check_provenance(world.db, world.storage).problems[0]
    world.storage.delete(BUCKET_RAW, key)
    assert "missing" in check_provenance(world.db, world.storage).problems[0]


def test_the_chunks_of_a_replaced_version_are_gone_and_the_new_ones_are_traceable(world):
    world.process()
    world.process(page_bytes(("bravo one",), title="Guide B"), at=T0 + timedelta(days=1))
    report = check_provenance(world.db, world.storage)
    assert report.ok and report.chunks_checked == 1
    [trace] = get_provenance(world.db, world.db.execute("SELECT chunk_id FROM knowledge.chunks").fetchone()[0])
    assert trace.title == "Guide B"
