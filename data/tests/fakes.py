"""Fakes of AI's functions (extract_page, embed, normalise_url) and small helpers for the pipeline tests.

A "page" in tests is JSON bytes: {"title", "paragraphs", "reject", "screening"}. FakeExtract turns it into an
ExtractedPage the way AI's extract_page would: one chunk per paragraph, chunk ids like
<host>-<sha256(url)[:8]>-<sha256(text)[:8]>, a rejected page without chunks.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from skillforge_data.interfaces import ExtractedChunk, ExtractedPage

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def page_bytes(paragraphs=("alpha text one", "beta text two"), *, title="A page", reject=(), screening=None) -> bytes:
    return json.dumps(
        {"title": title, "paragraphs": list(paragraphs), "reject": list(reject), "screening": screening}
    ).encode()


def fake_normalise_url(url: str) -> str:
    """The rules of AI's normalise_url, enough for tests: lower-case host, no fragment, no utm_*, no trailing slash."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    query = "&".join(p for p in parts.query.split("&") if p and not re.match(r"(?i)(utm_|gclid|fbclid)", p))
    path = parts.path.rstrip("/") or "/"
    port = parts.port
    netloc = parts.hostname.lower() + (f":{port}" if port and port not in (80, 443) else "")
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


class FakeExtract:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, html, *, url, retrieved) -> ExtractedPage:
        self.calls += 1
        data = json.loads(html)
        host = urlsplit(url).hostname
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        reject = tuple(data["reject"])
        chunks = ()
        if not reject:
            chunks = tuple(
                ExtractedChunk(
                    chunk_id=f"{host}-{url_hash}-{hashlib.sha256(text.encode()).hexdigest()[:8]}",
                    text=text, position=i, word_count=max(1, len(text.split())),
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    section=("Intro",), concepts=("concept",),
                )
                for i, text in enumerate(data["paragraphs"])
            )
        return ExtractedPage(
            url=url, title=data["title"], text="\n".join(data["paragraphs"]), quality_ok=not reject,
            quality_reasons=reject, language="en", screening=data["screening"], chunks=chunks,
        )


def unit_vector(seed: str, dimensions: int = 384) -> list[float]:
    rng = random.Random(seed)
    v = [rng.random() - 0.5 for _ in range(dimensions)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


class FakeEmbed:
    def __init__(self, dimensions: int = 384, scale: float = 1.0) -> None:
        self.calls = 0
        self.texts_embedded = 0
        self.dimensions = dimensions
        self.scale = scale

    def __call__(self, texts):
        self.calls += 1
        self.texts_embedded += len(texts)
        return [[x * self.scale for x in unit_vector(t, self.dimensions)] for t in texts]


class BrokenEmbed:
    def __call__(self, texts):
        raise RuntimeError("embedding service is down")
