"""DE-07: MinHash duplicates, the rule that duplicates never make content disappear, and the duplicate rate per crawl."""
from datetime import UTC, datetime, timedelta

import pytest
from fakes import T0, FakeEmbed, FakeExtract, fake_normalise_url, page_bytes

from skillforge_data.crawler import Crawler, FetchConfig
from skillforge_data.crawler.fetcher import FetchResult
from skillforge_data.dedup import (
    DedupConfig,
    DuplicateFinder,
    MinHasher,
    duplicate_rate,
    jaccard,
    shingles,
)
from skillforge_data.pipeline.config import PipelineConfig
from skillforge_data.pipeline.process import RawPage, process_document

CONFIG = PipelineConfig(pipeline_version="p1", embedding_version="rev-1")


def words(seed: str, n: int = 150, change: int | None = None) -> str:
    """A text of n distinct words; `change` replaces one word, which makes a near copy."""
    return " ".join(f"{seed}w{i}" if i != change else "changed" for i in range(n))


# --------------------------------------------------------------------------------------------- the hash
def test_shingles_are_overlapping_lower_case_word_groups():
    assert shingles("One two THREE four five six", 5) == {"one two three four five", "two three four five six"}
    assert shingles("only three words", 5) == {"only three words"}
    assert shingles("   ", 5) == set()


def test_the_signature_is_deterministic_and_fixed_in_size():
    hasher = MinHasher()
    a, again = hasher.signature(words("a")), MinHasher().signature(words("a"))
    assert a == again and len(a) == 128 * 8
    assert hasher.signature("") is None


def test_the_estimated_similarity_follows_the_text():
    h = MinHasher()
    base = h.signature(words("a"))
    assert jaccard(base, base) == 1.0
    assert jaccard(base, h.signature(words("a", change=70))) > 0.85, "one word of 150 changed"
    assert jaccard(base, h.signature(words("b"))) < 0.1, "unrelated text"


def test_a_bad_config_is_refused():
    with pytest.raises(ValueError):
        DedupConfig(num_perm=100, bands=16)


# --------------------------------------------------------------------------------------- the pipeline
class World:
    def __init__(self, db, dedup=True):
        self.db = db
        self.extract, self.embed = FakeExtract(), FakeEmbed()
        self.finder = DuplicateFinder() if dedup else None
        self.day = 0

    def run(self, url, text, *, title="Page", reject=()):
        self.day += 1
        page = RawPage(url=url, content=page_bytes((text,), title=title, reject=reject),
                       fetched_at=T0 + timedelta(days=self.day), domains=["technology/ai"], content_type="text/html")
        return process_document(self.db, page, config=CONFIG, extract=self.extract, embed=self.embed,
                                normalise_url=fake_normalise_url, dedup=self.finder)

    def one(self, sql, *params):
        return self.db.execute(sql, params).fetchone()[0]

    def visible(self, view="knowledge.retrievable_chunks"):
        return sorted(r[0] for r in self.db.execute(f"SELECT chunk_id FROM {view}").fetchall())

    def chunk_ids_of(self, document_id):
        return sorted(r[0] for r in self.db.execute(
            "SELECT chunk_id FROM knowledge.chunks WHERE document_id = %s", (document_id,)).fetchall())

    def duplicate_of(self, document_id):
        return self.one("SELECT duplicate_of FROM knowledge.documents WHERE id = %s", document_id)


@pytest.fixture
def world(db):
    return World(db)


URL1, URL2, URL3 = "https://one.example.org/page", "https://two.example.org/copy", "https://three.example.org/other"
T1, T2 = words("a"), words("b")


def test_a_copy_on_another_source_is_marked_and_hidden_but_keeps_its_chunks(world):
    first = world.run(URL1, T1)
    copy = world.run(URL2, T1)
    assert first.duplicate_of is None and copy.duplicate_of == first.document_id
    assert world.duplicate_of(copy.document_id) == first.document_id
    assert world.chunk_ids_of(copy.document_id), "the copy keeps its chunks and embeddings"
    assert world.one("SELECT count(*) FROM knowledge.embeddings") == 2
    assert world.visible() == world.chunk_ids_of(first.document_id), "only the first copy is shown"
    assert world.visible("knowledge.knowledge_chunks") == world.chunk_ids_of(first.document_id)


def test_a_near_copy_is_a_duplicate_and_unrelated_pages_are_not(world):
    first = world.run(URL1, T1)
    near = world.run(URL2, words("a", change=70))
    other = world.run(URL3, T2)
    assert near.duplicate_of == first.document_id
    assert other.duplicate_of is None


def test_a_new_version_of_the_same_page_is_never_its_own_duplicate(world):
    world.run(URL1, T1)
    newer = world.run(URL1, words("a", change=70))
    assert newer.duplicate_of is None
    assert world.one("SELECT count(*) FROM knowledge.documents WHERE duplicate_of IS NOT NULL") == 0


def test_the_signature_is_stored_and_the_same_text_gives_the_same_bytes(world):
    first = world.run(URL1, T1)
    copy = world.run(URL2, T1)
    sig = world.one("SELECT minhash FROM knowledge.documents WHERE id = %s", first.document_id)
    assert len(bytes(sig)) == 1024
    assert bytes(sig) == bytes(world.one("SELECT minhash FROM knowledge.documents WHERE id = %s", copy.document_id))


