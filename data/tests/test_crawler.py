"""DE-04: robots.txt, rate limit, redirects, size limit, retries, conditional GET, licence, crawl runs.

All requests go to a small HTTP server started inside the test on 127.0.0.1: no network.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fakes import FakeEmbed, FakeExtract, fake_normalise_url, page_bytes

from skillforge_data.crawler import (
    Crawler,
    FetchConfig,
    HttpFetcher,
    Validators,
    ValidatorStore,
)
from skillforge_data.crawler.license import detect_license, to_spdx
from skillforge_data.crawler.ratelimit import HostRateLimiter
from skillforge_data.crawler.robots import RobotsPolicy, RobotsResponse
from skillforge_data.pipeline.config import PipelineConfig
from skillforge_data.pipeline.process import process_document

LICENSED_PAGE = (
    b'<html><head><title>T</title><link rel="license" href="https://creativecommons.org/licenses/by/4.0/"></head>'
    b"<body><p>hello</p></body></html>"
)


class Site:
    """Routes and a log of every request the server received."""

    def __init__(self) -> None:
        self.hits: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.robots = "User-agent: *\nDisallow: /private\n"
        self.robots_status = 200
        self.counters: dict[str, int] = {}
        self.base = ""

    def count(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]


def _send(h, status, body=b"", headers=None, content_type="text/html"):
    h.send_response(status)
    h.send_header("Content-Type", content_type)
    h.send_header("Content-Length", str(len(body)))
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    h.end_headers()
    if body:
        h.wfile.write(body)


def _routes(site: Site):
    def robots(h):
        _send(h, site.robots_status, site.robots.encode(), content_type="text/plain")

    def ok(h):
        if h.headers.get("If-None-Match") == '"v1"':
            return _send(h, 304, headers={"ETag": '"v1"'})
        _send(h, 200, LICENSED_PAGE, {"ETag": '"v1"', "Last-Modified": "Wed, 04 Nov 2026 10:00:00 GMT"})

    def big_declared(h):
        _send(h, 200, b"x" * 3000)                      # Content-Length 3000

    def big_stream(h):                                  # no Content-Length: the body is read until it closes
        h.send_response(200)
        h.send_header("Content-Type", "text/html")
        h.send_header("Connection", "close")
        h.end_headers()
        h.wfile.write(b"y" * 3000)

    def flaky(h):
        if site.count("flaky") <= 2:
            return _send(h, 503)
        _send(h, 200, b"<p>finally</p>")

    def retry_after(h):
        if site.count("retry-after") == 1:
            return _send(h, 429, headers={"Retry-After": "7"})
        _send(h, 200, b"<p>after the wait</p>")

    def slow(h):
        time.sleep(1.0)
        _send(h, 200, b"<p>slow</p>")

    return {
        "/robots.txt": robots,
        "/ok": ok,
        "/private": lambda h: _send(h, 200, b"<p>secret</p>"),
        "/redirect": lambda h: _send(h, 302, headers={"Location": "/ok"}),
        "/redirect-private": lambda h: _send(h, 302, headers={"Location": "/private"}),
        "/loop": lambda h: _send(h, 302, headers={"Location": "/loop"}),
        "/big-declared": big_declared,
        "/big-stream": big_stream,
        "/flaky": flaky,
        "/always503": lambda h: _send(h, 503),
        "/retry-after": retry_after,
        "/gone": lambda h: _send(h, 404),
        "/slow": slow,
        "/trailing/": lambda h: _send(h, 200, b"<p>with a slash</p>"),
        "/doc-a": lambda h: _send(h, 200, page_bytes(("alpha one", "alpha two"), title="Doc A")),
        "/doc-b": lambda h: _send(h, 200, page_bytes(("bravo one",), title="Doc B")),
    }


@pytest.fixture
def site():
    site = Site()
    routes = _routes(site)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            site.hits.append(self.path)
            site.headers.append(dict(self.headers))
            route = routes.get(self.path.split("?")[0])
            if route is None:
                return _send(self, 404)
            route(self)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    site.base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield site
    server.shutdown()
    server.server_close()


class Sleeps:
    """Replaces time.sleep: records the pauses instead of waiting."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.values.append(seconds)


def make_fetcher(**overrides):
    sleeps = Sleeps()
    config = FetchConfig(**{"min_interval": 0.0, "timeout": 5.0, **overrides})
    return HttpFetcher(config, sleep=sleeps), sleeps


