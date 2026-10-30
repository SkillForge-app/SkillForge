"""Source discovery (AI-09): which pages to crawl for a domain, best first, and whether we may.

    found = await discover_sources("legal/contracts")          # or request=AnalyzedRequest
    found.sources        # RankedSource list: tier, score, reasons, licence, robots, crawl
    found.crawl_list()   # [(url, licence)] for DE-04: only what we may crawl
    found.rejected       # what was dropped, and why (blocked, robots, licence, duplicate)

Queries come from the domain (and the request, when there is one). A pluggable search provider
runs them: SKILLFORGE_SEARCH=fake (recorded results, the default until there is a key) or
brave (Brave Search API, BRAVE_SEARCH_API_KEY). Candidates are ranked by authority from the
registry in sources.yaml (official > academic and publisher > reference > unknown), relevance,
the provider's rank and fit with the domain's area. Blocked sites never make the list, and at
most two pages per site do. A domain's pinned sources (hand-checked URLs in the registry) come
first; sources outside the domain's jurisdiction, then pages with no title, come last. Robots.txt
is checked ahead of DE-04, which still enforces it.
"""

import asyncio
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import yaml
from pydantic import Field, ValidationError, model_validator

from core.knowledge.retrieval import check_domain
from core.llm.errors import ConfigError
from core.spec.models import HIGH_RISK_AREAS, SpecModel

REGISTRY_PATH = Path(__file__).with_name("sources.yaml")
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "search"
SEARCH_ENV = "SKILLFORGE_SEARCH"
BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"
USER_AGENT = "SkillForgeBot"
MAX_QUERIES = 8
PER_SITE = 2  # pages per site in one list
AUTHORITY_BONUS = 30  # for a site the registry names as an authority for this domain

Tier = Literal["official", "academic", "reference", "unknown"]
TIER_SCORES: dict[str, int] = {"official": 100, "academic": 80, "reference": 60, "unknown": 30}
# In legal, medical and finance only these may be crawled; others stay listed, crawl=False.
AUTHORITATIVE_TIERS = frozenset({"official", "academic"})
HIGH_RISK_REASON = "high-risk area needs an authoritative source"
UNTITLED_REASON = "no page title (ranked below pages with titles)"
UNKNOWN_REASON = "unknown site (no authority signal): only a pin can list it"
NO_TOPIC_REASON = "no topic words in its title or URL"
Licence = Literal[
    "public-domain-us-gov",
    "cc-by-4.0",
    "cc-by-sa-4.0",
    "copyright-summarise-and-cite",
    "excluded-terms",
]
Robots = Literal["allowed", "disallowed", "unknown"]


# ------------------------------------------------------------------ registry


class AreaWords(SpecModel):
    topic: str = Field(pattern=r"\{sub\}")
    hint: str


def _host_matches(
    host: str, exact: str | None, suffix: str | None, prefix: str | None = None
) -> bool:
    """Every given matcher must hold: `exact` is the site or a subdomain of it."""
    if exact is not None and not (host == exact or host.endswith("." + exact)):
        return False
    if suffix is not None and not host.endswith(suffix):
        return False
    return prefix is None or host.startswith(prefix)


class HostRule(SpecModel):
    """A site (`host`, with its subdomains), a host `suffix` (e.g. .gov) or `host_prefix`;
    `path_prefix` narrows a rule to one part of a site (e.g. one GitHub repository)."""

    host: str | None = None
    suffix: str | None = None
    host_prefix: str | None = None
    path_prefix: str | None = None
    tier: Tier
    kind: str  # shown in the reasons, e.g. "government site"
    licence: Licence = "copyright-summarise-and-cite"
    areas: list[str] = Field(default_factory=list)  # areas it is authoritative for; [] = any
    jurisdiction: str | None = None  # whose law it describes, when the host does not say

    @model_validator(mode="after")
    def _has_matcher(self) -> "HostRule":
        if self.host is None and self.suffix is None and self.host_prefix is None:
            raise ValueError("a source rule needs host, suffix or host_prefix")
        return self

    def matches(self, host: str, path: str = "/") -> bool:
        if self.path_prefix is not None and not path.startswith(self.path_prefix):
            return False
        return _host_matches(host, self.host, self.suffix, self.host_prefix)