def test_without_the_finder_nothing_about_duplicates_changes(db):
    plain = World(db, dedup=False)
    plain.run(URL1, T1)
    copy = plain.run(URL2, T1)
    assert copy.duplicate_of is None
    assert plain.one("SELECT count(*) FROM knowledge.documents WHERE minhash IS NOT NULL") == 0
    assert len(plain.visible()) == 2, "as in P1: both copies are shown"


def test_a_new_finder_loads_the_signatures_from_the_database(world, db):
    first = world.run(URL1, T1)
    fresh = World(db)
    fresh.day = world.day
    fresh.finder = DuplicateFinder.load(db)
    assert len(fresh.finder) == 1
    assert fresh.run(URL2, T1).duplicate_of == first.document_id


# ---------------------------------------------- "duplicates must not make content disappear" (architecture doc)
def test_when_the_canonical_page_changes_its_copy_is_shown(world):
    """B, C a copy of B; B is superseded: C's chunks must be in retrievable_chunks and knowledge_chunks."""
    b = world.run(URL1, T1)
    c = world.run(URL2, T1)
    assert world.visible() == world.chunk_ids_of(b.document_id)

    new_b = world.run(URL1, T2)                       # the page of B now says something else
    assert world.duplicate_of(c.document_id) is None, "C is the canonical copy now"
    shown = world.visible()
    assert set(world.chunk_ids_of(c.document_id)) <= set(shown)
    assert set(world.chunk_ids_of(new_b.document_id)) <= set(shown)
    assert set(world.chunk_ids_of(c.document_id)) <= set(world.visible("knowledge.knowledge_chunks"))


def test_when_the_changed_page_is_still_a_copy_of_the_promoted_one_it_stays_hidden(world):
    world.run(URL1, T1)
    c = world.run(URL2, T1)
    new_b = world.run(URL1, words("a", change=70))    # B changed a little: still a copy, now of C
    assert new_b.duplicate_of == c.document_id
    assert world.visible() == world.chunk_ids_of(c.document_id), "one copy shown, not two"


def test_a_b_a_with_a_copy_shows_one_copy_at_the_end(world):
    a = world.run(URL1, T1)
    c = world.run(URL2, T1)
    world.run(URL1, T2)                               # B
    back = world.run(URL1, T1)                        # A returns
    assert back.document_id == a.document_id, "the old row came back"
    assert back.duplicate_of == c.document_id, "and it is a copy of the promoted C"
    assert world.visible() == world.chunk_ids_of(c.document_id)


def test_a_rejected_new_version_also_promotes_the_copy(world):
    world.run(URL1, T1)
    c = world.run(URL2, T1)
    rejected = world.run(URL1, "paywall", reject=("paywall_or_login",))
    assert rejected.status == "rejected"
    assert world.duplicate_of(c.document_id) is None
    assert world.visible() == world.chunk_ids_of(c.document_id)


def test_if_no_copy_is_current_nothing_is_promoted_and_nothing_breaks(world):
    b = world.run(URL1, T1)
    c = world.run(URL2, T1)
    world.run(URL2, T2)                               # C's page changes: its old row is not current any more
    world.run(URL1, words("z"))                       # now B is superseded; the only copy points to a non-current row
    assert world.duplicate_of(c.document_id) == b.document_id, "left as it was: nothing live carries that content"
    assert world.one("SELECT count(*) FROM knowledge.documents WHERE is_current AND duplicate_of IS NOT NULL") == 0


# --------------------------------------------------------------------------------- rate per crawl run
class StubFetcher:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url, validators=None):
        return FetchResult(url=url, outcome="ok", final_url=url, http_status=200, content=self.pages[url],
                           content_type="text/html", robots_allowed=True, robots_checked_at=datetime.now(UTC))


def test_the_duplicate_rate_of_a_crawl_is_reported(world, db):
    pages = {URL1: page_bytes((T1,), title="One"), URL2: page_bytes((T1,), title="Two"), URL3: page_bytes((T2,), title="Three")}
    crawler = Crawler(db, StubFetcher(pages), fake_normalise_url, config=FetchConfig(), pipeline_version="p1")

    def handler(page):
        return process_document(db, page, config=CONFIG, extract=world.extract, embed=world.embed,
                                normalise_url=fake_normalise_url, dedup=world.finder)

    summary = crawler.run([URL1, URL2, URL3], domains=["technology/ai"], on_page=handler)
    assert (summary.fetched, summary.duplicates) == (3, 1)
    assert db.execute("SELECT pages_fetched, pages_duplicate FROM knowledge.crawl_runs WHERE id = %s",
                      (summary.run_id,)).fetchone() == (3, 1)
    assert duplicate_rate(db, summary.run_id) == pytest.approx(1 / 3)


def test_the_duplicate_rate_of_a_run_with_no_pages_is_none(db):
    crawler = Crawler(db, StubFetcher({}), fake_normalise_url, config=FetchConfig(), pipeline_version="p1")
    assert duplicate_rate(db, crawler.run([], domains=["technology/ai"]).run_id) is None
