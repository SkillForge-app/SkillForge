"""Support check for reference claims (AI-13): "cited" is not the same as "supported".

Each kept claim and the chunks it cites are embedded with the local embedding model (role
`embedding`: bge-small, no API cost). A claim's support is its best cosine similarity to its
cited chunks; below SUPPORT_THRESHOLD it is flagged *weakly supported*. Flagged claims are kept
and counted, never dropped, and nothing gates on them yet (a gate is set after the first live run).

SUPPORT_THRESHOLD was chosen once, on the fixture passages only, never on seed results:
`python -m evaluation.architect calibrate-support` (evaluation/architect/support.py), report
evaluation/architect/reports/support-calibration-2026-11-21.md, fixture passages.yaml 1.1.0.
"""

import dataclasses
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from core.knowledge import Passage
from core.llm import embed

if TYPE_CHECKING:
    from core.agents.writers.references import ReferenceFile

# From evaluation/architect/reports/support-calibration-2026-11-21.md (best F1 on the fixture
# passages 1.1.0: sentence vs its own passage, against the nearest passage of another page).
SUPPORT_THRESHOLD = 0.67
EMBED_BATCH = 64

Embed = Callable[[Sequence[str]], Awaitable[list[list[float]]]]


async def default_embed(texts: Sequence[str]) -> list[list[float]]:
    """The gateway's embedding role (the local bge-small model; the fake in tests)."""
    out: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        out += await embed(list(texts[start : start + EMBED_BATCH]))
    return out


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def support_scores(
    pairs: Sequence[tuple[str, Sequence[str]]], *, embed_fn: Embed = default_embed
) -> list[float]:
    """For each (claim text, cited texts), the best cosine similarity of the claim to them."""
    texts = list(dict.fromkeys([t for claim, cited in pairs for t in (claim, *cited)]))
    vectors = dict(zip(texts, await embed_fn(texts), strict=True)) if texts else {}
    return [
        max((cosine(vectors[claim], vectors[c]) for c in cited), default=0.0)
        for claim, cited in pairs
    ]


async def check_support(
    files: Sequence["ReferenceFile"],
    passages: Sequence[Passage],
    *,
    threshold: float | None = None,
    embed_fn: Embed = default_embed,
) -> list["ReferenceFile"]:
    """The files with each claim's `support` set and `weak` flagged below the threshold."""
    limit = SUPPORT_THRESHOLD if threshold is None else threshold
    by_chunk = {p.chunk_id: p.text for p in passages}
    claims = [c for f in files for c in f.claims]
    scores = await support_scores(
        [(c.text, [by_chunk[i] for i in c.chunk_ids if i in by_chunk]) for c in claims],
        embed_fn=embed_fn,
    )
    scored = iter(scores)
    out = []
    for f in files:
        new = []
        for c in f.claims:
            score = round(next(scored), 4)
            new.append(dataclasses.replace(c, support=score, weak=score < limit))
        out.append(dataclasses.replace(f, claims=tuple(new)))
    return out


__all__ = ["SUPPORT_THRESHOLD", "Embed", "check_support", "cosine", "support_scores"]