# --------------------------------------------------------------------------------------------- robots.txt
def test_a_url_disallowed_by_robots_txt_is_never_requested(site):
    fetcher, _ = make_fetcher()
    result = fetcher.fetch(f"{site.base}/private")
    assert result.outcome == "blocked" and result.robots_allowed is False
    assert "/private" not in site.hits, "the page itself must never be requested"
    assert site.hits == ["/robots.txt"]


def test_a_redirect_to_a_disallowed_url_is_stopped_before_the_request(site):
    fetcher, _ = make_fetcher()
    result = fetcher.fetch(f"{site.base}/redirect-private")
    assert result.outcome == "blocked"
    assert "/private" not in site.hits and "/redirect-private" in site.hits


def test_robots_txt_is_fetched_once_and_cached(site):
    fetcher, _ = make_fetcher()
    fetcher.fetch(f"{site.base}/ok")
    fetcher.fetch(f"{site.base}/gone")
    assert site.hits.count("/robots.txt") == 1


def test_the_request_names_the_bot(site):
    fetcher, _ = make_fetcher()
    fetcher.fetch(f"{site.base}/ok")
    agents = {h.get("User-Agent") for h in site.headers}
    assert len(agents) == 1 and next(iter(agents)).startswith("SkillForgeBot/")


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(200, True), (404, True), (410, True), (401, False), (403, False), (500, False), (None, False)],
)
def test_how_the_robots_txt_answer_is_read(status, allowed):
    policy = RobotsPolicy(lambda origin: RobotsResponse(status, "User-agent: *\nDisallow: /nope\n" if status == 200 else ""))
    assert policy.allowed("https://example.org/page")[0] is allowed


def test_robots_rules_for_our_token_win_over_the_star_group_and_crawl_delay_is_read():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: SkillForgeBot\nDisallow: /admin\nCrawl-delay: 3\n"
    policy = RobotsPolicy(lambda origin: RobotsResponse(200, text))
    assert policy.allowed("https://example.org/guide")[0] is True
    assert policy.allowed("https://example.org/admin/x")[0] is False
    assert policy.crawl_delay("https://example.org/guide") == 3.0


def test_the_deny_list_blocks_a_host_without_any_request(site):
    fetcher, _ = make_fetcher(denylist=frozenset({"127.0.0.1"}))
    result = fetcher.fetch(f"{site.base}/ok")
    assert result.outcome == "blocked" and site.hits == []


# ------------------------------------------------------------------------------------------- rate limit
def test_requests_to_one_host_are_spaced():
    now = [0.0]
    sleeps = Sleeps()
    limiter = HostRateLimiter(2.0, clock=lambda: now[0], sleep=lambda s: (sleeps(s), now.__setitem__(0, now[0] + s)))
    assert limiter.wait("a.example") == 0.0
    now[0] += 0.5
    assert limiter.wait("a.example") == pytest.approx(1.5)
    assert limiter.wait("b.example") == 0.0, "another host is not delayed"
    assert limiter.wait("a.example", crawl_delay=5.0) == pytest.approx(5.0), "a Crawl-delay raises the interval"
    assert sleeps.values == [pytest.approx(1.5), pytest.approx(5.0)]


def test_the_fetcher_waits_between_requests_to_the_same_host(site):
    fetcher, sleeps = make_fetcher(min_interval=2.0)
    fetcher.fetch(f"{site.base}/ok")
    fetcher.fetch(f"{site.base}/gone")
    assert any(s > 1.0 for s in sleeps.values), "the second page request had to wait"


# ------------------------------------------------------------------------------------ redirects, size
def test_a_redirect_is_followed_and_the_final_url_is_reported(site):
    fetcher, _ = make_fetcher()
    result = fetcher.fetch(f"{site.base}/redirect")
    assert result.outcome == "ok" and result.final_url.endswith("/ok") and len(result.redirects) == 1


def test_too_many_redirects_fail(site):
    fetcher, _ = make_fetcher(max_redirects=3)
    result = fetcher.fetch(f"{site.base}/loop")
    assert result.outcome == "failed" and "redirects" in result.error


@pytest.mark.parametrize("path", ["/big-declared", "/big-stream"])
def test_a_body_over_the_size_limit_is_refused(site, path):
    fetcher, _ = make_fetcher(max_bytes=1000)
    result = fetcher.fetch(f"{site.base}{path}")
    assert result.outcome == "too_large" and result.content == b""


