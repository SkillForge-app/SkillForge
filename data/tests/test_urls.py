"""DE-09: one host normalisation (skillforge_data/urls.py), the rules of AI's `normalise_url`, used by the crawler and the cache."""
from datetime import timedelta

import pytest
from fakes import T0

from skillforge_data.cache import DueSource, due_for_recrawl
from skillforge_data.crawler.fetcher import FetchConfig, HttpFetcher
from skillforge_data.crawler.robots import origin_of
from skillforge_data.freshness import FreshnessRules
from skillforge_data.urls import host_key, origin_key


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org/a", "example.org"),
        ("https://example.org:443/a", "example.org"),                 # default port of https
        ("http://example.org:80/a", "example.org"),                   # default port of http
        ("https://example.org:80/a", "example.org:80"),               # 80 is not the default of https
        ("http://example.org:443/a", "example.org:443"),
        ("https://example.org:8443/a", "example.org:8443"),           # another port is another server
        ("HTTPS://WWW.Example.ORG/A", "www.example.org"),
        ("https://user:secret@example.org/a", "example.org"),
        ("https://user@example.org:8080/a", "example.org:8080"),
        ("https://[::1]/a", "[::1]"),
        ("https://[::1]:443/a", "[::1]"),
        ("http://[2001:DB8::1]:8080/a", "[2001:db8::1]:8080"),
        ("https://example.org./a", "example.org."),                   # a trailing dot is kept, as AI's normalise_url keeps it
        ("  https://example.org/a  ", "example.org"),
    ],
)
def test_host_key(url, expected):
    assert host_key(url) == expected


@pytest.mark.parametrize("url", ["ftp://example.org/x", "example.org/x", "https:///x", "https://example.org:abc/x",
                                 "https://example.org:99999/x", "mailto:a@b.org", ""])
def test_things_that_are_not_http_urls_are_refused(url):
    with pytest.raises(ValueError, match="not an http"):
        host_key(url)


def test_the_same_server_has_one_key_however_it_is_written():
    spellings = ["https://example.org/x", "https://EXAMPLE.org:443/y", "https://u:p@Example.Org/z"]
    assert len({host_key(u) for u in spellings}) == 1 and len({origin_key(u) for u in spellings}) == 1


def test_origin_key_has_the_scheme_and_the_key_of_the_host():
    assert origin_key("HTTPS://User:pw@Example.org:443/a/b?c=d") == "https://example.org"
    assert origin_key("http://example.org:8080/") == "http://example.org:8080"
    assert origin_key("https://[::1]:9000/x") == "https://[::1]:9000"


def test_the_robots_cache_uses_the_same_origin():
    assert origin_of("https://Example.org:443/a") == origin_of("https://example.org/b") == "https://example.org"


def test_the_rate_limiter_gets_one_bucket_per_server():
    seen = []

    class Limiter:
        def wait(self, host, crawl_delay=None):
            seen.append(host)
            return 0.0

    fetcher = HttpFetcher(FetchConfig(min_interval=0.0))
    fetcher._limiter = Limiter()
    for url in ("https://127.0.0.1:1/a", "https://User:pw@127.0.0.1:1/b", "http://127.0.0.1:1/c"):
        fetcher.fetch(url)
    fetcher.close()
    assert set(seen) == {"127.0.0.1:1"}, "the first two spellings are one server; the http one (robots.txt of another origin) also keys by host and port"


# ---- the domain cache
def test_a_due_source_has_the_crawlers_key_and_keeps_the_stored_host():
    source = DueSource(source_id=None, url="https://Example.org:443/a", host="example.org", source_type="web_page", last_fetched_at=None)
    assert source.host == "example.org" and source.host_key == "example.org"
    other_port = DueSource(None, "https://example.org:8443/a", "example.org", "web_page", None)
    assert other_port.host == "example.org" and other_port.host_key == "example.org:8443", "the stored host has no port; the key does"


def test_a_source_that_is_not_http_falls_back_to_the_stored_host():
    repo_file = DueSource(None, "git@github.com:org/repo.git", "github.com", "repo_file", None)
    assert repo_file.host_key == "github.com"


def test_the_schedule_can_be_grouped_by_the_crawlers_key(db):
    for url, host in (("https://a.example.org/1", "a.example.org"), ("https://a.example.org:443/2", "a.example.org"),
                      ("https://A.example.org:8443/3", "a.example.org")):
        db.execute("INSERT INTO knowledge.sources (url, host, source_type) VALUES (%s, %s, 'web_page')", (url, host))
    due = due_for_recrawl(db, rules=FreshnessRules(), now=T0 + timedelta(days=1))
    assert sorted({s.host_key for s in due}) == ["a.example.org", "a.example.org:8443"]
    assert {s.host for s in due} == {"a.example.org"}
