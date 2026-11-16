"""DE-05: the adapter between our pipeline interfaces and AI's real functions (`ai/core`, the `skillforge` package).

    AI's extract_page / ExtractConfig   ->  ExtractPage / ExtractConfigLike   (`make_extract`, `default_extract_config`)
    AI's embed_sync                     ->  Embed                             (`make_embed`)
    AI's normalise_url                  ->  NormaliseUrl                      (`normalise_url`)
    AI's find_site_boilerplate          ->  per-host hashes                   (`site_boilerplate`)

AI's code is imported **inside the functions that need it** (never at module import), so this module can be imported, and everything
that uses fakes can be tested, on a machine where `skillforge` is not installed. Install it with the optional extra `ai` (see
`pyproject.toml`). The conversion functions (`convert_page`, `check_vectors`, `embedding_version`) only read attributes and use no AI
import, so they are tested with stand-in objects that always run; tests against the real code carry the marker `ai_real`.
"""
from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from ..interfaces import (
    Embed,
    ExtractConfigLike,
    ExtractedChunk,
    ExtractedPage,
    ExtractPage,
    NormaliseUrl,
    PipelineError,
)
from ..pipeline.config import EMBEDDING_DIMENSIONS

INSTALL_HINT = (
    "AI's code (the `skillforge` package, ai/core) is not installed. Install the optional extra: "
    "pip install -e \"data[ai]\"  (see data/pyproject.toml)"
)

# The pinned model of the `embedding` role (ai/core/llm/models.yaml, role `embedding`), written in the form of retrieval.md:
# `repo@revision#file:sha256=<hash>`. `embedding_version_from_ai()` reads the same values from AI's config; a test compares the two.
PINNED_EMBEDDING = {
    "repo": "Qdrant/bge-small-en-v1.5-onnx-Q",
    "revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
    "file": "model_optimized.onnx",
    "sha256": "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431",
}


def embedding_version(repo: str, revision: str, file: str, sha256: str) -> str:
    """AI's long form: `Qdrant/bge-small-en-v1.5-onnx-Q@<revision>#model_optimized.onnx:sha256=<hash>`."""
    return f"{repo}@{revision}#{file}:sha256={sha256}"


EMBEDDING_VERSION = embedding_version(**PINNED_EMBEDDING)


def _ai() -> Any:
    """AI's `core.knowledge` package, imported when first needed."""
    try:
        return importlib.import_module("core.knowledge")
    except ImportError as exc:                         # not installed
        raise ImportError(INSTALL_HINT) from exc


def _ai_llm() -> Any:
    try:
        return importlib.import_module("core.llm")
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc


# ------------------------------------------------------------------------------------------------- URLs
def normalise_url(url: str) -> str:
    """AI's `normalise_url`: the canonical URL. Raises ValueError for anything that is not http(s)."""
    return _ai().normalise_url(url)


# --------------------------------------------------------------------------------------- extract config
def default_extract_config(site_boilerplate: Iterable[str] = ()) -> ExtractConfigLike:
    """AI's `ExtractConfig()` with the site's boilerplate hashes. The fingerprint does not depend on them."""
    config_type = _ai().ExtractConfig
    hashes = tuple(site_boilerplate)
    return config_type().model_copy(update={"site_boilerplate": hashes}) if hashes else config_type()


def site_boilerplate(pages: Iterable[tuple[str | bytes, str]], *, min_pages: int = 2) -> dict[str, tuple[str, ...]]:
    """AI's `find_site_boilerplate`: {host: hashes} from (html, url) pairs of one crawl. Run it once per host, not once per page."""
    return dict(_ai().find_site_boilerplate(pages, min_pages=min_pages))


# ------------------------------------------------------------------------------------------------ extract
def convert_page(page: Any) -> ExtractedPage:
    """AI's pydantic `ExtractedPage` -> ours. Reads attributes only."""
    quality = page.quality
    chunks = tuple(
        ExtractedChunk(
            chunk_id=str(c.chunk_id), text=c.text, position=c.position, word_count=c.word_count, content_hash=c.content_hash,
            section=tuple(c.section), concepts=tuple(c.concepts),
        )
        for c in page.chunks
    )
    screening = page.screening
    if screening is not None and not isinstance(screening, Mapping):
        screening = screening.model_dump(mode="json")
    return ExtractedPage(
        url=str(page.url), title=str(page.title), text=page.text, quality_ok=bool(quality.ok),
        quality_reasons=tuple(str(r) for r in quality.reasons), language=quality.language,
        screening=screening, chunks=chunks,
    )


def make_extract(config: ExtractConfigLike | None = None, *, extract_page: Callable[..., Any] | None = None) -> ExtractPage:
    """An `ExtractPage` that calls AI's `extract_page` with `config` (default `ExtractConfig()`).

    A page AI cannot take (not an http(s) URL) raises `PipelineError`: the old content stays. `extract_page` can be injected for tests.
    """
    if extract_page is None:
        extract_page = _ai().extract_page
    config = config if config is not None else default_extract_config()

    def extract(html: bytes | str, *, url: str, retrieved: date) -> ExtractedPage:
        try:
            page = extract_page(html, url=url, retrieved=retrieved, config=config)
        except ValueError as exc:                       # AI's ExtractionInputError is a ValueError
            raise PipelineError(f"extract_page refused {url}: {exc}") from exc
        return convert_page(page)

    return extract


# -------------------------------------------------------------------------------------------------- embed
def check_vectors(texts: Sequence[str], vectors: Sequence[Sequence[float]], *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[list[float]]:
    """One finite vector of `dimensions` numbers per text, in order; otherwise `PipelineError` (nothing is stored)."""
    if len(vectors) != len(texts):
        raise PipelineError(f"embed returned {len(vectors)} vectors for {len(texts)} texts")
    result: list[list[float]] = []
    for i, vector in enumerate(vectors):
        values = [float(x) for x in vector]
        if len(values) != dimensions:
            raise PipelineError(f"vector {i} has {len(values)} dimensions, expected {dimensions}")
        if not all(math.isfinite(x) for x in values):
            raise PipelineError(f"vector {i} has a value that is not a finite number")
        result.append(values)
    return result


def make_embed(*, embed_sync: Callable[..., Any] | None = None, model_role: str = "embedding", dimensions: int = EMBEDDING_DIMENSIONS) -> Embed:
    """An `Embed` over AI's `embed_sync` (blocking: it runs `asyncio.run`, so call it from synchronous code, not inside a running loop).

    All texts go in one call (AI's local model caches the loaded model between calls). Empty input gives an empty result without a call.
    """
    if embed_sync is None:
        embed_sync = _ai_llm().embed_sync

    def embed(texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = embed_sync(list(texts), model_role=model_role)
        except RuntimeError as exc:                     # asyncio.run() inside a running event loop, among others
            raise PipelineError(f"embed_sync failed: {exc}") from exc
        return check_vectors(texts, vectors, dimensions=dimensions)

    return embed


def embedding_version_from_ai() -> str:
    """The same long form, read from AI's `models.yaml` (role `embedding`). Use it to check `EMBEDDING_VERSION` has not drifted."""
    llm = _ai_llm()
    local = llm.load_config().role("embedding").local
    if local is None:
        raise PipelineError("the embedding role has no pinned local model, so there is no embedding_version")
    return embedding_version(local.repo, local.revision, local.file, local.sha256)


def make_normalise_url() -> NormaliseUrl:
    return normalise_url
