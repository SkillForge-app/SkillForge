"""Calibrate the reference writer's support threshold (AI-13) on the fixture passages only.

    python -m evaluation.architect calibrate-support     # the local bge-small model, no API cost

Pairs, from tests/fixtures/knowledge/passages.yaml (never from seed results):
- positive: each sentence of a passage (6+ words) against its own passage;
- negative: the same sentence against the most similar passage of ANOTHER page in the SAME
  domain: a near miss, the hard case.
The threshold is the score with the best F1 between the two (ties: the lower threshold, so
fewer genuine claims are flagged), rounded to 2 decimals.

Known limit: a sentence taken from the passage itself scores higher than a fair paraphrase
would, so the threshold may flag some paraphrased claims. The 10-claim human spot-check in each
seed report covers that; a gate is set only after the first live run.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agents.writers.support import Embed, cosine, default_embed
from core.knowledge.retrieval import FIXTURES_PATH, FixtureEntry, load_fixtures

MIN_WORDS = 6
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    """The passage's sentences with at least MIN_WORDS words."""
    parts = [" ".join(s.split()) for s in _SENTENCE.split(" ".join(text.split()))]
    return [s for s in parts if len(s.split()) >= MIN_WORDS]


@dataclass(frozen=True)
class Pair:
    sentence: str
    chunk_id: str  # the passage the sentence comes from
    other_id: str | None  # the negative's passage (None: no other page in the domain)
    positive: float
    negative: float | None


def best_f1(positives: Sequence[float], negatives: Sequence[float]) -> dict[str, float]:
    """The threshold t (score >= t counts as supported) with the best F1; ties: the lower t."""
    best: dict[str, float] = {"threshold": 0.0, "precision": 0.0, "recall": 0.0, "f1": -1.0}
    for t in sorted({round(s, 2) for s in (*positives, *negatives)}):
        tp = sum(p >= t for p in positives)
        fp = sum(n >= t for n in negatives)
        fn = len(positives) - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best["f1"]:
            best = {"threshold": t, "precision": precision, "recall": recall, "f1": f1}
    return {k: round(v, 4) for k, v in best.items()}


async def calibration_pairs(
    entries: Sequence[FixtureEntry], *, embed_fn: Embed = default_embed
) -> list[Pair]:
    """Every (sentence, own passage) pair, with its hardest same-domain other-page negative."""
    items = [(e, s) for e in entries for s in sentences(e.passage.text)]
    texts = list(dict.fromkeys([e.passage.text for e in entries] + [s for _, s in items]))
    vectors = dict(zip(texts, await embed_fn(texts), strict=True))
    pairs = []
    for entry, sentence in items:
        own = entry.passage
        others = [
            e.passage
            for e in entries
            if e.domain == entry.domain and str(e.passage.source_url) != str(own.source_url)
        ]
        scored = [(cosine(vectors[sentence], vectors[o.text]), o.chunk_id) for o in others]
        hardest = max(scored, default=None)
        pairs.append(
            Pair(
                sentence=sentence,
                chunk_id=own.chunk_id,
                other_id=hardest[1] if hardest else None,
                positive=round(cosine(vectors[sentence], vectors[own.text]), 4),
                negative=round(hardest[0], 4) if hardest else None,
            )
        )
    return pairs


def _spread(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}
    return {
        "min": ordered[0],
        "p10": ordered[len(ordered) // 10],
        "median": ordered[len(ordered) // 2],
        "max": ordered[-1],
    }


@dataclass
class Calibration:
    created: str
    model: str
    fixtures: str
    pairs: int
    negatives: int
    threshold: float
    precision: float
    recall: float
    f1: float
    positive_scores: dict[str, float] = field(default_factory=dict)
    negative_scores: dict[str, float] = field(default_factory=dict)
    method: str = (
        "positive: a passage sentence (6+ words) vs its own passage; negative: the same sentence "
        "vs the most similar passage of another page in the same domain; threshold: best F1 "
        "(ties: the lower), rounded to 2 decimals. Fixture passages only, never seed results."
    )
    limit: str = (
        "A sentence taken from the passage scores higher than a fair paraphrase, so the threshold "
        "may flag some paraphrased claims; the seed reports' 10-claim human spot-check covers it."
    )


async def calibrate(
    *, path: Path = FIXTURES_PATH, embed_fn: Embed = default_embed, model: str = "n/a"
) -> Calibration:
    entries = load_fixtures(path)
    pairs = await calibration_pairs(entries, embed_fn=embed_fn)
    positives = [p.positive for p in pairs]
    negatives = [p.negative for p in pairs if p.negative is not None]
    best = best_f1(positives, negatives)
    import yaml

    version = yaml.safe_load(path.read_text(encoding="utf-8")).get("version", "n/a")
    return Calibration(
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=model,
        fixtures=f"passages.yaml {version}",
        pairs=len(pairs),
        negatives=len(negatives),
        threshold=best["threshold"],
        precision=best["precision"],
        recall=best["recall"],
        f1=best["f1"],
        positive_scores=_spread(positives),
        negative_scores=_spread(negatives),
    )


def render(c: Calibration) -> str:
    return "\n".join(
        [
            f"# Support threshold calibration (AI-13), {c.created}",
            "",
            f"**Threshold: {c.threshold:.2f}** (a claim below it is flagged *weakly supported*).",
            "",
            f"- Model: `{c.model}` (local, no API cost). Data: {c.fixtures} "
            f"({c.pairs} positive pairs, {c.negatives} negative pairs).",
            f"- At the threshold: precision {c.precision:.2%}, recall {c.recall:.2%}, "
            f"F1 {c.f1:.3f}.",
            f"- Positive scores: {c.positive_scores}.",
            f"- Negative scores: {c.negative_scores}.",
            "",
            f"**Method.** {c.method}",
            "",
            f"**Known limit.** {c.limit}",
            "",
        ]
    )


def write(c: Calibration, reports_dir: Path) -> tuple[Path, Path]:
    """reports_dir/support-calibration-<date>[-n].md/.json, never overwriting an earlier one."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    base, n = f"support-calibration-{c.created[:10]}", 1
    while (reports_dir / f"{base}{'' if n == 1 else f'-{n}'}.md").exists():
        n += 1
    stem = f"{base}{'' if n == 1 else f'-{n}'}"
    md, js = reports_dir / f"{stem}.md", reports_dir / f"{stem}.json"
    md.write_text(render(c), encoding="utf-8", newline="\n")
    js.write_text(json.dumps(asdict(c), indent=2) + "\n", encoding="utf-8", newline="\n")
    return md, js


def as_dict(c: Calibration) -> dict[str, Any]:
    return asdict(c)


__all__ = ["Calibration", "Pair", "best_f1", "calibrate", "calibration_pairs", "sentences", "write"]