def test_a_body_exactly_at_the_limit_is_accepted(site):
    fetcher, _ = make_fetcher(max_bytes=3000)
    assert fetcher.fetch(f"{site.base}/big-declared").outcome == "ok"


# ----------------------------------------------------------------------------------------------- retries
def test_a_503_is_retried_with_backoff_until_it_works(site):
    fetcher, sleeps = make_fetcher(retries=3, backoff_base=1.0)
    result = fetcher.fetch(f"{site.base}/flaky")
    assert result.outcome == "ok" and result.content == b"<p>finally</p>"
    assert sleeps.values == [1.0, 2.0]


def test_retries_end_and_the_failure_is_reported(site):
    fetcher, _ = make_fetcher(retries=2)
    result = fetcher.fetch(f"{site.base}/always503")
    assert result.outcome == "failed" and result.http_status == 503
    assert site.hits.count("/always503") == 3, "the first try and two retries"


def test_a_404_is_not_retried(site):
    fetcher, sleeps = make_fetcher(retries=3)
    result = fetcher.fetch(f"{site.base}/gone")
    assert result.outcome == "failed" and result.http_status == 404
    assert site.hits.count("/gone") == 1 and sleeps.values == []


def test_retry_after_is_honoured_but_capped(site):
    fetcher, sleeps = make_fetcher(retries=2)
    assert fetcher.fetch(f"{site.base}/retry-after").outcome == "ok"
    assert sleeps.values == [7.0]
    site.counters.clear()
    capped, sleeps2 = make_fetcher(retries=2, max_wait=3.0)
    capped.fetch(f"{site.base}/retry-after")
    assert sleeps2.values == [3.0]


def test_a_timeout_is_a_failure_after_the_retries(site):
    fetcher, _ = make_fetcher(timeout=0.2, retries=1)
    result = fetcher.fetch(f"{site.base}/slow")
    assert result.outcome == "failed" and "Timeout" in result.error
    assert site.hits.count("/slow") == 2


# ----------------------------------------------------------------------------------------- conditional GET
def test_etag_gives_a_304_the_second_time(site):
    fetcher, _ = make_fetcher()
    first = fetcher.fetch(f"{site.base}/ok")
    assert first.outcome == "ok" and first.validators.etag == '"v1"' and first.validators.last_modified
    second = fetcher.fetch(f"{site.base}/ok", first.validators)
    assert second.outcome == "not_modified" and second.content == b""
    assert site.headers[-1]["If-None-Match"] == '"v1"'
    assert site.headers[-1]["If-Modified-Since"] == "Wed, 04 Nov 2026 10:00:00 GMT"