class Block(SpecModel):
    host: str | None = None
    suffix: str | None = None
    pattern: str | None = None  # a regular expression searched in the URL
    title_pattern: str | None = None  # a regular expression searched in the page title
    reason: str

    @model_validator(mode="after")
    def _has_matcher(self) -> "Block":
        matchers = (self.host, self.suffix, self.pattern, self.title_pattern)
        if all(m is None for m in matchers):
            raise ValueError("a block needs host, suffix, pattern or title_pattern")
        for pattern in (self.pattern, self.title_pattern):
            if pattern is not None:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"bad pattern {pattern!r}: {exc}") from exc
        return self

    def matches(self, url: str, host: str, title: str = "") -> bool:
        if self.pattern is not None and not re.search(self.pattern, url):
            return False
        if self.title_pattern is not None and not re.search(self.title_pattern, title):
            return False
        if self.host is None and self.suffix is None:
            return True
        return _host_matches(host, self.host, self.suffix)


class Pinned(SpecModel):
    """A hand-picked page that always ranks first for its domain. A person opened it and
    checked its title on `verified` (a date)."""

    url: str
    title: str
    verified: str


class DomainHints(SpecModel):
    """Extra wording for one domain, when the generic queries bring back off-topic pages."""

    terms: list[str] = Field(default_factory=list)  # phrases that also count as on topic
    queries: list[str] = Field(default_factory=list)  # run before the domain templates
    templates: bool = True  # False: skip the generic templates, they bring back junk here
    authorities: list[str] = Field(default_factory=list)  # sites named as this domain's experts
    exclude: list[str] = Field(default_factory=list)  # words that mark a page off topic here
    pinned: list[Pinned] = Field(default_factory=list)  # search alone does not reach these
    jurisdiction: str | None = None  # e.g. "US": its sources rank above other jurisdictions'

    def is_authority(self, host: str) -> bool:
        return host in self.authorities or site_of(host) in self.authorities


class Registry(SpecModel):
    version: str
    acronyms: list[str]
    areas: dict[str, AreaWords]
    domains: dict[str, DomainHints] = Field(default_factory=dict)
    templates: list[str]
    sources: list[HostRule] = Field(default_factory=list)
    blocked: list[Block] = Field(default_factory=list)


@lru_cache(maxsize=4)
def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    import json

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return Registry.model_validate_json(json.dumps(data))
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid: {exc.error_count()} errors") from exc


# ------------------------------------------------------------------ queries


def build_queries(
    domain: str, request: Any | None = None, registry: Registry | None = None
) -> list[str]:
    """Up to MAX_QUERIES search queries for `domain`, deterministic, no LLM.

    `request` is an AnalyzedRequest (or anything with `skill_name` / `summary` and
    `expected_outputs`). It adds one query for the skill itself and one for its first expected
    output, ahead of the domain templates.
    """
    check_domain(domain)
    registry = registry or load_registry()
    area, _, sub = domain.partition("/")
    words = registry.areas.get(area) or registry.areas["general"]
    topic = words.topic.format(sub=_words(sub or area, registry))
    queries: list[str] = []
    if request is not None:
        name = getattr(request, "skill_name", None)
        skill = _words(name, registry) if name else " ".join(str(request.summary).split()[:12])
        missing = [w for w in topic.split() if w.lower() not in skill.lower()]
        queries.append(" ".join([skill, *missing, "guide"]))
        queries += [f"{output} template" for output in list(request.expected_outputs)[:1]]
    hints = registry.domains.get(domain)
    if hints is not None:
        queries += hints.queries
    if hints is None or hints.templates:
        queries += [t.format(topic=topic, hint=words.hint) for t in registry.templates]
    unique = list(dict.fromkeys(" ".join(q.split()) for q in queries if q.strip()))
    return unique[:MAX_QUERIES]


