"""DE-08: the SKILL.md collector, with a fake GitHub client (no network).

Rule under test: only files with an open licence reach the tables; a refused or unknown one is counted and nothing about it is stored
(not even its content hash).
"""
import hashlib
from datetime import UTC, datetime

import pytest

from skillforge_data.corpus import CorpusCollector, SkillFileHit
from skillforge_data.crawler.ratelimit import HostRateLimiter
from skillforge_data.storage import BUCKET_RAW, MemoryStorage

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


class FakeGitHub:
    def __init__(self, repos: dict[str, tuple[str | None, bytes]], per_page: int = 2):
        self.repos = repos                           # repo -> (SPDX id or None, content of its SKILL.md)
        self.per_page = per_page
        self.fetched: list[str] = []
        self.licence_calls: list[str] = []

    def hits(self):
        return [SkillFileHit(r, "skills/a/SKILL.md", f"https://github.com/{r}/blob/main/skills/a/SKILL.md") for r in self.repos]

    def search_skill_files(self, query, *, page):
        hits = self.hits()
        return hits[(page - 1) * self.per_page: page * self.per_page]

    def repo_licence(self, repo):
        self.licence_calls.append(repo)
        return self.repos[repo][0]

    def fetch_file(self, hit):
        self.fetched.append(hit.repo)
        return self.repos[hit.repo][1]


def collector(db, client, storage=None):
    return CorpusCollector(db, client, storage=storage, limiter=HostRateLimiter(0.0), now=lambda: NOW)