# -------------------------------------------------------------------------------------------- licence
@pytest.mark.parametrize(
    ("value", "spdx"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("https://creativecommons.org/licenses/by-nc-sa/3.0/", "CC-BY-NC-SA-3.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("https://opensource.org/licenses/MIT", "MIT"),
        ("https://www.apache.org/licenses/LICENSE-2.0", "Apache-2.0"),
        ("https://spdx.org/licenses/BSD-3-Clause.html", "BSD-3-Clause"),
        ("All rights reserved", "unknown"),
        ("https://example.org/our-own-terms", "unknown"),
    ],
)
def test_licence_urls_map_to_spdx_ids(value, spdx):
    assert to_spdx(value) == spdx


def test_a_licence_declared_in_the_page_is_found():
    assert detect_license(LICENSED_PAGE).spdx == "CC-BY-4.0"
    meta = b'<head><meta name="license" content="https://opensource.org/licenses/MIT"></head>'
    assert detect_license(meta).spdx == "MIT"
    jsonld = b'<script type="application/ld+json">{"@type": "Article", "license": "https://creativecommons.org/licenses/by-sa/4.0/"}</script>'
    assert detect_license(jsonld).spdx == "CC-BY-SA-4.0"


def test_nothing_is_guessed_when_the_page_declares_no_licence():
    info = detect_license(b"<html><body><footer>(c) 2026 Example. MIT licensed.</footer></body></html>")
    assert info.spdx == "unknown" and info.source == "unknown"


# --------------------------------------------------------------------------------------------- crawl runs
@pytest.fixture
def crawl(db, site):
    fetcher, _sleeps = make_fetcher()
    config = fetcher.config

    def make(validators=None):
        return Crawler(db, fetcher, fake_normalise_url, config=config, pipeline_version="p1", validators=validators)

    return make, site


def test_a_crawl_run_is_recorded_with_its_counters(db, crawl):
    make, site = crawl
    pages = []
    summary = make().run(
        [f"{site.base}/ok", f"{site.base}/private", f"{site.base}/gone"], domains=["technology/ai"], on_page=pages.append,
    )
    assert (summary.fetched, summary.blocked, summary.failed, summary.unchanged) == (1, 1, 1, 0)
    assert summary.status == "partial"
    row = db.execute(
        "SELECT status, user_agent, pages_fetched, pages_unchanged, pages_blocked, pages_failed, error, "
        "finished_at IS NOT NULL, config->>'max_bytes' FROM knowledge.crawl_runs WHERE id = %s", (summary.run_id,),
    ).fetchone()
    assert row[0] == "partial" and row[1].startswith("SkillForgeBot/") and row[2:6] == (1, 0, 1, 1)
    assert "404" in row[6] and row[7] and row[8] == str(20 * 1024 * 1024)
    assert len(pages) == 1 and pages[0].crawl_run_id == summary.run_id


def test_the_source_gets_its_robots_flag_and_licence(db, crawl):
    make, site = crawl
    make().run([f"{site.base}/ok", f"{site.base}/private"], domains=["technology/ai"])
    ok = db.execute("SELECT robots_allowed, robots_checked_at IS NOT NULL, license, license_source FROM knowledge.sources "
                    "WHERE url LIKE '%/ok'").fetchone()
    assert ok == (True, True, "CC-BY-4.0", "page")
    blocked = db.execute("SELECT robots_allowed, license FROM knowledge.sources WHERE url LIKE '%/private'").fetchone()
    assert blocked == (False, "unknown")


def test_the_original_url_is_fetched_and_the_canonical_one_is_stored(db, crawl):
    make, site = crawl
    make().run([f"{site.base}/trailing/"], domains=["technology/ai"])
    assert "/trailing/" in site.hits, "fetched with the slash, as the site serves it"
    assert db.execute("SELECT url FROM knowledge.sources").fetchone()[0] == f"{site.base}/trailing"


def test_a_second_crawl_with_the_same_etag_counts_as_unchanged(db, crawl):
    make, site = crawl
    validators = ValidatorStore()
    first = make(validators).run([f"{site.base}/ok"], domains=["technology/ai"])
    second = make(validators).run([f"{site.base}/ok"], domains=["technology/ai"])
    assert first.fetched == 1 and second.fetched == 0 and second.unchanged == 1 and second.status == "succeeded"
    assert validators.get(f"{site.base}/ok") == Validators('"v1"', "Wed, 04 Nov 2026 10:00:00 GMT")


def test_a_run_where_everything_fails_has_status_failed(db, crawl):
    make, site = crawl
    summary = make().run([f"{site.base}/gone", "ftp://example.org/x"], domains=["technology/ai"])
    assert summary.status == "failed" and summary.failed == 2
    assert db.execute("SELECT status, pages_failed FROM knowledge.crawl_runs").fetchone() == ("failed", 2)


def test_a_crawl_feeds_the_pipeline_and_a_second_crawl_changes_nothing(db, crawl):
    make, site = crawl
    extract, embed = FakeExtract(), FakeEmbed()
    config = PipelineConfig(pipeline_version="p1", embedding_version="rev-1")

    def handler(page):
        return process_document(db, page, config=config, extract=extract, embed=embed, normalise_url=fake_normalise_url)

    urls = [f"{site.base}/doc-a", f"{site.base}/doc-b"]
    first = make().run(urls, domains=["technology/ai"], on_page=handler)
    assert first.fetched == 2 and first.failed == 0
    assert db.execute("SELECT count(*), count(DISTINCT crawl_run_id) FROM knowledge.documents").fetchone() == (2, 1)
    assert db.execute("SELECT count(*) FROM knowledge.chunks").fetchone()[0] == 3

    second = make().run(urls, domains=["technology/ai"], on_page=handler)
    assert second.fetched == 2 and second.unchanged == 2, "same content: the pipeline reports 'unchanged'"
    assert db.execute("SELECT count(*) FROM knowledge.documents").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM knowledge.chunks").fetchone()[0] == 3
    assert embed.calls == 2, "nothing was embedded twice"
    assert db.execute("SELECT pages_unchanged FROM knowledge.crawl_runs WHERE id = %s", (second.run_id,)).fetchone()[0] == 2
