"""DE-04: robots.txt rules as RFC 9309 defines them (wildcards, end anchor, longest match), and a robots.txt that is too big.

`urllib.robotparser` (used before) ignores `*` and `$` inside paths and takes the first matching rule in file order, so a site
that asks us to stay away from `/*.pdf$` or writes `Allow: /` before `Disallow: /secret/` was crawled. No database, no network.
"""
import httpx
import pytest

from skillforge_data.crawler import FetchConfig, HttpFetcher
from skillforge_data.crawler.robots import RobotsPolicy, RobotsResponse


def policy(text: str, status: int = 200) -> RobotsPolicy:
    return RobotsPolicy(lambda origin: RobotsResponse(status, text))


def ok(text: str, path: str) -> bool:
    return policy(text).allowed(f"https://x.org{path}")[0]


# ------------------------------------------------------------------------------------------------ wildcards and $
def test_a_star_in_a_path_matches_any_text():
    rules = "User-agent: *\nDisallow: /*.pdf\n"
    assert ok(rules, "/a/file.pdf") is False
    assert ok(rules, "/file.pdf?download=1") is False, "no $: the rule matches the start of path and query"
    assert ok(rules, "/a/file.html") is True


def test_a_dollar_at_the_end_anchors_the_rule():
    rules = "User-agent: *\nDisallow: /*.pdf$\n"
    assert ok(rules, "/a/file.pdf") is False
    assert ok(rules, "/a/file.pdf?x=1") is True, "the path plus query does not end with .pdf"
    assert ok(rules, "/a/file.pdfx") is True


def test_a_star_in_the_middle_and_a_plain_prefix():
    rules = "User-agent: *\nDisallow: /private*/secret\nDisallow: /tmp\n"
    assert ok(rules, "/private-area/secret") is False
    assert ok(rules, "/private/secret/x") is False
    assert ok(rules, "/private/open") is True
    assert ok(rules, "/tmp/a") is False and ok(rules, "/tmpfile") is False, "a plain rule is a prefix"


# ------------------------------------------------------------------------------------------------ longest match wins
def test_allow_before_a_more_specific_disallow_does_not_win():
    rules = "User-agent: *\nAllow: /\nDisallow: /secret/\n"
    assert ok(rules, "/secret/x") is False
    assert ok(rules, "/public") is True


def test_the_longest_matching_rule_wins_whatever_the_order():
    allow_first = "User-agent: *\nAllow: /a/public/\nDisallow: /a/\n"
    disallow_first = "User-agent: *\nDisallow: /a/\nAllow: /a/public/\n"
    for rules in (allow_first, disallow_first):
        assert ok(rules, "/a/public/page") is True
        assert ok(rules, "/a/private/page") is False


def test_when_two_rules_are_equally_long_allow_wins():
    assert ok("User-agent: *\nDisallow: /x\nAllow: /x\n", "/x") is True


def test_an_empty_disallow_allows_everything_and_no_rule_allows():
    assert ok("User-agent: *\nDisallow:\n", "/anything") is True
    assert ok("User-agent: *\nDisallow: /a\n", "/b") is True


# ------------------------------------------------------------------------------------------------ groups
def test_our_token_group_wins_over_star_and_groups_of_the_same_agent_are_joined():
    text = ("User-agent: *\nDisallow: /\n\n"
            "User-agent: SkillForgeBot\nDisallow: /admin\n\n"
            "User-agent: skillforgebot\nDisallow: /drafts\nCrawl-delay: 3\n")
    p = policy(text)
    assert p.allowed("https://x.org/guide")[0] is True
    assert p.allowed("https://x.org/admin/x")[0] is False and p.allowed("https://x.org/drafts/x")[0] is False
    assert p.crawl_delay("https://x.org/guide") == 3.0


def test_several_user_agent_lines_share_the_rules_that_follow():
    text = "User-agent: OtherBot\nUser-agent: SkillForgeBot\nDisallow: /no\n"
    assert ok(text, "/no/x") is False


