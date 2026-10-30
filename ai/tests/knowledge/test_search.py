"""Source discovery (AI-09): queries, ranking, blocklist, licence and robots. No network."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from core.knowledge import RetrievalInputError
from core.knowledge.search import (
    AUTHORITY_BONUS,
    BRAVE_KEY_ENV,
    HIGH_RISK_REASON,
    MAX_QUERIES,
    NO_TOPIC_REASON,
    PER_SITE,
    SEARCH_ENV,
    UNKNOWN_REASON,
    UNTITLED_REASON,
    BraveSearchProvider,
    DomainHints,
    FakeSearchProvider,
    FixtureRobots,
    HttpRobots,
    Registry,
    SearchResult,
    SourceList,
    build_queries,
    discover_sources,
    document_key,
    in_jurisdiction,
    jurisdiction_of,
    load_registry,
    normalise,
    parse_brave,
    provider_from_env,
    site_of,
    title_key,
    topic_phrases,
)
from core.llm import ConfigError
from evaluation.sources.__main__ import main
from evaluation.sources.review import (
    automatic_checks,
    build_review,
    review_history,
    seed_domains,
    write_review,
)


@dataclass(frozen=True)
class Request:
    skill_name: str | None
    summary: str
    expected_outputs: tuple[str, ...] = ()


class Scripted:
    """A provider that returns the same results for every query."""

    def __init__(self, results: list[tuple[str, str]]) -> None:
        self.results = [SearchResult(url, title, i) for i, (url, title) in enumerate(results, 1)]

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        return self.results[:count]


class AllowAll:
    def status(self, url: str) -> str:
        return "allowed"


def without_pins(registry: Registry | None = None) -> Registry:
    """The registry with no pinned sources, so a test sees only its scripted results."""
    data = (registry or load_registry()).model_dump(mode="json")
    for hints in data["domains"].values():
        hints["pinned"] = []
    return Registry.model_validate_json(json.dumps(data))


async def run(
    results: list[tuple[str, str]], domain: str = "legal/contracts", **kw: Any
) -> SourceList:
    kw.setdefault("registry", without_pins())
    return await discover_sources(domain, provider=Scripted(results), robots=AllowAll(), **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ queries


def test_queries_are_deterministic_short_and_unique() -> None:
    queries = build_queries("hr/recruiting")
    assert queries == build_queries("hr/recruiting")
    assert len(queries) <= MAX_QUERIES and len(set(queries)) == len(queries)
    assert "recruiting guidelines site:.gov" in queries


def test_a_request_adds_its_skill_and_output_first() -> None:
    queries = build_queries(
        "legal/contracts", Request("review-nda", "x", ("NDA review checklist",))
    )
    assert queries[:2] == ["review NDA contracts guide", "NDA review checklist template"]
    assert len(queries) == 2 + len(load_registry().domains["legal/contracts"].queries)
    without_name = build_queries("hr/recruiting", Request(None, "hire a backend engineer fast"))
    assert without_name[0] == "hire a backend engineer fast recruiting guide"


def test_domain_hints_add_their_queries_after_the_request_ones() -> None:
    hints = load_registry().domains["legal/contracts"].queries
    queries = build_queries(
        "legal/contracts", Request("review-nda", "x", ("NDA review checklist",))
    )
    assert queries[2 : 2 + len(hints)] == hints
    assert build_queries("legal/contracts")[: len(hints)] == hints
    hr = build_queries("hr/recruiting", Request("hr-recruiter", "x", ("job ad",)))
    assert MAX_QUERIES == 8 and len(hr) == MAX_QUERIES  # hints and templates are cut at 8
    assert not load_registry().domains["technology/software-engineering"].queries  # terms only
    first = build_queries("technology/software-engineering")[0]
    assert first == "software engineering official documentation"  # a template


def test_a_domain_can_skip_the_generic_templates() -> None:
    registry = load_registry()
    assert registry.domains["legal/contracts"].templates is False
    templated = {t.format(topic="contracts", hint="law") for t in registry.templates}
    assert not templated & set(build_queries("legal/contracts"))
    assert "contracts guidelines site:.gov" in templated


@pytest.mark.parametrize("domain", ["", "astrology", "Legal/Contracts", "legal/"])
def test_bad_domains_are_rejected(domain: str) -> None:
    with pytest.raises(RetrievalInputError):
        build_queries(domain)


# ------------------------------------------------------------------ normalising


def test_copies_of_one_page_get_one_key() -> None:
    _, a, host = normalise("https://www.Example.org/Guide/?utm_source=x&id=2#top")
    _, b, _ = normalise("https://example.org/guide?id=2&ref=feed")
    _, c, _ = normalise("https://www2.example.org/fr-fr/guide/amp")
    _, d, _ = normalise("https://example.org/guide.md?id=2")
    assert a == b == d and host == "example.org"
    assert c.startswith("example.org/guide?")
    clean, _, _ = normalise("https://Example.org/a?utm_medium=y&b=1#frag")
    assert clean == "https://example.org/a?b=1"
    _, e, _ = normalise("https://www.eeoc.gov/index%2Ephp/newsroom/x")
    _, f, _ = normalise("https://www.eeoc.gov/index.php/newsroom/x")
    assert e == f == normalise("https://www.eeoc.gov/newsroom/x")[1]


def test_one_document_on_two_sites_has_one_key() -> None:
    a = document_key("https://sceweb.uhcl.edu/helm/SWEBOK_IEEE/SWEBOK_Guide_2004.pdf")
    b = document_key("https://www.inf.ed.ac.uk/teaching/2004_2005/resources/SWEBOK_2004.pdf")
    assert a == b == "2004 swebok"
    assert document_key("https://x.example/Report_2023_final_1.PDF") == "2023 report"
    assert document_key("https://x.example/SWEBOK_2014.pdf") != a
    assert document_key("https://x.example/swebok") is None  # a web page
    assert document_key("https://x.example/report.pdf") is None  # too generic to match


def test_title_key_ignores_titles_that_are_only_the_host() -> None:
    assert title_key("Marketing & Sales", "franklincountyohio.gov") == "marketing sale"
    assert title_key("www.ftc.gov", "ftc.gov") is None
    assert title_key("help.sos.iowa.gov", "help.sos.iowa.gov") is None
    assert title_key("Hiring | U.S. Department of Labor", "dol.gov") == title_key(
        "Hiring", "dol.gov"
    )
    assert title_key("Data - Analytics", "x.gov") == "analytic data"  # a hyphen is kept


def test_a_library_guide_is_blocked_by_its_title() -> None:
    url = "https://library.example.org/ai"
    title = "Home - Artificial Intelligence - LibGuides at Example University"
    assert "library guide" in (_block_reason(url, title) or "")


@pytest.mark.parametrize(
    ("host", "site"),
    [
        ("www2.ed.gov", "ed.gov"),
        ("oudev.stockton.edu", "stockton.edu"),
        ("docs.service.gov.uk", "service.gov.uk"),
    ],
)
def test_site_of(host: str, site: str) -> None:
    assert site_of(host) == site


# ------------------------------------------------------------------ ranking


async def test_authorities_rank_and_an_unknown_site_needs_a_pin() -> None:
    found = await run(
        [
            ("https://contracts-blog.example.com/contracts-guide", "Contracts guide"),
            ("https://www.sba.gov/contracts", "Contracts guide"),
            ("https://law.cornell.edu/wex/contract", "Contract"),
        ]
    )
    assert [s.host for s in found.sources] == [
        "law.cornell.edu",  # academic, but a named authority for legal/contracts
        "sba.gov",
    ]
    sba = found.sources[1]
    assert sba.tier == "official" and sba.licence == "public-domain-us-gov"
    assert "an authority for legal" in sba.reasons
    blog = "https://contracts-blog.example.com/contracts-guide"
    assert [(r.url, r.reason) for r in found.rejected] == [(blog, UNKNOWN_REASON)]


async def test_a_source_for_other_areas_only_needs_a_pin_or_a_naming() -> None:
    results = [
        ("https://www.eeoc.gov/contracts", "Contracts"),
        ("https://www.ftc.gov/contracts", "Contracts"),
    ]
    legal = await run(results, "legal/contracts")
    marketing = await run(results, "marketing/contracts")
    assert {s.host for s in legal.sources} == {"eeoc.gov", "ftc.gov"}
    assert [s.host for s in marketing.sources] == ["ftc.gov"]
    assert marketing.rejected[0].reason == "an authority for hr, legal only, not marketing"
    # A domain's named authority stays even when the registry names it for other areas.
    ir = await run(
        [("https://www.atlassian.com/incident-management/postmortems", "Postmortems")],
        "technology/incident-response",
    )
    assert [s.host for s in ir.sources] == ["atlassian.com"]
    ai = await run([("https://learning.atlassian.com/ai-best-practices", "AI")], "technology/ai")
    assert ai.sources == [] and "only, not technology" in ai.rejected[0].reason


async def test_blocked_and_weak_unknown_sources_are_rejected_with_a_reason() -> None:
    found = await run(
        [
            ("https://www.scribd.com/document/1/contracts", "Contracts"),
            ("https://mail.example.org/contracts-law.html", "Contracts law"),
            ("https://example.org/Download_PDFS/x/contracts.pdf", "Contracts"),
            ("https://example.org/tag/contracts/", "Contracts"),
            ("https://unrelated.example.com/recipes", "Cake recipes"),
        ]
    )
    assert found.sources == []
    reasons = {r.url.split("/")[2]: r.reason for r in found.rejected}
    assert "user-uploaded documents" in reasons["www.scribd.com"]
    assert "infrastructure subdomain" in reasons["mail.example.org"]
    assert reasons["unrelated.example.com"] == UNKNOWN_REASON
    assert reasons["example.org"] in {
        "blocked: SEO spam (fake PDF download pages)",
        "blocked: tag or category listing page",
    }
    assert len(found.rejected) == 5


async def test_duplicates_fold_and_the_site_cap_holds() -> None:
    found = await run(
        [
            ("https://www.sba.gov/contracts-a", "Contracts A"),
            ("https://www.sba.gov/contracts-a?utm_source=x", "Contracts A again"),
            ("https://www.sba.gov/contracts-b", "Contracts B"),
            ("https://www2.sba.gov/contracts-c", "Contracts C"),
        ]
    )
    assert len(found.sources) == PER_SITE
    reasons = [r.reason for r in found.rejected]
    assert any("already 2 pages from this site" in r for r in reasons)
    assert len({s.url for s in found.sources}) == PER_SITE


async def test_robots_disallowed_sources_are_dropped_and_unknown_is_labelled(
    tmp_path: Path,
) -> None:
    (tmp_path / "www.sba.gov.txt").write_text(
        "User-agent: *\nDisallow: /private/\n", encoding="utf-8"
    )
    found = await discover_sources(
        "legal/contracts",
        provider=Scripted(
            [
                ("https://www.sba.gov/private/contracts", "Contracts"),
                ("https://www.sba.gov/contracts", "Contracts"),
                ("https://www.dol.gov/contracts", "Contracts"),
            ]
        ),
        robots=FixtureRobots(tmp_path),
        registry=without_pins(),
    )
    assert {s.url: s.robots for s in found.sources} == {
        "https://www.sba.gov/contracts": "allowed",
        "https://www.dol.gov/contracts": "unknown",
    }
    assert any("robots.txt disallows" in r.reason for r in found.rejected)
    assert all(s.crawl for s in found.sources)
    assert [u for u, _ in found.crawl_list()] == [s.url for s in found.sources]


@pytest.mark.parametrize(
    "domain", ["legal/contracts", "medical/patient-education", "finance/small-business"]
)
async def test_high_risk_areas_crawl_only_official_and_academic_sources(domain: str) -> None:
    topic = topic_phrases(domain)[0][0]
    found = await run(
        [
            ("https://www.example.gov/guide", topic),
            ("https://example.edu/guide", topic),
            ("https://en.wikipedia.org/wiki/guide", topic),
        ],
        domain,
    )
    assert [(s.tier, s.crawl) for s in found.sources] == [("official", True), ("academic", True)]
    assert [(s.tier, s.crawl) for s in found.listed] == [("reference", False)]
    assert HIGH_RISK_REASON in found.listed[0].reasons
    assert not any(HIGH_RISK_REASON in s.reasons for s in found.sources)
    assert {u for u, _ in found.crawl_list()} == {
        "https://www.example.gov/guide",
        "https://example.edu/guide",
    }


async def test_other_areas_still_crawl_reference_sources() -> None:
    found = await run(
        [("https://en.wikipedia.org/wiki/strategy", "Marketing strategy")], "marketing/strategy"
    )
    assert [(s.tier, s.crawl) for s in found.sources] == [("reference", True)]
    assert found.listed == [] and HIGH_RISK_REASON not in found.sources[0].reasons


async def test_legal_sources_name_their_jurisdiction() -> None:
    results = [
        ("https://www.sba.gov/contracts", "Contracts"),
        ("https://www.nysenate.gov/contracts", "Contracts"),
        ("https://www.legislation.gov.uk/contracts", "Contracts"),
        ("https://eur-lex.europa.eu/contracts", "Contracts"),
        ("https://www.nolo.com/contracts", "Contracts"),
        ("https://www.cbca.gov/contracts", "Contracts"),
        ("https://www.contracts.example.ca/contracts", "Contracts"),
    ]
    found = await run(results)
    places = {
        s.host: next(r for r in s.reasons if r.startswith("jurisdiction: "))
        for s in [*found.sources, *found.listed]  # Nolo is listed: crawl: no (high risk)
    }
    below = " (not US: ranked below US sources)"  # legal/contracts wants US law
    assert places == {
        "sba.gov": "jurisdiction: US (federal)",  # a federal public-domain source
        "cbca.gov": "jurisdiction: US (federal)",  # a federal host listed in the registry
        "nysenate.gov": "jurisdiction: US (state or local)",  # an unlisted .gov
        "legislation.gov.uk": f"jurisdiction: UK{below}",
        "eur-lex.europa.eu": f"jurisdiction: EU{below}",
        "nolo.com": "jurisdiction: US",  # set in the registry
    }
    assert found.rejected[0].reason == UNKNOWN_REASON  # the .ca site: unknown, so not listed
    marketing = await run(results, "marketing/contracts")
    assert not any(r.startswith("jurisdiction") for s in marketing.sources for r in s.reasons)


@pytest.mark.parametrize(
    ("host", "place"),
    [("x.mil", "US (federal)"), ("x.edu", "US"), ("x.gc.ca", "Canada"), ("x.example", "unknown")],
)
def test_jurisdiction_from_the_host_suffix(host: str, place: str) -> None:
    assert jurisdiction_of(host, None) == place


async def test_domain_hint_terms_count_as_on_topic() -> None:
    page = [("https://www.example.gov/mutual", "Mutual non-disclosure agreement template")]
    legal = await run(page, "legal/contracts")
    assert [s.host for s in legal.sources] == ["example.gov"]
    assert 'matched 3 of 3 words of "non-disclosure agreement"' in legal.sources[0].reasons
    hr = await run(page, "hr/recruiting")
    assert hr.sources == [] and hr.rejected[0].reason == NO_TOPIC_REASON


def _block_reason(url: str, title: str = "") -> str | None:
    host = normalise(url)[2]
    blocked = load_registry().blocked
    return next((b.reason for b in blocked if b.matches(url, host, title)), None)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://libcat.mcphs.edu/Record/in00000150077/Description", "catalogue record"),
        ("https://oalib-perpustakaan.upi.edu/Record/doaj_26cb/Description", "catalogue record"),
        ("https://catalog.pelhamlibrary.org/Record/3271940", "catalogue record"),
        ("https://profiles.nlm.nih.gov/101584666X450", "catalogue record"),
        ("https://www.guilfordcountync.gov/news/events/budget-and-cashflow", "event"),
        ("https://gov.texas.gov/es/business/event/small-business-cash-flow", "event"),
        ("https://www.example.gov/news/small-business-webinar-series", "event"),
        ("https://imagine.jhu.edu/classes/how-to-write-a-press-release/", "event"),
        ("https://ce.mayo.edu/node/180293", "continuing-education"),
        ("https://online.nwmissouri.edu/programs/undergraduate/pr", "program marketing"),
        ("https://www.uni.edu/academics/degrees/communication", "program marketing"),
        ("https://ccrsstg-acquia.nysed.gov/lawshelf/basics-contract-law", "staging or test"),
        ("https://stagingmolly.molevalley.gov.uk/job-description.pdf", "staging or test"),
        ("https://app-dev.example.gov/guide", "staging or test"),
        ("https://test2.example.edu/guide", "staging or test"),
        ("https://irishplaces.flinders.edu.au/10-contract-law-essentials", "SEO spam"),
        ("https://www.ftc.gov/news-events/news/press-releases?page=36", "paginated listing"),
        ("https://vendordirectory.shrm.org/company/1/products/2/interview-guides", "vendor"),
        ("https://www.dol.gov/general/jobs/how-to-apply", "job or careers"),
        ("https://www.example.gov/careers", "job or careers"),
        ("https://www.sheffield.gov.uk/job-vacancies/fairness", "job or careers"),
        ("https://disclosures.pembrokeshire.gov.uk/details/1711433?culture=cy", "disclosure log"),
        ("https://www.example.gov.uk/foi/request-123", "disclosure log"),
        ("https://www.example.gov/freedom-of-information/requests", "disclosure log"),
        ("https://gov.wales/atisn18678", "disclosure log"),
        (
            "https://www.americanbar.org/groups/public_education/resources/"
            "law_issues_for_consumers/books_consumer_home/",
            "only lists links",
        ),
        ("https://www.sba.gov/", "only lists links"),
        ("https://www.example.gov/sitemap.xml", "only lists links"),
        ("https://libguides.utoledo.edu/c.php?g=975620", "library guide"),
        ("https://guides.library.harvard.edu/contracts?hs=a", "library guide"),
        ("https://library.osuit.edu/AI", "library guide"),
        ("https://hslguides.med.nyu.edu/healthlit", "library guide"),
        ("https://liblicense.crl.edu/ListArchives/1103/msg00100.html", "mailing-list archive"),
        ("https://bookstore.sautech.edu/ebook/1554313562", "shop listing"),
    ],
)
def test_non_content_pages_are_blocked(url: str, reason: str) -> None:
    assert reason in (_block_reason(url) or ""), url


def test_transparency_data_is_blocked_by_its_title() -> None:
    url = "https://www.gov.uk/government/publications/non-disclosure-agreements--2"
    assert "transparency data" in (_block_reason(url, "Transparency data") or "")
    assert _block_reason(url, "Non-disclosure agreements") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.devon.gov.uk/guide",  # "dev" inside a word
        "https://developers.google.com/search/docs",
        "https://devblogs.microsoft.com/python/post",  # "dev" starts a word
        "https://www.stgeorges.nhs.uk/patient-education",  # "stg" inside a word
        "https://www.acquia.com/blog/guide",  # the vendor's own site
        "https://www.sba.gov/funding-programs/loans",
        "https://www.nist.gov/programs-projects/ai",
        "https://www.eeoc.gov/prohibited-employment-policiespractices",
        "https://www.cdc.gov/health-literacy/php/about/guidelines.html",
        "https://www.law.cornell.edu/wex/contract",
        "https://www.shrm.org/topics-tools/tools/job-descriptions",  # about jobs, not a job
        "https://www.ftc.gov/business-guidance/advertising-marketing",
        "https://www.score.org/?p=29289",  # a post by id, not the home page
        "https://www.homeoffice.gov.uk/guidance/recruitment",  # "home" in the host
        "https://www.sba.gov/counseling/plan-your-business/",
    ],
)
def test_content_pages_are_not_blocked(url: str) -> None:
    assert _block_reason(url) is None, url


async def test_one_document_on_two_sites_is_kept_once() -> None:
    found = await run(
        [
            ("https://sceweb.uhcl.edu/helm/SWEBOK_IEEE/SWEBOK_Guide_2004.pdf", "SWEBOK Guide"),
            ("https://www.inf.ed.ac.uk/teaching/resources/SWEBOK_2004.pdf", "SWEBOK 2004"),
        ],
        "technology/software-engineering",
    )
    assert len(found.sources) == 1
    assert found.rejected[0].reason == f"same document as {found.sources[0].url}"


async def test_same_title_pages_on_one_site_are_kept_once() -> None:
    found = await run(
        [
            ("https://www.franklincountyohio.gov/Food/Plan/Marketing-Sales", "Marketing & Sales"),
            (
                "https://www.franklincountyohio.gov/Dev/Food/Plan/Marketing-Sales",
                "Marketing & Sales",
            ),
            ("https://www.ftc.gov/advertising/node-1", "www.ftc.gov"),
            ("https://www.ftc.gov/advertising/node-2", "www.ftc.gov"),
        ],
        "marketing/strategy",
    )
    hosts = sorted(s.host for s in found.sources)
    assert hosts == ["franklincountyohio.gov", "ftc.gov", "ftc.gov"]  # bare titles never match
    assert [r.reason.split(" as ")[0] for r in found.rejected] == ["same title"]


async def test_a_registry_rule_can_cover_one_repository() -> None:
    found = await run(
        [
            ("https://github.com/google/eng-practices/blob/master/review/index.md", "github.com"),
            ("https://github.com/someone/notes/blob/main/review.md", "github.com"),
        ],
        "technology/software-engineering",
    )
    assert [(s.url.split("/")[4], s.tier) for s in found.sources] == [("eng-practices", "official")]
    assert found.rejected[0].reason == UNKNOWN_REASON  # the rest of GitHub


async def test_named_authorities_get_a_bonus() -> None:
    found = await run(
        [
            ("https://www.oregon.gov/hr/hiring-process", "Hiring process"),
            ("https://www.eeoc.gov/hiring-process", "Hiring process"),
        ],
        "hr/recruiting",
    )
    eeoc, oregon = found.sources
    assert eeoc.host == "eeoc.gov" and "a named authority for hr/recruiting" in eeoc.reasons
    assert eeoc.score - oregon.score >= AUTHORITY_BONUS
    assert not any("named authority" in r for r in oregon.reasons)


def test_authorities_match_their_site_not_every_subdomain_of_the_suffix() -> None:
    hints = DomainHints(authorities=["gov.uk", "sba.gov", "cipr.co.uk", "response.pagerduty.com"])
    assert hints.is_authority("gov.uk") and hints.is_authority("legacy.sba.gov")
    assert hints.is_authority("newsroom.cipr.co.uk")
    assert hints.is_authority("response.pagerduty.com")
    assert not hints.is_authority("old-leake.parish.lincolnshire.gov.uk")  # a parish council
    assert not hints.is_authority("pagerduty.com")


async def test_excluded_words_mark_a_page_off_topic() -> None:
    found = await run(
        [
            ("https://www.hhs.gov/guidance/medicare-marketing-guidelines", "Medicare marketing"),
            ("https://www.sba.gov/marketing-strategy", "Marketing strategy"),
        ],
        "marketing/strategy",
    )
    assert [s.host for s in found.sources] == ["sba.gov"]
    assert found.rejected[0].reason == 'off topic for marketing/strategy: "medicare"'


LEGAL_PINS = [
    "https://www.law.cornell.edu/wex/non-disclosure_agreement_(nda)",
    "https://www.law.cornell.edu/wex/contract",
    "https://www.law.cornell.edu/wex/trade_secret",
    "https://www.uspto.gov/ip-policy/trade-secret-policy",
]


async def test_pinned_sources_come_first_even_when_search_misses_them() -> None:
    found = await run(
        [("https://www.sba.gov/contracts", "Contracts guide")], registry=load_registry()
    )
    assert [s.url for s in found.sources] == [*LEGAL_PINS, "https://www.sba.gov/contracts"]
    nda = found.sources[0]
    assert nda.title == "non-disclosure agreement (NDA)" and nda.best_rank == 0
    assert "pinned in the registry (verified 2026-10-26)" in nda.reasons
    assert not any(r.startswith("search rank") for r in nda.reasons) and nda.crawl


async def test_a_pin_found_by_search_keeps_its_search_rank_and_the_pinned_title() -> None:
    found = await run([(LEGAL_PINS[1], "law.cornell.edu")], registry=load_registry())
    contract = next(s for s in found.sources if s.url == LEGAL_PINS[1])
    assert contract.title == "contract" and contract.best_rank == 1
    assert "search rank 1" in contract.reasons and len(found.sources) == len(LEGAL_PINS)


async def test_pins_still_follow_robots_and_the_high_risk_rule(tmp_path: Path) -> None:
    (tmp_path / "www.law.cornell.edu.txt").write_text(
        "User-agent: *\nDisallow: /wex/contract\n", encoding="utf-8"
    )
    data = load_registry().model_dump(mode="json")
    data["domains"]["legal/contracts"]["pinned"].append(
        {"url": "https://www.nolo.com/legal-encyclopedia/nda", "title": "NDAs", "verified": "x"}
    )
    found = await discover_sources(
        "legal/contracts",
        provider=Scripted([]),
        robots=FixtureRobots(tmp_path),
        registry=Registry.model_validate_json(json.dumps(data)),
    )
    assert [s.url for s in found.sources] == [LEGAL_PINS[0], *LEGAL_PINS[2:]]
    assert found.rejected[0].url == LEGAL_PINS[1] and "robots.txt" in found.rejected[0].reason
    [nolo] = found.listed  # a pin, but reference tier in a high-risk area: listed, not crawled
    assert nolo.tier == "reference" and not nolo.crawl and HIGH_RISK_REASON in nolo.reasons
    assert nolo.pinned and all(s.pinned for s in found.sources)


async def test_pins_are_never_capped_but_count_toward_the_site_cap() -> None:
    found = await run(
        [
            ("https://www.ftc.gov/business-guidance/blog/advertising", "Advertising blog"),
            ("https://www.sba.gov/marketing-strategy", "Marketing strategy"),
        ],
        "marketing/strategy",
        registry=load_registry(),
    )
    hosts = [s.host for s in found.sources]
    assert hosts[:3] == ["ftc.gov", "ftc.gov", "sba.gov"]  # the three marketing pins
    assert hosts.count("ftc.gov") == 2 and hosts.count("sba.gov") == 2
    assert "already 2 pages from this site" in found.rejected[0].reason


async def test_pages_with_no_title_rank_below_pages_with_titles() -> None:
    found = await run(
        [
            ("https://www.ftc.gov/advertising/node-54279", "www.ftc.gov"),
            ("https://www.franklincountyohio.gov/marketing-plan", "Marketing plan"),
        ],
        "marketing/strategy",
    )
    titled, untitled = found.sources
    assert titled.host == "franklincountyohio.gov" and untitled.host == "ftc.gov"
    assert untitled.score > titled.score and UNTITLED_REASON in untitled.reasons


async def test_legal_sources_in_the_wanted_jurisdiction_rank_first() -> None:
    found = await run(
        [
            ("https://www.gov.uk/non-disclosure-agreements", "Non-disclosure agreements"),
            ("https://www.nysenate.gov/contracts", "Contracts"),
        ]
    )
    us, uk = found.sources
    assert us.host == "nysenate.gov" and uk.host == "gov.uk" and uk.score > us.score
    assert "jurisdiction: UK (not US: ranked below US sources)" in uk.reasons


@pytest.mark.parametrize(
    ("place", "wanted", "inside"),
    [
        ("US", "US", True),
        ("US (federal)", "US", True),
        ("US (state or local)", "US", True),
        ("UK", "US", False),
        ("unknown", "US", False),
        ("USA", "US", False),
    ],
)
def test_in_jurisdiction(place: str, wanted: str, inside: bool) -> None:
    assert in_jurisdiction(place, wanted) is inside


def test_every_pin_is_allowed_by_its_saved_robots_txt() -> None:
    pins = [p for hints in load_registry().domains.values() for p in hints.pinned]
    assert len(pins) == 13  # ai 3, legal 4, hr 3, marketing 3
    for pin in pins:
        assert pin.title and pin.verified == "2026-10-26"
        assert FixtureRobots().status(pin.url) == "allowed", pin.url


async def test_a_page_with_no_topic_word_needs_a_pin() -> None:
    found = await run(
        [
            ("https://its.idaho.gov/?p=11145", "Idaho Official Government Website"),
            ("https://www.nist.gov/itl/ai/standards", "AI standards"),
        ],
        "technology/ai",
    )
    assert [s.host for s in found.sources] == ["nist.gov"]
    assert found.rejected[0].reason == NO_TOPIC_REASON
    # A pin stays though its words miss the topic: the endorsement guides never say
    # "advertising" or "marketing" in their title or URL.
    pinned = await run([], "marketing/strategy", registry=load_registry())
    endorsement = next(s for s in pinned.sources if "endorsement" in s.url)
    assert 'matched 0 of 1 words of "advertising"' in endorsement.reasons


async def test_an_unknown_site_enters_only_when_pinned() -> None:
    data = without_pins().model_dump(mode="json")
    pin = {
        "url": "https://handbook.example.com/postmortems",
        "title": "Postmortems",
        "verified": "x",
    }
    data["domains"]["technology/incident-response"]["pinned"] = [pin]
    found = await run(
        [("https://blog.example.com/my-postmortems", "Postmortems")],
        "technology/incident-response",
        registry=Registry.model_validate_json(json.dumps(data)),
    )
    assert [(s.host, s.tier) for s in found.sources] == [("handbook.example.com", "unknown")]
    assert found.rejected[0].reason == UNKNOWN_REASON


async def test_sources_not_crawled_are_listed_apart_and_take_no_top_place() -> None:
    found = await run(
        [
            ("https://en.wikipedia.org/wiki/Contract", "Contract"),
            ("https://www.nolo.com/contracts", "Contracts"),
            ("https://www.sba.gov/contracts", "Contracts"),
            ("https://www.example.gov/contracts", "Contracts"),
        ],
        limit=2,
    )
    assert [s.host for s in found.sources] == ["sba.gov", "example.gov"]
    assert {s.host for s in found.listed} == {"en.wikipedia.org", "nolo.com"}
    assert all(s.crawl for s in found.sources) and not any(s.crawl for s in found.listed)
    assert [u for u, _ in found.crawl_list()] == [s.url for s in found.sources]


async def test_technology_ai_has_three_pins() -> None:
    found = await run([], "technology/ai", registry=load_registry())
    assert [s.url for s in found.sources] == [
        "https://www.nist.gov/itl/ai-risk-management-framework",
        "https://developers.google.com/machine-learning/guides/rules-of-ml",
        "https://genai.owasp.org/llm-top-10/",
    ]
    assert all(s.pinned and s.crawl for s in found.sources)


def test_the_sheet_shows_listed_sources_apart(tmp_path: Path) -> None:
    lst = _one_source_list("legal/contracts", "https://www.sba.gov/a", "sba.gov", "official")
    nolo = _one_source_list(
        "legal/contracts", "https://www.nolo.com/b", "nolo.com", "reference", crawl=False
    ).sources[0]
    lst = lst.model_copy(update={"listed": [nolo]})
    md, _ = write_review("2026-10-26", [lst], automatic_checks([lst]), tmp_path)
    text = md.read_text(encoding="utf-8")
    assert "**Listed, not crawled (1):**" in text and "<https://www.nolo.com/b>" in text
    assert text.count("- [ ] authoritative") == 1  # only the top list is judged


async def test_excluded_terms_never_crawl(tmp_path: Path) -> None:
    registry = load_registry()
    data = registry.model_dump(mode="json")
    data["sources"].insert(
        0,
        {
            "host": "no-scraping.example",
            "tier": "official",
            "kind": "x",
            "licence": "excluded-terms",
        },
    )
    strict = without_pins(Registry.model_validate_json(json.dumps(data)))
    found = await run([("https://no-scraping.example/contracts", "Contracts")], registry=strict)
    assert found.sources == [] and "terms forbid" in found.rejected[0].reason


async def test_ranking_is_deterministic_and_round_trips() -> None:
    first = await discover_sources(
        "legal/contracts", Request("review-nda", ""), provider=FakeSearchProvider()
    )
    again = await discover_sources(
        "legal/contracts", Request("review-nda", ""), provider=FakeSearchProvider()
    )
    assert first == again
    assert SourceList.model_validate_json(first.model_dump_json()) == first


# ------------------------------------------------------------------ providers


async def test_fake_provider_replays_and_records() -> None:
    fake = FakeSearchProvider()
    results = await fake.search("contracts law", 3)
    assert [r.rank for r in results] == [1, 2, 3] and fake.calls == ["contracts law"]
    assert await fake.search("never recorded") == [] and fake.has("contracts law")


def test_brave_parses_results_and_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "web": {
            "results": [
                {
                    "url": "https://a.example/x",
                    "title": "<strong>A</strong> page",
                    "description": "about <b>A</b>",
                },
                {"title": "no url"},
                {"url": "https://b.example/", "title": "B"},
            ]
        }
    }
    parsed = parse_brave(data)
    assert [(r.url, r.title, r.rank, r.snippet) for r in parsed] == [
        ("https://a.example/x", "A page", 1, "about A"),
        ("https://b.example/", "B", 2, ""),
    ]
    assert parse_brave({}) == []
    monkeypatch.delenv(BRAVE_KEY_ENV, raising=False)
    with pytest.raises(ConfigError, match=BRAVE_KEY_ENV):
        BraveSearchProvider()


async def test_brave_sends_the_key_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"] = str(request.url), request.headers["X-Subscription-Token"]
        return httpx.Response(
            200, json={"web": {"results": [{"url": "https://a.example/", "title": "A"}]}}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    results = await BraveSearchProvider("test-key").search("contracts law", 5)
    assert results[0].url == "https://a.example/" and seen["key"] == "test-key"
    assert "q=contracts+law" in seen["url"] and "count=5" in seen["url"]


def test_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SEARCH_ENV, raising=False)
    assert isinstance(provider_from_env(), FakeSearchProvider)
    monkeypatch.setenv(SEARCH_ENV, "brave")
    monkeypatch.setenv(BRAVE_KEY_ENV, "k")
    assert isinstance(provider_from_env(), BraveSearchProvider)
    monkeypatch.setenv(SEARCH_ENV, "google")
    with pytest.raises(ConfigError, match="unknown"):
        provider_from_env()


@pytest.mark.live
async def test_brave_live() -> None:
    """Opt-in: `pytest -m live` with BRAVE_SEARCH_API_KEY set (costs about $0.005)."""
    import os

    if not os.environ.get(BRAVE_KEY_ENV):
        pytest.skip(f"{BRAVE_KEY_ENV} not set")
    results = await BraveSearchProvider().search("NIST AI risk management framework", 5)
    assert results and any("nist.gov" in r.url for r in results)


def test_http_robots_follows_rfc_9309(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {
        "https://a.example": "User-agent: *\nDisallow: /x\n",
        "https://down.example": "User-agent: *\nDisallow: /\n",
    }
    monkeypatch.setattr(
        "core.knowledge.search.fetch_robots", lambda origin, timeout_s=10.0: texts[origin]
    )
    robots = HttpRobots()
    assert robots.status("https://a.example/ok") == "allowed"
    assert robots.status("https://a.example/x/page") == "disallowed"
    assert robots.status("https://down.example/anything") == "disallowed"


# ------------------------------------------------------------------ registry and review


def test_registry_is_valid() -> None:
    registry = load_registry()
    hosts = [r.host for r in registry.sources if r.host]
    assert len(hosts) == len(set(hosts))
    assert all(b.reason for b in registry.blocked)
    assert all(r.matches(r.host, r.path_prefix or "/") for r in registry.sources if r.host)


def test_bad_registry_entries_are_refused() -> None:
    data = load_registry().model_dump(mode="json")
    for broken in (
        {"tier": "official", "kind": "no matcher"},
        {"host": "x.org", "tier": "famous", "kind": "k"},
    ):
        with pytest.raises(ValueError):
            Registry.model_validate_json(json.dumps({**data, "sources": [broken]}))
    with pytest.raises(ValueError):
        Registry.model_validate_json(
            json.dumps({**data, "blocked": [{"pattern": "([", "reason": "r"}]})
        )


async def test_review_covers_the_ten_seed_domains_and_passes_its_checks(tmp_path: Path) -> None:
    assert len(seed_domains()) == 10
    day, lists, checks = await build_review(today=date(2026, 10, 26))
    assert [lst.domain for lst in lists] == list(seed_domains())
    assert all(checks.values()), checks
    md, js = write_review(day, lists, checks, tmp_path)
    again, _ = write_review(day, lists, checks, tmp_path)
    assert md.name == "sources-2026-10-26.md" and again.name == "sources-2026-10-26-2.md"
    text = md.read_text(encoding="utf-8")
    top = sum(len(lst.sources) for lst in lists)  # the rules may leave fewer than 10
    assert 70 <= top <= 100 and text.count("- [ ] authoritative") == top
    assert "Human review: PENDING" in text
    assert json.loads(js.read_text(encoding="utf-8"))["checks"] == checks


def _one_source_list(domain: str, url: str, host: str, tier: str, crawl: bool = True) -> SourceList:
    source = {
        "url": url,
        "host": host,
        "title": "t",
        "tier": tier,
        "score": 1,
        "reasons": [],
        "licence": "copyright-summarise-and-cite",
        "robots": "allowed",
        "crawl": crawl,
        "best_rank": 1,
        "queries": 1,
    }
    data = {
        "domain": domain,
        "queries": ["q"],
        "registry_version": "1",
        "rejected": [],
        "sources": [source],
    }
    return SourceList.model_validate_json(json.dumps(data))


def test_automatic_checks_catch_a_blocked_source() -> None:
    lst = _one_source_list(
        "legal/contracts", "https://www.scribd.com/doc/1", "scribd.com", "unknown"
    )
    checks = automatic_checks([lst])
    assert not checks["no blocked source in any list"]
    assert not checks["every domain has at least 7 sources"]


def test_automatic_checks_catch_a_source_not_crawled_in_the_top_list() -> None:
    lst = _one_source_list("hr/recruiting", "https://x.gov/a", "x.gov", "official", crawl=False)
    assert not automatic_checks([lst])["the top 10 holds crawlable sources only"]


def test_automatic_checks_catch_a_weak_source_set_to_crawl_in_a_high_risk_domain() -> None:
    check = "high-risk domains crawl only official or academic sources"
    for domain, tier, ok in [
        ("medical/patient-education", "reference", False),
        ("finance/small-business", "unknown", False),
        ("legal/contracts", "academic", True),
        ("marketing/strategy", "unknown", True),
    ]:
        lst = _one_source_list(domain, "https://blog.example.com/a", "blog.example.com", tier)
        assert automatic_checks([lst])[check] is ok, (domain, tier)


def test_a_judged_sheet_appears_in_the_next_sheets_history(tmp_path: Path) -> None:
    lst = _one_source_list("legal/contracts", "https://www.sba.gov/a", "sba.gov", "official")
    checks = automatic_checks([lst])
    _, first = write_review("2026-10-26", [lst], checks, tmp_path)
    data = json.loads(first.read_text(encoding="utf-8"))
    data["human_review"] = {
        "reviewer": "A Reviewer",
        "date": "2026-10-26",
        "passed": False,
        "domains": {"legal/contracts": {"good": "1-2", "passed": False}},
        "notes": ["Too many procurement guides."],
    }
    first.write_text(json.dumps(data), encoding="utf-8")
    md, js = write_review("2026-10-26", [lst], checks, tmp_path)
    write_review("2026-10-27", [lst], checks, tmp_path)  # not judged: not in the history
    text = md.read_text(encoding="utf-8")
    assert "## Review history" in text
    assert "| sources-2026-10-26.md | A Reviewer | 2026-10-26 | FAIL | 0 / 1 |" in text
    assert "legal/contracts 1-2" in text and "- Too many procurement guides." in text
    assert json.loads(js.read_text(encoding="utf-8"))["history"][0]["sheet"] == (
        "sources-2026-10-26.md"
    )
    assert [h["sheet"] for h in review_history(tmp_path)] == ["sources-2026-10-26.md"]


def test_the_first_human_review_is_recorded() -> None:
    history = review_history()
    assert history[0]["sheet"] == "sources-2026-10-26-2.md"
    first = history[0]
    assert first["reviewer"] == "Ziad Abdullah" and first["passed"] is False
    passing = [d for d, v in first["domains"].items() if v["passed"]]
    assert passing == ["technology/ai", "technology/software-engineering", "data/analytics"]
    assert first["domains"]["legal/contracts"]["good"] == "1-2"


def test_the_second_human_review_is_recorded() -> None:
    second = review_history()[1]
    assert second["sheet"] == "sources-2026-10-26-3.md" and second["passed"] is False
    failing = [d for d, v in second["domains"].items() if not v["passed"]]
    assert failing == ["hr/recruiting", "marketing/strategy", "legal/contracts"]
    assert "how-to-apply" in second["domains"]["hr/recruiting"]["junk_in_top_5"]


def test_cli_check_data(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-data"]) == 0
    assert "OK" in capsys.readouterr().out
