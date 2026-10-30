"""Scoring and metrics for the Gap Checker (AI-08).

Pair level (the done-when number): a (request, card) pair is predicted `exists` when its score
is at or above the `exists` threshold (and, with the area gate, the card is in the request's
domain area); precision and recall are against the `match` labels. `related` is the same with
the `similar` threshold against match or near_miss. Request level: the verdict check_gap gives
from the top-scored card, against the request's best label.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.analysis import GapSettings, SkillCard, request_text, skill_text
from core.analysis.gap_checker import RequestVariant, Verdict, _unit, decide
from core.llm import embed, load_config
from core.llm.gateway import EMBEDDING_ROLE
from evaluation.gap.data import LABEL_VERDICT, Label, LabelledRequest

EXISTS_BETA = 0.5  # precision-first: a wrong "this already exists" turns the user away
RELATED_BETA = 1.0

# At most four variants are compared on dev, to keep tuning from fitting the dev set.
VARIANTS: dict[str, dict[str, Any]] = {
    "summary": {"request_text": "summary", "query_prefix": False, "same_area_for_exists": False},
    "structured": {
        "request_text": "structured",
        "query_prefix": False,
        "same_area_for_exists": False,
    },
    "structured+prefix": {
        "request_text": "structured",
        "query_prefix": True,
        "same_area_for_exists": False,
    },
    "structured+area-gate": {
        "request_text": "structured",
        "query_prefix": False,
        "same_area_for_exists": True,
    },
}


@dataclass(frozen=True)
class Counts:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    def f_beta(self, beta: float) -> float:
        p, r = self.precision, self.recall
        return (1 + beta**2) * p * r / (beta**2 * p + r) if p + r else 0.0


@dataclass
class ScoreTable:
    """Cosine scores of every (request, card) pair, rows in request order."""

    requests: list[LabelledRequest]
    cards: list[SkillCard]
    scores: Any  # numpy (requests x cards)
    gold: dict[Label, Any] = field(init=False)  # boolean masks per label
    same_area: Any = field(init=False)

    def __post_init__(self) -> None:
        labels = np.array([[r.label(c.id) for c in self.cards] for r in self.requests])
        self.gold = {name: labels == name for name in ("match", "near_miss", "no_match")}
        areas = [c.domain.split("/", 1)[0] for c in self.cards]
        self.same_area = np.array(
            [[r.analysis.domain.split("/", 1)[0] == a for a in areas] for r in self.requests]
        )


async def card_vectors(cards: Sequence[SkillCard], *, model_role: str = EMBEDDING_ROLE) -> Any:
    return _unit(await embed([skill_text(c) for c in cards], model_role=model_role))


async def score_table(
    requests: list[LabelledRequest],
    cards: list[SkillCard],
    vectors: Any,
    *,
    variant: RequestVariant,
    query_prefix: bool,
    model_role: str = EMBEDDING_ROLE,
) -> ScoreTable:
    prefix = load_config().role(model_role).query_prefix if query_prefix else ""
    texts = [prefix + request_text(r.analyzed(), variant) for r in requests]
    request_vectors = _unit(await embed(texts, model_role=model_role))
    return ScoreTable(requests, cards, np.round(request_vectors @ vectors.T, 6))


def pair_counts(
    table: ScoreTable, threshold: float, *, positive: Sequence[Label], area_gate: bool = False
) -> Counts:
    predicted = table.scores >= threshold
    if area_gate:
        predicted &= table.same_area
    gold = np.zeros_like(predicted)
    for label in positive:
        gold |= table.gold[label]
    tp = int((predicted & gold).sum())
    return Counts(tp=tp, fp=int((predicted & ~gold).sum()), fn=int((~predicted & gold).sum()))


def best_threshold(
    table: ScoreTable,
    *,
    positive: Sequence[Label],
    beta: float,
    area_gate: bool = False,
    below: float | None = None,
) -> tuple[float, Counts]:
    """The threshold with the best F-beta on this table; ties go to the higher threshold."""
    candidates = sorted({round(float(s), 4) for s in table.scores.ravel()}, reverse=True)
    if below is not None:
        candidates = [t for t in candidates if t < below]
    best: tuple[float, float, Counts] | None = None
    for t in candidates:
        counts = pair_counts(table, t, positive=positive, area_gate=area_gate)
        score = counts.f_beta(beta)
        if best is None or score > best[0]:
            best = (score, t, counts)
    if best is None:
        raise ValueError("no candidate threshold")
    return best[1], best[2]


@dataclass(frozen=True)
class RequestOutcome:
    request: LabelledRequest
    top: SkillCard
    top_score: float
    verdict: Verdict
    gold: Verdict

    @property
    def correct(self) -> bool:
        if self.verdict != self.gold:
            return False
        return self.verdict != "exists" or self.top.id in self.request.match


def request_outcomes(table: ScoreTable, settings: GapSettings) -> list[RequestOutcome]:
    outcomes = []
    for i, r in enumerate(table.requests):
        row = table.scores[i]
        j = min(range(len(table.cards)), key=lambda c: (-row[c], table.cards[c].id))
        card, score = table.cards[j], float(row[j])
        outcomes.append(
            RequestOutcome(
                request=r,
                top=card,
                top_score=score,
                verdict=decide(r.analyzed(), (card, score), settings),
                gold=LABEL_VERDICT[r.best_label],
            )
        )
    return outcomes


def confusion(outcomes: Sequence[RequestOutcome]) -> dict[str, dict[str, int]]:
    verdicts = ("exists", "similar", "new")
    table = {gold: dict.fromkeys(verdicts, 0) for gold in verdicts}
    for o in outcomes:
        table[o.gold][o.verdict] += 1
    return table
