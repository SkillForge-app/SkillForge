"""The Gap Checker's labelled requests (AI-08): loading, labels and the data checks.

Each request carries the gold analysis (what the Request Analyzer would produce) and pair
labels: `match` and `near_miss` card ids; every other (request, card) pair is no_match.
See evaluation/gap/LABELLING.md.
"""

import datetime as dt
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, StringConstraints, model_validator

from core.analysis import AnalyzedRequest, AnalyzerInfo, SkillCard
from core.analysis.gap_checker import CardId, Verdict, load_cards
from core.analysis.types import RequestText
from core.spec import HIGH_RISK_AREAS
from core.spec.models import Domain, Kind, Line, SkillName, SpecModel
from evaluation.common import AI_ROOT

DATA_DIR = AI_ROOT / "evaluation" / "gap"
CARDS_PATH = AI_ROOT / "tests" / "fixtures" / "gap" / "skills.yaml"
SPLITS = ("dev", "test")
GOLD_ANALYZER = AnalyzerInfo(prompt_id="gold-labels", prompt_version=1)

Label = Literal["match", "near_miss", "no_match"]
LABEL_VERDICT: dict[Label, Verdict] = {"match": "exists", "near_miss": "similar", "no_match": "new"}


class GoldAnalysis(SpecModel):
    kind: Kind
    domain: Domain
    skill_name: SkillName | None = None
    summary: Line
    expected_outputs: list[Line] = Field(default_factory=list, max_length=10)


class LabelledRequest(SpecModel):
    id: Annotated[str, StringConstraints(pattern=r"^g[dt]-\d{2}$")]
    text: RequestText
    style: Literal["clear", "vague", "detailed"]
    language: Literal["en", "ar"]
    analysis: GoldAnalysis
    match: list[CardId] = Field(default_factory=list)
    near_miss: list[CardId] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _labels(self) -> "LabelledRequest":
        both = set(self.match) & set(self.near_miss)
        if both:
            raise ValueError(f"{self.id}: {sorted(both)} is both match and near_miss")
        for ids in (self.match, self.near_miss):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{self.id}: a card is listed twice")
        return self

    def label(self, card_id: str) -> Label:
        if card_id in self.match:
            return "match"
        if card_id in self.near_miss:
            return "near_miss"
        return "no_match"

    @property
    def best_label(self) -> Label:
        return "match" if self.match else "near_miss" if self.near_miss else "no_match"

    def analyzed(self) -> AnalyzedRequest:
        """The gold analysis as an AnalyzedRequest, so the numbers measure the gap checker
        alone (the analyzer has its own evaluation, AI-05)."""
        a = self.analysis
        area = a.domain.split("/", 1)[0]
        return AnalyzedRequest(
            request=self.text,
            kind=a.kind,
            domain=a.domain,
            risk="high" if area in HIGH_RISK_AREAS else "low",
            expected_outputs=a.expected_outputs,
            skill_name=a.skill_name,
            summary=a.summary,
            needs_clarification=False,
            analyzer=GOLD_ANALYZER,
        )


class Review(SpecModel):
    status: Literal["draft", "reviewed"]
    reviewer: str | None = None
    date: dt.date | None = None


class PairSet(SpecModel):
    name: str
    version: str
    split: Literal["dev", "test"]
    review: Review
    requests: list[LabelledRequest]


def load_pairs(split: str, data_dir: Path = DATA_DIR) -> PairSet:
    path = data_dir / f"pairs-{split}.yaml"
    return PairSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_fixture_cards(path: Path = CARDS_PATH) -> list[SkillCard]:
    return load_cards(path)


def check_data(cards: list[SkillCard], sets: list[PairSet]) -> list[str]:
    """Problems that make the labelled set unusable; [] when it is fine."""
    problems: list[str] = []
    known = {card.id for card in cards}
    seen: dict[str, str] = {}
    texts: dict[str, str] = {}
    for pair_set in sets:
        labels = {r.best_label for r in pair_set.requests}
        missing = {"match", "near_miss", "no_match"} - labels
        if missing:
            problems.append(f"{pair_set.split}: no request is {sorted(missing)}")
        for r in pair_set.requests:
            if not r.id.startswith("gd-" if pair_set.split == "dev" else "gt-"):
                problems.append(f"{r.id}: id prefix does not match the {pair_set.split} split")
            if r.id in seen:
                problems.append(f"{r.id}: in {seen[r.id]} and {pair_set.split}")
            seen[r.id] = pair_set.split
            key = " ".join(r.text.lower().split())
            if key in texts and texts[key] != pair_set.split:
                problems.append(f"{r.id}: the same text is in dev and test")
            texts[key] = pair_set.split
            for card_id in (*r.match, *r.near_miss):
                if card_id not in known:
                    problems.append(f"{r.id}: unknown card {card_id}")
            try:
                r.analyzed()
            except ValueError as exc:
                problems.append(f"{r.id}: gold analysis is not a valid AnalyzedRequest: {exc}")
    return problems
