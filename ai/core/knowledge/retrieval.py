"""The retrieval contract (contract A4). Every knowledge lookup goes through here.

    from core.knowledge import retrieve

    passages = await retrieve("influencer disclosure rules", "marketing/strategy", k=5)

`domain` is a SkillSpec domain (`marketing/strategy`) or just its area (`marketing`). A passage
matches when its domain equals the query's or one is a path prefix of the other. The list is
ranked, best first, with at most `k` passages; no match gives `[]`.

The backend is chosen by SKILLFORGE_RETRIEVER: `real` (the default, AI-11: embeddings over the
knowledge index, see core/knowledge/real.py) or `fake` (fixture passages, for tests), or set
directly with `set_retriever()`.
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import ValidationError

from core.knowledge.types import Passage
from core.llm.errors import ConfigError, LLMInputError
from core.spec.models import DOMAIN_AREAS, KEBAB

BACKEND_ENV = "SKILLFORGE_RETRIEVER"
DEFAULT_K = 5
MAX_K = 20
FIXTURES_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "knowledge" / "passages.yaml"
)

_DOMAIN = re.compile(f"^(?:{'|'.join(DOMAIN_AREAS)})(?:/{KEBAB})*$")


class RetrievalInputError(LLMInputError):
    """The caller passed a bad query, domain or k."""


class Retriever(Protocol):
    async def retrieve(self, query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
        """At most `k` passages for `query` in `domain`, best first. No match returns [].

        Raises RetrievalInputError for a blank query, an unknown domain area or k outside 1–20.
        """
        ...


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = _retriever_from_env()
    return _retriever


def set_retriever(retriever: Retriever | None) -> Retriever | None:
    """Install a retriever and return the previous one. None means: rebuild from env on next use."""
    global _retriever
    previous, _retriever = _retriever, retriever
    return previous


def _retriever_from_env() -> Retriever:
    backend = os.environ.get(BACKEND_ENV, "real").strip().lower()
    if backend == "real":
        from core.knowledge.real import RealRetriever

        return RealRetriever()
    if backend == "fake":
        return FakeRetriever()
    raise ConfigError(f"unknown {BACKEND_ENV}={backend!r}; use 'real' or 'fake'")


def check_request(query: str, domain: str, k: int) -> None:
    """Shared `retrieve` input rules, for every backend."""
    if not query.strip():
        raise RetrievalInputError("query is empty")
    check_domain(domain)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise RetrievalInputError(f"k must be an integer from 1 to {MAX_K}, got {k!r}")


def check_domain(domain: str) -> None:
    if not isinstance(domain, str) or not _DOMAIN.match(domain):
        raise RetrievalInputError(
            f"domain {domain!r} is not <area> or <area>/<sub-area> with a known area"
        )


def domains_match(a: str, b: str) -> bool:
    """Equal, or one is a path prefix of the other: `technology` matches `technology/ai`."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


async def retrieve(query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
    return await get_retriever().retrieve(query, domain, k)


def retrieve_sync(query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
    """Blocking `retrieve` for scripts. In notebooks and async code, `await retrieve(...)`."""
    return asyncio.run(retrieve(query, domain, k))


# ------------------------------------------------------------------ FakeRetriever

_STOP_WORDS = frozenset(
    re.findall(
        r"\w+",
        "a an and are as at be by can do does for from has have how i in is it its of on or our "
        "should so than that the their them then there these they this to was we what when which "
        "who why will with you your",
    )
)


def _terms(text: str) -> set[str]:
    # Lowercase words minus stop words, with a plural "s" dropped so "rules" meets "rule".
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words} - _STOP_WORDS


def rank_by_overlap(query: str, passages: list[Passage]) -> list[Passage]:
    """The fake's ranking: word overlap with title and text, ties by chunk_id. Also the
    baseline the AI-11 recall report compares embeddings against."""
    wanted = _terms(query)
    return sorted(
        passages, key=lambda p: (-len(wanted & _terms(f"{p.title} {p.text}")), p.chunk_id)
    )


@dataclass(frozen=True)
class FixtureEntry:
    domain: str
    passage: Passage


@dataclass(frozen=True)
class RetrievalCall:
    query: str
    domain: str
    k: int


@dataclass
class FakeRetriever:
    """A network-free Retriever over fixture passages, for tests and for coding against A4.

    Ranking is word overlap between the query and each passage's title and text, ties broken
    by chunk_id, so results are deterministic. Passages in the domain with no overlap still
    follow the scored ones, so `k` results come back when the domain has that many, as with
    vector search.
    """

    path: Path = FIXTURES_PATH
    entries: list[FixtureEntry] = field(init=False)
    calls: list[RetrievalCall] = field(default_factory=list, init=False)
    _index: dict[str, set[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.entries = load_fixtures(self.path)
        self._index = {
            e.passage.chunk_id: _terms(f"{e.passage.title} {e.passage.text}") for e in self.entries
        }

    async def retrieve(self, query: str, domain: str, k: int = DEFAULT_K) -> list[Passage]:
        check_request(query, domain, k)
        self.calls.append(RetrievalCall(query, domain, k))
        wanted = _terms(query)
        matches = [e.passage for e in self.entries if domains_match(e.domain, domain)]
        matches.sort(key=lambda p: (-len(wanted & self._index[p.chunk_id]), p.chunk_id))
        return matches[:k]


def load_fixtures(path: Path = FIXTURES_PATH) -> list[FixtureEntry]:
    """Read and validate a fixture file: `passages`, each a Passage plus its `domain`."""
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read retrieval fixtures {path}: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("passages"), list):
        raise ConfigError(f"{path}: expected a mapping with a 'passages' list")
    entries: list[FixtureEntry] = []
    seen: set[str] = set()
    for i, raw in enumerate(data["passages"]):
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: passages[{i}] is not a mapping")
        raw = dict(raw)
        domain = raw.pop("domain", None)
        if not isinstance(domain, str) or not _DOMAIN.match(domain):
            raise ConfigError(f"{path}: passages[{i}].domain is missing or not a known domain")
        try:
            # JSON mode, like core/llm/fake.py: YAML dates become ISO strings for strict mode.
            passage = Passage.model_validate_json(json.dumps(raw, default=str))
        except ValidationError as exc:
            fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
            raise ConfigError(f"{path}: passages[{i}] is invalid at {fields}") from exc
        if passage.chunk_id in seen:
            raise ConfigError(f"{path}: chunk_id {passage.chunk_id!r} is listed twice")
        seen.add(passage.chunk_id)
        entries.append(FixtureEntry(domain, passage))
    return entries
