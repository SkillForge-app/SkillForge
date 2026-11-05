"""The canonical page URL (core.knowledge.urls): one rule for extraction and source discovery."""

from datetime import date

import pytest

from core.knowledge import ExtractionInputError, extract_page, normalise_url
from core.knowledge.search import normalise
from evaluation.retrieval.evaluate import hit_rank
from tests.knowledge.test_extract import article, html_page

DAY = date(2026, 11, 1)
PAGE = html_page(article(400))


@pytest.mark.parametrize(
    "spelling",
    [
        "https://example.org/guide/page",
        "https://example.org/guide/page/",  # trailing slash
        "https://example.org/guide/page//",
        "HTTPS://EXAMPLE.ORG/guide/page",  # scheme and host case
        "https://example.org/guide/page#section-2",  # fragment
        "https://example.org/guide/page?utm_source=news&utm_medium=email",
        "https://example.org/guide/page?UTM_Campaign=x&gclid=abc&FBCLID=def",
        "https://example.org:443/guide/page/",  # the default port
        "https://user:secret@example.org/guide/page",  # credentials are never kept
        "  https://example.org/guide/page  ",
    ],
)
def test_every_spelling_of_one_page_gives_one_url(spelling: str) -> None:
    assert normalise_url(spelling) == "https://example.org/guide/page"


def test_the_root_keeps_its_slash() -> None:
    for url in ("https://example.org", "https://example.org/", "https://example.org//"):
        assert normalise_url(url) == "https://example.org/"
    assert normalise_url("https://example.org/?utm_source=x") == "https://example.org/"


def test_other_query_parameters_are_kept_verbatim_and_in_order() -> None:
    url = "https://example.org/a?b=2&a=1&utm_term=x&q=hello%20world&flag&a=3"
    assert normalise_url(url) == "https://example.org/a?b=2&a=1&q=hello%20world&flag&a=3"
    assert normalise_url("https://example.org/a?ref=feed") == "https://example.org/a?ref=feed"


def test_the_path_keeps_its_case_and_a_port_is_kept() -> None:
    assert normalise_url("https://Example.org/Guide/") == "https://example.org/Guide"
    assert normalise_url("http://example.org:8080/a/") == "http://example.org:8080/a"


def test_it_is_idempotent() -> None:
    for url in ("https://WWW.Example.org/A/b/?x=1&utm_source=y#z", "http://[::1]:8080/a/"):
        once = normalise_url(url)
        assert normalise_url(once) == once


@pytest.mark.parametrize("bad", ["ftp://example.org/a", "mailto:a@example.org", "https://", "x"])
def test_only_http_urls(bad: str) -> None:
    with pytest.raises(ValueError):
        normalise_url(bad)


# ------------------------------------------------------------------ extraction (chunk_id)


def ids(url: str) -> tuple[str, list[str]]:
    page = extract_page(PAGE, url=url, retrieved=DAY)
    assert page.quality.ok and page.chunks
    return str(page.url), [c.chunk_id for c in page.chunks]


def test_tracking_fragment_case_and_slash_give_the_same_chunk_ids() -> None:
    expected = ids("https://example.org/guide/page")
    for spelling in (
        "https://example.org/guide/page/",
        "https://EXAMPLE.org/guide/page?utm_source=x&gclid=1",
        "https://example.org/guide/page#top",
        "https://example.org/guide/page/?fbclid=2#top",
    ):
        assert ids(spelling) == expected
    assert expected[0] == "https://example.org/guide/page"  # page.url is the canonical URL


def test_different_real_query_parameters_give_different_chunk_ids() -> None:
    one, two = ids("https://example.org/item?id=1"), ids("https://example.org/item?id=2")
    assert one[0] != two[0] and set(one[1]).isdisjoint(two[1])
    assert ids("https://example.org/item?id=1&utm_source=x") == one


def test_the_root_page_url_keeps_its_slash() -> None:
    assert ids("https://example.org")[0] == "https://example.org/"


def test_extraction_rejects_what_is_not_http() -> None:
    with pytest.raises(ExtractionInputError):
        extract_page(PAGE, url="ftp://example.org/a", retrieved=DAY)


# ------------------------------------------------------------------ one rule everywhere


def test_discovery_stores_the_same_canonical_url() -> None:
    url = "https://www.Example.org/Guide/?utm_source=x&id=2&ref=feed#top"
    clean, _, _ = normalise(url)
    assert clean == normalise_url(url) == "https://www.example.org/Guide?id=2&ref=feed"


def test_recall_matches_a_page_by_its_canonical_url() -> None:
    passages = extract_page(PAGE, url="https://example.org/guide/", retrieved=DAY).chunks
    found = [c.to_passage() for c in passages]
    evidence = "Clear rules help readers trust the advice they get."
    assert hit_rank(found, "https://example.org/guide/", evidence) == 1  # labelled with a slash
    assert hit_rank(found, "https://example.org/guide", evidence) == 1