def _words(kebab: str, registry: Registry) -> str:
    return " ".join(w.upper() if w in registry.acronyms else w for w in kebab.split("-"))


def topic_words(domain: str, registry: Registry | None = None) -> set[str]:
    """The domain's topic as plain terms (e.g. {"patient", "education"}), for relevance."""
    registry = registry or load_registry()
    area, _, sub = domain.partition("/")
    words = registry.areas.get(area) or registry.areas["general"]
    return _terms(words.topic.format(sub=_words(sub or area, registry)))


def topic_phrases(domain: str, registry: Registry | None = None) -> list[tuple[str, set[str]]]:
    """(phrase, terms) that make a page on topic: the domain topic, then its hint terms."""
    registry = registry or load_registry()
    area, _, sub = domain.partition("/")
    words = registry.areas.get(area) or registry.areas["general"]
    phrases = [words.topic.format(sub=_words(sub or area, registry))]
    hints = registry.domains.get(domain)
    phrases += hints.terms if hints else []
    return [(p, _terms(p)) for p in phrases if _terms(p)]


def jurisdiction_of(host: str, rule: "HostRule | None") -> str:
    """Whose law a legal source describes: the registry's note, else the host's suffix."""
    if rule is not None and rule.jurisdiction:
        return rule.jurisdiction
    if rule is not None and rule.licence == "public-domain-us-gov":
        return "US (federal)"
    for suffix, place in _JURISDICTIONS:
        if host.endswith(suffix):
            return place
    return "unknown"


_JURISDICTIONS = (
    (".gov", "US (state or local)"),
    (".mil", "US (federal)"),
    (".edu", "US"),
    (".uk", "UK"),
    (".eu", "EU"),
    (".ie", "Ireland"),
    (".ca", "Canada"),
    (".au", "Australia"),
    (".in", "India"),
)


_STOP = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how"}
    | {"in", "is", "of", "on", "or", "the", "to", "with"}
)


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words} - _STOP


# ------------------------------------------------------------------ search providers


class SearchError(Exception):
    """The search provider failed (network, quota, bad key)."""


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    rank: int  # 1 = the provider's top result
    snippet: str = ""


class SearchProvider(Protocol):
    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        """At most `count` results for `query`, in the provider's order."""
        ...


