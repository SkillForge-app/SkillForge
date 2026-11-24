"""DE-09: one way to write the host of a URL, for everything in DE that keys something by host.

The rules are those of AI's `normalise_url` (`ai/core/knowledge/urls.py`) for the host part of a URL:

- the scheme and the host are lower-case;
- a **default port is dropped** (80 for http, 443 for https) and any other port is kept (another port is another server);
- `user:password@` is dropped (it is not part of the server's name, and a password must never end up in a key or a log);
- an IPv6 address keeps its brackets (`[::1]`);
- nothing else is changed: a trailing dot (`example.org.`) is kept, exactly as AI's code keeps it, and an IDN host is not converted.

Used for: the per-host rate limit and the robots.txt cache of the crawler (`crawler/fetcher.py`, `crawler/robots.py`) and the host
grouping of the re-crawl schedule (`cache.py`, `DueSource.host_key`).

**Not used for `knowledge.sources.host`.** That column keeps the value `urlsplit(url).hostname.lower()` that the crawler and the
pipeline have always stored (no port, IPv6 without brackets); it is not changed here. See the question in `docs/p4-progress.md`.
"""
from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def host_key(url: str) -> str:
    """`host` or `host:port` of an http(s) URL in AI's normal form. Raises ValueError for anything else (also a bad port)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    try:
        port = parts.port
    except ValueError as exc:                       # a port that is not a number, or over 65535
        raise ValueError(f"not an http(s) URL: {url!r}") from exc
    host = parts.hostname.lower()
    if ":" in host:                                 # IPv6: urlsplit removed the brackets
        host = f"[{host}]"
    return host if port is None or port == DEFAULT_PORTS[scheme] else f"{host}:{port}"


def origin_key(url: str) -> str:
    """`scheme://host_key(url)`: what robots.txt belongs to (RFC 9309: one origin, one robots.txt)."""
    return f"{urlsplit(url.strip()).scheme.lower()}://{host_key(url)}"
