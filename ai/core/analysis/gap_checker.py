"""Gap Checker (AI-08): does a good skill for this request already exist?

    result = await check_gap(analyzed, indexes=[registry, corpus], k=5)
    result.verdict    # exists | similar | new   (FE-09: use it / customize it / generate new)
    result.matches    # GapMatch list, best first: the skill card and its cosine score

The request and every skill become one short text each (request_text / skill_text), embedded
with the `embedding` role (the local bge-small of AI-11). The top score decides the verdict
against two thresholds tuned on a labelled set (gap_checker.yaml, see docs/ai/gap-checker.md).

A SkillIndex is where the skills live: the SkillForge registry (BE-11) and the public SKILL.md
corpus (DE-08) will implement it; FixtureSkillIndex is the fake, backed by a YAML file.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

import numpy as np
import yaml
from pydantic import Field, HttpUrl, StringConstraints, ValidationError, model_validator

from core.analysis.types import AnalyzedRequest
from core.llm import embed, load_config
from core.llm.config import ModelConfig
from core.llm.errors import ConfigError
from core.llm.gateway import EMBEDDING_ROLE
from core.spec.models import Domain, Kind, Line, SkillName, SkillSpec, SpecModel, Title
from core.spec.validator import load_spec

AI_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = Path(__file__).with_name("gap_checker.yaml")
DEFAULT_K = 5
MAX_K = 20

Verdict = Literal["exists", "similar", "new"]
SkillSource = Literal["registry", "corpus"]
RequestVariant = Literal["summary", "structured"]
CardId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:/-]{1,127}$")]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class SkillCard(SpecModel):
    """What the gap checker knows about one existing skill. Built from a SkillSpec for the
    registry (from_spec), or from a SKILL.md's metadata for the public corpus."""

    id: CardId = Field(description="Unique across all indexes, e.g. registry:review-nda.")
    name: SkillName
    title: Title
    description: Description = Field(description="What the skill makes the agent do.")
    kind: Kind
    domain: Domain
    use_when: list[Line] = Field(default_factory=list, max_length=10)
    source: SkillSource
    url: HttpUrl | None = None  # corpus cards: where the SKILL.md was found
    licence: str | None = None  # corpus cards: only permissively licensed skills (DE-08)

    @classmethod
    def from_spec(cls, spec: SkillSpec, *, source: SkillSource = "registry") -> "SkillCard":
        skill = spec.skill
        return cls(
            id=f"{source}:{skill.name}",
            name=skill.name,
            title=skill.title,
            description=skill.summary,
            kind=skill.kind,
            domain=skill.domain,
            use_when=list(spec.triggers.use_when),
            source=source,
        )


def domain_words(domain: str) -> str:
    return domain.replace("/", " ").replace("-", " ")


def skill_text(card: SkillCard) -> str:
    """What a skill says it does and when to load it. `avoid_when` is never part of it: it
    describes exactly the near-misses, so it would make them look more similar."""
    text = f"{card.title}. A {card.kind} skill for {domain_words(card.domain)}. {card.description}"
    if card.use_when:
        text += " Use when: " + "; ".join(card.use_when) + "."
    return text


def request_text(analyzed: AnalyzedRequest, variant: RequestVariant = "structured") -> str:
    """The analyzer's English one-sentence summary (it already folds in the clarification
    answers), optionally with what kind of skill, for which domain, making which outputs. The
    raw request text, audience and targets are left out: noise for this question."""
    if variant == "summary":
        return analyzed.summary
    text = f"A {analyzed.kind} skill for {domain_words(analyzed.domain)}. {analyzed.summary}"
    if analyzed.expected_outputs:
        text += " Outputs: " + ", ".join(analyzed.expected_outputs) + "."
    return text


class GapSettings(SpecModel):
    """The tuned choices (gap_checker.yaml). Re-tuning is a data change with its report."""

    version: str
    request_text: RequestVariant
    query_prefix: bool  # put the embedding role's query prefix before the request text
    same_area_for_exists: bool  # `exists` also needs the same domain area as the request
    exists: float = Field(ge=-1, le=1)  # top score at or above: the skill exists
    similar: float = Field(ge=-1, le=1)  # at or above (and below `exists`): customize it
    tuned_on: str  # the report that set these values

    @model_validator(mode="after")
    def _ordered(self) -> "GapSettings":
        if self.similar >= self.exists:
            raise ValueError("the `similar` threshold must be below the `exists` threshold")
        return self


@lru_cache(maxsize=4)
def load_settings(path: Path = SETTINGS_PATH) -> GapSettings:
    try:
        return GapSettings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid: {exc.error_count()} errors") from exc


class GapMatch(SpecModel):
    skill: SkillCard
    score: float  # cosine similarity, -1 to 1


class GapCheck(SpecModel):
    verdict: Verdict
    matches: list[GapMatch]  # best first, at most k
    exists_threshold: float
    similar_threshold: float
    model: str  # the embedding model the scores come from
    settings_version: str