@dataclass
class FakeSearchProvider:
    """Replays recorded results (tests/fixtures/search/results.yaml) by exact query."""

    path: Path = FIXTURES_DIR / "results.yaml"
    calls: list[str] = field(default_factory=list, init=False)
    _results: dict[str, list[SearchResult]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self._results = {
            " ".join(query.split()): [
                SearchResult(r["url"], r.get("title") or "", int(r["rank"]), r.get("snippet") or "")
                for r in results
            ]
            for query, results in data["results"].items()
        }

    def has(self, query: str) -> bool:
        """Whether results were recorded for this query."""
        return bool(self._results.get(" ".join(query.split())))

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        self.calls.append(query)
        return self._results.get(" ".join(query.split()), [])[:count]


class BraveSearchProvider:
    """Brave Search API (https://api.search.brave.com): $5 per 1,000 searches, with a $5 monthly
    credit (checked 2026-10-26). Needs BRAVE_SEARCH_API_KEY."""

    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, *, timeout_s: float = 15.0) -> None:
        self.api_key = api_key or os.environ.get(BRAVE_KEY_ENV, "")
        if not self.api_key:
            raise ConfigError(f"{BRAVE_KEY_ENV} is not set")
        self.timeout_s = timeout_s

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(
                    self.ENDPOINT,
                    params={"q": query, "count": min(count, 20)},
                    headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchError(f"Brave search failed: {type(exc).__name__}") from exc
        return parse_brave(response.json())[:count]


def parse_brave(data: dict[str, Any]) -> list[SearchResult]:
    results = [r for r in (data.get("web") or {}).get("results") or [] if r.get("url")]
    return [
        SearchResult(
            str(r["url"]),
            _strip_tags(str(r.get("title") or "")),
            i,
            _strip_tags(str(r.get("description") or "")),
        )
        for i, r in enumerate(results, 1)
    ]


def _strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", text).split())


def provider_from_env() -> SearchProvider:
    backend = os.environ.get(SEARCH_ENV, "fake").strip().lower()
    if backend == "fake":
        return FakeSearchProvider()
    if backend == "brave":
        return BraveSearchProvider()
    raise ConfigError(f"unknown {SEARCH_ENV}={backend!r}; use 'fake' or 'brave'")


# ------------------------------------------------------------------ robots.txt


class RobotsPolicy(Protocol):
    def status(self, url: str) -> Robots: ...


def _robots_allows(text: str, url: str) -> bool:
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


@dataclass
class FixtureRobots:
    """robots.txt files saved once (tests/fixtures/search/robots/<host>.txt); a host with no
    file is `unknown`."""

    folder: Path = FIXTURES_DIR / "robots"

    def status(self, url: str) -> Robots:
        host = (urlsplit(url).hostname or "").lower()
        path = self.folder / f"{host}.txt"
        if not path.is_file():
            return "unknown"
        return "allowed" if _robots_allows(path.read_text(encoding="utf-8"), url) else "disallowed"


@dataclass
class HttpRobots:
    """Fetches each host's robots.txt once (RFC 9309): 4xx means no rules (allowed); 5xx or no
    answer means assume everything is disallowed. For DE-04, which enforces it when crawling."""

    timeout_s: float = 10.0
    _cache: dict[str, str] = field(default_factory=dict, repr=False)

    def status(self, url: str) -> Robots:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host not in self._cache:
            self._cache[host] = fetch_robots(f"{parts.scheme}://{parts.netloc}", self.timeout_s)
        return "allowed" if _robots_allows(self._cache[host], url) else "disallowed"


DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


def fetch_robots(origin: str, timeout_s: float = 10.0) -> str:
    """robots.txt text for a site, following RFC 9309 for errors (see HttpRobots)."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return str(response.read(500_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return "" if 400 <= exc.code < 500 else DISALLOW_ALL
    except (urllib.error.URLError, TimeoutError, OSError):
        return DISALLOW_ALL


# ------------------------------------------------------------------ results


class RankedSource(SpecModel):
    url: str
    host: str
    title: str
    snippet: str = ""
    tier: Tier
    score: int
    reasons: list[str]
    licence: Licence
    robots: Robots
    crawl: bool
    best_rank: int  # 0: a pinned source no search found
    queries: int  # how many of the queries found it
    pinned: bool = False  # hand-picked in the registry: first, and never capped per site


class Rejected(SpecModel):
    url: str
    reason: str


class SourceList(SpecModel):
    domain: str
    queries: list[str]
    registry_version: str
    sources: list[RankedSource]  # the top list: crawlable sources only
    rejected: list[Rejected]
    listed: list[RankedSource] = Field(default_factory=list)  # ranked, crawl=False: never crawled

    def crawl_list(self) -> list[tuple[str, str]]:
        """(url, licence) for DE-04: only sources we may crawl, best first."""
        return [(s.url, s.licence) for s in self.sources if s.crawl]


# ------------------------------------------------------------------ discovery

TRACKING_PARAMS = frozenset({"ref", "fl", "x", "pd", "amp", "gclid", "fbclid", "mc_cid", "mc_eid"})
_LOCALE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")


# Public suffixes with two labels, so "gov.uk" sites are one level deeper than "nist.gov".
_TWO_LABEL_SUFFIXES = frozenset(
    {"gov.uk", "ac.uk", "co.uk", "org.uk", "gov.au", "edu.au", "com.au", "org.au", "gov.in"}
    | {"co.in", "gov.br", "com.br", "edu.py", "edu.jm", "edu.vn", "gov.hk", "co.jp", "ac.jp"}
)


def site_of(host: str) -> str:
    """The registrable site: www.ed.gov and www2.ed.gov are both ed.gov."""
    labels = host.lower().split(".")
    keep = 3 if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def normalise(url: str) -> tuple[str, str, str]:
    """(clean url, duplicate key, host). Clean: lowercase host, no fragment or tracking
    parameters. The key is the site and path, so copies of one page on two hosts of one site
    (www2., a dev copy) meet, as do AMP and Markdown copies, a trailing slash, a leading
    locale folder ("/fr-fr/") and an "/index.php/" (or "/index%2Ephp/") prefix."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    netloc = host + (f":{parts.port}" if parts.port else "")
    clean = urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(query), ""))
    path = unquote(parts.path).rstrip("/")
    path = re.sub(r"(/amp|\.md)$", "", path)
    segments = [s for s in path.split("/") if s and s.lower() != "index.php"]
    if segments and _LOCALE.match(segments[0].lower()):
        segments = segments[1:]
    key = f"{site_of(host)}/{'/'.join(segments).lower()}?{urlencode(sorted(query))}"
    return clean, key, host.removeprefix("www.")