def count(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def test_an_allowed_file_is_stored_with_url_licence_hash_and_date(db):
    content = b"# Skill\nDo the thing.\n"
    report = collector(db, FakeGitHub({"acme/skills": ("MIT", content)})).run()
    assert (report.found, report.stored, report.refused, report.failed) == (1, 1, 0, 0)
    source = db.execute("SELECT url, host, source_type, license, license_source FROM knowledge.sources").fetchone()
    assert source == ("https://github.com/acme/skills/blob/main/skills/a/SKILL.md", "github.com", "skill_md", "MIT", "repo")
    document = db.execute("SELECT content_hash, fetched_at, license, is_current FROM knowledge.documents").fetchone()
    assert document == (hashlib.sha256(content).hexdigest(), NOW, "MIT", True)


@pytest.mark.parametrize("licence", ["GPL-3.0-only", "AGPL-3.0-only", "CC-BY-SA-4.0", "MPL-2.0", "CC-BY-NC-4.0", "Proprietary", None])
def test_a_refused_or_unknown_licence_never_reaches_the_tables(db, licence):
    secret = b"SECRET-CONTENT-OF-A-REFUSED-FILE"
    client = FakeGitHub({"acme/closed": (licence, secret)})
    report = collector(db, client).run()
    assert (report.found, report.refused, report.stored) == (1, 1, 0)
    assert sum(report.refused_by_licence.values()) == 1
    assert client.fetched == [], "a refused file is not even downloaded"
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 0
    assert count(db, "SELECT count(*) FROM knowledge.documents") == 0
    assert count(db, "SELECT count(*) FROM knowledge.sources WHERE url LIKE %s", "%acme/closed%") == 0
    assert count(db, "SELECT count(*) FROM knowledge.documents WHERE content_hash = %s", hashlib.sha256(secret).hexdigest()) == 0


def test_a_mixed_run_stores_only_the_allowed_ones_and_counts_the_rest(db):
    client = FakeGitHub({
        "a/mit": ("MIT", b"one"), "b/apache": ("Apache-2.0", b"two"), "c/gpl": ("GPL-3.0-only", b"three"),
        "d/none": (None, b"four"), "e/sa": ("CC-BY-SA-4.0", b"five"),
    })
    report = collector(db, client).run()
    assert (report.found, report.stored, report.refused) == (5, 2, 3)
    assert sorted(client.fetched) == ["a/mit", "b/apache"]
    assert report.refused_by_licence == {"GPL-3.0-only": 1, "unknown": 1, "CC-BY-SA-4.0": 1}
    stored = {r[0] for r in db.execute("SELECT license FROM knowledge.sources")}
    assert stored == {"MIT", "Apache-2.0"}, "only allowed licences are in the table"
    assert count(db, "SELECT count(*) FROM knowledge.documents d JOIN knowledge.sources s ON s.id = d.source_id "
                     "WHERE s.license NOT IN ('MIT', 'Apache-2.0')") == 0


def test_running_again_changes_nothing_but_the_fetch_time(db):
    client = FakeGitHub({"a/mit": ("MIT", b"one"), "b/gpl": ("GPL-3.0-only", b"two")})
    collector(db, client).run()
    later = CorpusCollector(db, client, limiter=HostRateLimiter(0.0), now=lambda: datetime(2026, 11, 18, tzinfo=UTC))
    report = later.run()
    assert (report.stored, report.unchanged, report.updated, report.refused) == (0, 1, 0, 1)
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 1 and count(db, "SELECT count(*) FROM knowledge.documents") == 1
    assert count(db, "SELECT fetched_at FROM knowledge.documents") == datetime(2026, 11, 18, tzinfo=UTC)


def test_changed_content_is_a_new_version_and_the_old_one_stays_as_history(db):
    client = FakeGitHub({"a/mit": ("MIT", b"version one")})
    collector(db, client).run()
    client.repos["a/mit"] = ("MIT", b"version two")
    report = collector(db, client).run()
    assert (report.stored, report.updated) == (0, 1)
    assert count(db, "SELECT count(*) FROM knowledge.documents") == 2
    assert count(db, "SELECT count(*) FROM knowledge.documents WHERE is_current") == 1


def test_a_file_stored_earlier_is_withdrawn_when_its_repository_licence_becomes_refused(db):
    client = FakeGitHub({"a/lib": ("MIT", b"content")})
    collector(db, client).run()
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 1
    client.repos["a/lib"] = ("GPL-3.0-only", b"content")
    report = collector(db, client).run()
    assert (report.refused, report.withdrawn) == (1, 1)
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 0 and count(db, "SELECT count(*) FROM knowledge.documents") == 0


def test_the_licence_of_a_repository_is_asked_once_per_run(db):
    client = FakeGitHub({"a/mit": ("MIT", b"x")})
    other = SkillFileHit("a/mit", "other/SKILL.md", "https://github.com/a/mit/blob/main/other/SKILL.md")
    original = client.hits
    client.hits = lambda: [*original(), other]
    collector(db, client).run()
    assert client.licence_calls == ["a/mit"]
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 2


def test_the_content_goes_to_the_raw_bucket_only_for_allowed_files(db):
    storage = MemoryStorage()
    client = FakeGitHub({"a/mit": ("MIT", b"allowed text"), "b/gpl": ("GPL-3.0-only", b"refused text")})
    collector(db, client, storage).run()
    stored = [obj for obj in storage.list(BUCKET_RAW)]
    assert len(stored) == 1
    assert storage.get(BUCKET_RAW, stored[0].key) == b"allowed text"
    key = db.execute("SELECT raw_object_key FROM knowledge.documents").fetchone()[0]
    assert key == stored[0].key


def test_one_failing_file_does_not_stop_the_run(db):
    class Flaky(FakeGitHub):
        def fetch_file(self, hit):
            if hit.repo == "a/bad":
                raise TimeoutError("timed out")
            return super().fetch_file(hit)

    client = Flaky({"a/bad": ("MIT", b"x"), "b/good": ("MIT", b"y")})
    report = collector(db, client).run()
    assert (report.stored, report.failed) == (1, 1) and "a/bad" in report.errors[0]
    assert count(db, "SELECT count(*) FROM knowledge.sources") == 1


def test_a_file_over_the_size_limit_is_not_stored(db):
    client = FakeGitHub({"a/huge": ("MIT", b"x" * (1024 * 1024 + 1))})
    report = collector(db, client).run()
    assert (report.failed, report.stored) == (1, 0) and count(db, "SELECT count(*) FROM knowledge.sources") == 0


def test_search_pages_and_the_limit_are_respected(db):
    client = FakeGitHub({f"o/r{i}": ("MIT", f"c{i}".encode()) for i in range(5)}, per_page=2)
    report = collector(db, client).run(max_files=3)
    assert report.found == 3 and report.stored == 3


def test_every_github_call_waits_for_the_rate_limiter(db):
    waited: list[str] = []

    class Recording(HostRateLimiter):
        def wait(self, host, crawl_delay=None):
            waited.append(host)
            return 0.0

    client = FakeGitHub({"a/mit": ("MIT", b"x")})
    CorpusCollector(db, client, limiter=Recording(1.0), now=lambda: NOW).run()
    assert waited.count("github-api") >= 3 and "github-content" in waited       # search, licence, empty last page, then the file