@dataclass(frozen=True)
class IndexInfo:
    count: int
    model: str | None  # the embedding model the index was built with; None while empty
    dimensions: int | None


class SkillIndex(Protocol):
    def info(self) -> IndexInfo: ...

    async def search(self, vector: Sequence[float], k: int) -> list[tuple[SkillCard, float]]:
        """At most `k` skills by cosine similarity to `vector`, best first (ties by id). The
        index embeds skill_text(card) with the same model as the request."""
        ...


def _unit(vectors: Any) -> Any:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _rank(scored: list[tuple[SkillCard, float]], k: int) -> list[tuple[SkillCard, float]]:
    return sorted(scored, key=lambda pair: (-round(pair[1], 6), pair[0].id))[:k]


class FixtureSkillIndex:
    """The fake index: cards from a YAML file, embedded on first search with `embed()`.

    The file holds `cards:`, each either a card or `{spec: <path from ai/>, source: ...}` to
    build one from a SkillSpec file (SkillCard.from_spec)."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        cards: Sequence[SkillCard] | None = None,
        model_role: str = EMBEDDING_ROLE,
        model_config: ModelConfig | None = None,
    ) -> None:
        """Cards from the YAML file at `path`, or the given `cards` (e.g. one source's)."""
        if (path is None) == (cards is None):
            raise ValueError("give either a path or cards")
        self.path = path
        self.model_role = model_role
        self._model_config = model_config
        self.cards = list(cards) if cards is not None else load_cards(path)  # type: ignore[arg-type]
        self._vectors: Any = None
        self._lock = asyncio.Lock()

    def info(self) -> IndexInfo:
        role = (self._model_config or load_config()).role(self.model_role)
        if not self.cards:
            return IndexInfo(0, None, None)
        return IndexInfo(len(self.cards), role.model, role.dimensions)

    async def search(self, vector: Sequence[float], k: int) -> list[tuple[SkillCard, float]]:
        if not self.cards:
            return []
        async with self._lock:
            if self._vectors is None:
                texts = [skill_text(card) for card in self.cards]
                self._vectors = _unit(await embed(texts, model_role=self.model_role))
        scores = self._vectors @ _unit(vector)
        return _rank(list(zip(self.cards, scores.tolist(), strict=True)), k)


def load_cards(path: Path) -> list[SkillCard]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cards = []
    for entry in data.get("cards", []):
        if "spec" in entry:
            spec = load_spec(AI_ROOT / entry["spec"])
            cards.append(SkillCard.from_spec(spec, source=entry.get("source", "registry")))
        else:
            cards.append(SkillCard.model_validate(entry))
    ids = [card.id for card in cards]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"{path}: card ids must be unique")
    return cards


async def check_gap(
    analyzed: AnalyzedRequest,
    *,
    indexes: Sequence[SkillIndex],
    k: int = DEFAULT_K,
    settings: GapSettings | None = None,
    model_role: str = EMBEDDING_ROLE,
    model_config: ModelConfig | None = None,
) -> GapCheck:
    """Rank existing skills for `analyzed` and decide exists / similar / new. Run it after
    clarification: a vague request gives a vague summary and weak matches."""
    if not 1 <= k <= MAX_K:
        raise ValueError(f"k must be 1 to {MAX_K}, not {k}")
    settings = settings or load_settings()
    role = (model_config or load_config()).role(model_role)
    for index in indexes:
        info = index.info()
        if info.count and (info.model != role.model or info.dimensions != role.dimensions):
            raise ConfigError(
                f"a skill index holds {info.dimensions}-dimension vectors from {info.model}, "
                f"not {role.dimensions}-dimension vectors from {role.model}; rebuild it"
            )
    text = request_text(analyzed, settings.request_text)
    if settings.query_prefix:
        text = role.query_prefix + text
    [vector] = await embed([text], model_role=model_role)
    best: dict[str, tuple[SkillCard, float]] = {}
    for index in indexes:
        for card, score in await index.search(vector, k):
            if card.id not in best or score > best[card.id][1]:
                best[card.id] = (card, score)
    ranked = _rank(list(best.values()), k)
    return GapCheck(
        verdict=decide(analyzed, ranked[0] if ranked else None, settings),
        matches=[GapMatch(skill=card, score=round(score, 6)) for card, score in ranked],
        exists_threshold=settings.exists,
        similar_threshold=settings.similar,
        model=role.model,
        settings_version=settings.version,
    )


def decide(
    analyzed: AnalyzedRequest, top: tuple[SkillCard, float] | None, settings: GapSettings
) -> Verdict:
    """The verdict from the best match alone."""
    if top is None:
        return "new"
    card, score = top
    same_area = card.domain.split("/", 1)[0] == analyzed.domain_area
    if score >= settings.exists and (same_area or not settings.same_area_for_exists):
        return "exists"
    if score >= settings.similar:
        return "similar"
    return "new"