@dataclass
class _Candidate:
    url: str
    host: str
    title: str
    snippet: str
    best_rank: int  # 0: pinned, and no search found it
    queries: set[int]
    pin: Pinned | None = None


def _blocked(url: str, host: str, registry: Registry, title: str = "") -> str | None:
    for block in registry.blocked:
        if block.matches(url, host, title):
            return block.reason
    return None


def in_jurisdiction(place: str, wanted: str) -> bool:
    """ "US (federal)" and "US (state or local)" are both in "US"."""
    return place == wanted or place.startswith(f"{wanted} (")


def _rule(host: str, registry: Registry, path: str = "/") -> HostRule | None:
    return next((rule for rule in registry.sources if rule.matches(host, path)), None)


_DOCUMENT = re.compile(r"\.(pdf|docx?|pptx?)$", re.IGNORECASE)
# Words in a file name that do not tell documents apart ("SWEBOK_Guide_2004.pdf").
_FILE_FILLER = frozenset({"guide", "final", "draft", "copy", "version", "print", "web"})


def document_key(url: str) -> str | None:
    """A PDF or Office file's name as words, so one document hosted on two sites meets:
    SWEBOK_Guide_2004.pdf and SWEBOK_2004.pdf. None for web pages and names under 2 words."""
    name = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    if not _DOCUMENT.search(name):
        return None
    words = {
        w
        for w in _terms(_DOCUMENT.sub("", name))
        if w not in _FILE_FILLER and not (w.isdigit() and len(w) <= 2)
    }
    return " ".join(sorted(words)) if len(words) >= 2 else None


def title_key(title: str, host: str) -> str | None:
    """The title as words, so two pages on one site with the same title meet ("Hiring" and
    "Hiring | U.S. Department of Labor": a trailing " | site name" is ignored). None when the
    title is only the host name, as some search results give."""
    title = re.split(r"\s+[|–—]\s+", title)[0]
    words = _terms(title) - _terms(host) - {"www"}
    return " ".join(sorted(words)) if words else None