def test_without_a_matching_group_everything_is_allowed():
    assert ok("User-agent: OtherBot\nDisallow: /\n", "/x") is True


def test_comments_blank_lines_and_a_bom_are_ignored():
    text = "﻿# robots\nUser-agent: *  # everyone\n\nDisallow: /no # not here\n"
    assert ok(text, "/no/x") is False and ok(text, "/yes") is True


# ------------------------------------------------------------------------------------------------ the same answers as before
@pytest.mark.parametrize(
    ("status", "allowed"),
    [(200, True), (404, True), (410, True), (401, False), (403, False), (500, False), (None, False)],
)
def test_the_status_of_robots_txt_still_decides_as_before(status, allowed):
    p = RobotsPolicy(lambda origin: RobotsResponse(status, "User-agent: *\nDisallow: /nope\n" if status == 200 else ""))
    assert p.allowed("https://example.org/page")[0] is allowed


# ------------------------------------------------------------------------------------------------ too big
def _fetcher(body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=body, headers={"Content-Type": "text/plain"})
        return httpx.Response(200, text="<p>page</p>", headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return HttpFetcher(FetchConfig(min_interval=0.0), client=client, sleep=lambda s: None)


def test_a_robots_txt_over_512_kb_is_unavailable_and_disallows_the_whole_origin(caplog):
    body = b"User-agent: *\nDisallow: /\n" + b"# padding\n" * 60000          # about 600 KB, over the limit
    assert len(body) > 512 * 1024
    fetcher = _fetcher(body)
    with caplog.at_level("WARNING"):
        result = fetcher.fetch("https://example.org/page")
    assert result.outcome == "blocked" and result.robots_allowed is False
    assert any("larger than" in r.message and "example.org" in r.message for r in caplog.records), "the decision is logged"


def test_a_robots_txt_over_512_kb_that_allows_everything_is_still_unavailable():
    body = b"User-agent: *\nAllow: /\n" + b"# padding\n" * 60000
    result = _fetcher(body).fetch("https://example.org/page")
    assert result.outcome == "blocked", "too big means we do not know the rules, not that there are none"


def test_a_robots_txt_just_under_the_limit_is_read():
    body = b"User-agent: *\nDisallow: /nope\n"
    body += b"#" * (512 * 1024 - len(body))
    assert len(body) == 512 * 1024
    fetcher = _fetcher(body)
    assert fetcher.fetch("https://example.org/nope").outcome == "blocked"
    assert fetcher.fetch("https://example.org/page").outcome == "ok"


# ------------------------------------------------------------------------------------------------ one identity
def test_the_user_agent_header_and_the_robots_token_are_the_same_word():
    from skillforge_data.crawler.fetcher import USER_AGENT
    from skillforge_data.crawler.robots import PRODUCT_TOKEN

    assert PRODUCT_TOKEN == "SkillForgeBot"
    assert USER_AGENT.split("/", 1)[0] == PRODUCT_TOKEN


def test_the_header_the_crawler_really_sends_names_the_token_robots_txt_is_read_for(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["User-Agent"]))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: SkillForgeBot\nDisallow: /bot\n\nUser-agent: *\nDisallow: /all\n")
        return httpx.Response(200, text="<p>x</p>", headers={"Content-Type": "text/html"})

    real_client = httpx.Client                      # the default client (the one with the User-Agent header) over a mock network
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    fetcher = HttpFetcher(FetchConfig(min_interval=0.0), sleep=lambda s: None)
    assert fetcher.fetch("https://example.org/bot").outcome == "blocked", "our own group applies"
    assert fetcher.fetch("https://example.org/all").outcome == "ok", "the * group is ignored when ours exists"
    assert all(ua.startswith("SkillForgeBot/") for _, ua in seen)


def test_the_star_group_applies_when_there_is_no_group_for_our_token():
    assert ok("User-agent: *\nDisallow: /all\n", "/all/x") is False
    assert ok("User-agent: SkillForge\nDisallow: /\n", "/x") is True, "a different, shorter token is not ours"
