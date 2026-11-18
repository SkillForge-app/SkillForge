"""The canonical page URL (AI-10, contract with DE-04/DE-05): one rule for extraction and discovery.

    normalise_url("https://WWW.Example.org/Guide/?utm_source=x&id=2#top")
    # -> "https://www.example.org/Guide?id=2"

The canonical URL identifies a page: `extract_page()` hashes it into every `chunk_id` and returns
it as `ExtractedPage.url`, so every spelling of one page gets the same ids. It is an identifier,
not a fetch address: fetch with the original URL (docs/ai/extraction.md, "For Data Engineering").
Imports nothing from core.knowledge, so extraction and discovery can both use it.
"""

from urllib.parse import unquote_plus, urlsplit, urlunsplit

from pydantic import HttpUrl, ValidationError

# Tracking parameters dropped from the canonical URL (names compared case-insensitively).
TRACKING_PREFIXES = ("utm_",)
TRACKING_NAMES = frozenset({"gclid", "fbclid"})


def _is_tracking(segment: str) -> bool:
    name = unquote_plus(segment.split("=", 1)[0]).strip().lower()
    return name.startswith(TRACKING_PREFIXES) or name in TRACKING_NAMES


def normalise_url(url: str) -> str:
    """The canonical form of an http(s) URL. Raises ValueError for anything else.

    - scheme and host lowercase; a non-default port is kept; user:password@ is dropped
    - no fragment
    - utm_*, gclid and fbclid removed; every other query parameter kept verbatim, in order
    - trailing slashes removed from the path, except the root "/"

    The result is idempotent: normalise_url(normalise_url(u)) == normalise_url(u).
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    try:
        port = parts.port
    except ValueError as exc:  # e.g. a non-numeric port
        raise ValueError(f"not an http(s) URL: {url!r}") from exc
    host = parts.hostname.lower()
    if ":" in host:  # an IPv6 address: urlsplit removed its brackets
        host = f"[{host}]"
    netloc = host + (f":{port}" if port else "")
    query = "&".join(s for s in parts.query.split("&") if s and not _is_tracking(s))
    path = parts.path.rstrip("/") or "/"
    try:
        return str(HttpUrl(urlunsplit((parts.scheme.lower(), netloc, path, query, ""))))
    except ValidationError as exc:
        raise ValueError(f"not an http(s) URL: {url!r}") from exc