async def discover_sources(
    domain: str,
    request: Any | None = None,
    *,
    limit: int = 10,
    provider: SearchProvider | None = None,
    robots: RobotsPolicy | None = None,
    registry: Registry | None = None,
    per_query: int = 10,
) -> SourceList:
    """Ranked sources to crawl for `domain` (a SkillSpec domain or area), best first."""
    registry = registry or load_registry()
    queries = build_queries(domain, request, registry)
    provider = provider or provider_from_env()
    if robots is None:
        robots = FixtureRobots() if isinstance(provider, FakeSearchProvider) else HttpRobots()
    area = domain.split("/", 1)[0]
    phrases = topic_phrases(domain, registry)
    hints = registry.domains.get(domain) or DomainHints()
    excluded = [(word, _terms(word)) for word in hints.exclude]

    candidates: dict[str, _Candidate] = {}
    rejected: list[Rejected] = []
    duplicates: set[str] = set()
    for qi, query in enumerate(queries):
        for result in await provider.search(query, per_query):
            url, key, host = normalise(result.url)
            seen = candidates.get(key)
            if seen is None:
                candidates[key] = _Candidate(
                    url, host, result.title, result.snippet, result.rank, {qi}
                )
                continue
            if seen.url != url and url not in duplicates:
                duplicates.add(url)
                rejected.append(Rejected(url=url, reason=f"duplicate of {seen.url}"))
            seen.best_rank = min(seen.best_rank, result.rank)
            seen.queries.add(qi)
    for pin in hints.pinned:  # in the list even when no search found it
        url, key, host = normalise(pin.url)
        if key not in candidates:
            candidates[key] = _Candidate(url, host, pin.title, "", 0, set())
        candidates[key].pin = pin
        candidates[key].title = pin.title

    # Order: pinned sources (in registry order), then the rest; within each, sources outside
    # the domain's jurisdiction, then pages with no title, come last; then by score.
    scored: list[tuple[tuple[int, int, int, int], RankedSource]] = []
    for c in candidates.values():
        # A pin was checked by a person: no block, exclude or weak-match test.
        reason = None if c.pin else _blocked(c.url, c.host, registry, c.title)
        if reason is not None:
            rejected.append(Rejected(url=c.url, reason=f"blocked: {reason}"))
            continue
        rule = _rule(c.host, registry, urlsplit(c.url).path)
        tier: Tier = rule.tier if rule else "unknown"
        licence: Licence = rule.licence if rule else "copyright-summarise-and-cite"
        if licence == "excluded-terms":
            rejected.append(Rejected(url=c.url, reason="the site's terms forbid reuse"))
            continue
        page = _terms(f"{c.title} {urlsplit(c.url).path} {c.snippet}")
        off_topic = next((word for word, terms in excluded if terms <= page), None)
        if off_topic is not None and not c.pin:
            rejected.append(Rejected(url=c.url, reason=f'off topic for {domain}: "{off_topic}"'))
            continue
        phrase, terms = max(phrases, key=lambda pt: (len(pt[1] & page) / len(pt[1]), -len(pt[1])))
        found = terms & page
        share = len(found) / len(terms)
        # Only a pin brings in an unknown site, a page with no topic word, or a source the
        # registry names for other areas only (unless this domain names it as an authority).
        if not c.pin:
            if tier == "unknown":
                rejected.append(Rejected(url=c.url, reason=UNKNOWN_REASON))
                continue
            if not found:
                rejected.append(Rejected(url=c.url, reason=NO_TOPIC_REASON))
                continue
            if rule and rule.areas and area not in rule.areas and not hints.is_authority(c.host):
                reason = f"an authority for {', '.join(rule.areas)} only, not {area}"
                rejected.append(Rejected(url=c.url, reason=reason))
                continue
        relevance = round(20 * share)
        rank_bonus = max(0, 11 - c.best_rank) if c.best_rank else 0
        agreement = min(10, 5 * max(0, len(c.queries) - 1))
        reasons = [rule.kind if rule else "no authority signal (unknown site)"]
        if c.pin:
            reasons.append(f"pinned in the registry (verified {c.pin.verified})")
        reasons.append(f'matched {len(found)} of {len(terms)} words of "{phrase}"')
        if c.best_rank:
            reasons.append(f"search rank {c.best_rank}")
        if len(c.queries) > 1:
            reasons.append(f"found by {len(c.queries)} queries")
        fit = 0
        if rule and rule.areas:
            fit = 10 if area in rule.areas else -15
            reasons.append(
                f"an authority for {area}"
                if fit > 0
                else f"an authority for {', '.join(rule.areas)}, not {area}"
            )
        named = AUTHORITY_BONUS if hints.is_authority(c.host) else 0
        if named:
            reasons.append(f"a named authority for {domain}")
        outside = False
        if area == "legal" or hints.jurisdiction:
            place = jurisdiction_of(c.host, rule)
            wanted = hints.jurisdiction
            outside = wanted is not None and not in_jurisdiction(place, wanted)
            note = f" (not {wanted}: ranked below {wanted} sources)" if outside else ""
            reasons.append(f"jurisdiction: {place}{note}")
        untitled = title_key(c.title, c.host) is None
        if untitled:
            reasons.append(UNTITLED_REASON)
        crawl = True
        if area in HIGH_RISK_AREAS and tier not in AUTHORITATIVE_TIERS:
            crawl = False  # kept for review, never crawled
            reasons.append(HIGH_RISK_REASON)
        score = TIER_SCORES[tier] + relevance + rank_bonus + agreement + fit + named
        order = (0, hints.pinned.index(c.pin)) if c.pin else (1, 0)
        scored.append((
            (*order, int(outside), int(untitled)),
            RankedSource(
                url=c.url, host=c.host, title=c.title, snippet=c.snippet, tier=tier, score=score,
                reasons=reasons, licence=licence, robots="unknown", crawl=crawl,
                best_rank=c.best_rank, queries=len(c.queries), pinned=c.pin is not None,
            ),
        ))  # fmt: skip

    scored.sort(key=lambda item: (item[0], -item[1].score, item[1].url))
    kept: list[RankedSource] = []  # crawlable: the top list
    listed: list[RankedSource] = []  # crawl=False (e.g. the high-risk rule): shown apart
    per_site: dict[str, int] = {}
    documents: dict[str, str] = {}  # document_key -> the kept URL
    titles: dict[tuple[str, str], str] = {}  # (site, title_key) -> the kept URL
    for (group, *_), source in scored:  # group 0: pinned
        if len(kept) >= limit and len(listed) >= limit:
            break
        if len(kept if source.crawl else listed) >= limit:
            continue
        site = site_of(source.host)
        doc = document_key(source.url)
        title = title_key(source.title, source.host)
        if doc is not None and doc in documents:
            rejected.append(Rejected(url=source.url, reason=f"same document as {documents[doc]}"))
            continue
        if title is not None and (site, title) in titles:
            rejected.append(Rejected(url=source.url, reason=f"same title as {titles[site, title]}"))
            continue
        if not source.crawl:  # listed for review; takes no place in the top list or site cap
            status = robots.status(source.url)
            if status == "disallowed":
                reason = f"robots.txt disallows {USER_AGENT}"
                rejected.append(Rejected(url=source.url, reason=reason))
            else:
                listed.append(source.model_copy(update={"robots": status}))
            continue
        if per_site.get(site, 0) >= PER_SITE and group != 0:  # pins are never capped
            rejected.append(
                Rejected(url=source.url, reason=f"already {PER_SITE} pages from this site")
            )
            continue
        status = robots.status(source.url)
        if status == "disallowed":
            rejected.append(Rejected(url=source.url, reason=f"robots.txt disallows {USER_AGENT}"))
            continue
        per_site[site] = per_site.get(site, 0) + 1
        if doc is not None:
            documents[doc] = source.url
        if title is not None:
            titles[site, title] = source.url
        kept.append(source.model_copy(update={"robots": status}))
    return SourceList(
        domain=domain,
        queries=queries,
        registry_version=registry.version,
        sources=kept,
        rejected=rejected,
        listed=listed,
    )


def discover_sources_sync(domain: str, request: Any | None = None, **kwargs: Any) -> SourceList:
    """Blocking `discover_sources`, for scripts."""
    return asyncio.run(discover_sources(domain, request, **kwargs))
