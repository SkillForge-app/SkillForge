"""Test requests for the Skill Architect.

AI-07 (done-when: >= 90% valid specs), the 103 requests of `all`:
- the 3 example AnalyzedRequests in ai/examples/analyzed-request/
- the 100 analyzer gate requests, turned into AnalyzedRequests straight from their labels, so
  the score measures the Architect alone (not analyzer mistakes). Vague requests become
  "questions skipped" requests: the Architect must still design something sensible.

AI-12 (done-when: "seed skills generated with sources"), the 10 requests of `seed`: the clear
request (`req-1`) of each seed-benchmark skill, from the release the analyzer gate uses, built
from its labels the same way.
"""

import re
from dataclasses import dataclass

from core.analysis import AnalyzedRequest
from core.analysis.types import AnalyzerInfo, SafetyClearance, SafetyCondition
from core.spec import HIGH_RISK_AREAS
from evaluation.analyzer import data as analyzer_data
from evaluation.common import AI_ROOT

EXAMPLES_DIR = AI_ROOT / "examples" / "analyzed-request"
GATE_SIZE = 103
SEED_SET_SIZE = 10
LABELS = AnalyzerInfo(prompt_id="labels", prompt_version=1)


@dataclass(frozen=True)
class ArchitectItem:
    id: str
    source: str  # "example" or "gate"
    text: str  # the original request text (for --end-to-end)
    analyzed: AnalyzedRequest


def _first_sentence(text: str, limit: int = 200) -> str:
    sentence = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def from_labels(item: analyzer_data.EvalItem) -> AnalyzedRequest:
    """An AnalyzedRequest built from labels, with the clearance the safety rules imply."""
    area = item.domain.split("/", 1)[0]
    conditions: list[SafetyCondition] = (
        ["professional_disclaimer"] if area in HIGH_RISK_AREAS else []
    )
    return AnalyzedRequest.model_validate(
        {
            "request": item.text,
            "kind": item.kind,
            "domain": item.domain,
            "risk": item.risk,
            "summary": _first_sentence(item.text),
            "needs_clarification": False,
            "targets": list(item.mentioned_targets or ()),
            "analyzer": LABELS,
            "safety": SafetyClearance(conditions=conditions, prompt_version=1),
        }
    )


def example_items() -> list[ArchitectItem]:
    items = []
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        analyzed = AnalyzedRequest.model_validate_json(path.read_text(encoding="utf-8"))
        items.append(ArchitectItem(f"example:{path.stem}", "example", analyzed.request, analyzed))
    return items


def gate_items() -> list[ArchitectItem]:
    return [
        ArchitectItem(f"gate:{i.id}", "gate", i.text, from_labels(i))
        for i in analyzer_data.load_set("gate")
    ]


def seed_items() -> list[ArchitectItem]:
    """One clear request per seed-benchmark skill (its `req-1`)."""
    return [
        ArchitectItem(f"seed:{i.id}", "seed", i.text, from_labels(i))
        for i in analyzer_data.seed_requests()
        if i.id.endswith("/req-1")
    ]


def load_items(name: str) -> list[ArchitectItem]:
    if name == "examples":
        return example_items()
    if name == "gate":
        return gate_items()
    if name == "seed":
        return seed_items()
    return example_items() + gate_items()


def sources() -> list[dict[str, str]]:
    return [
        {"name": s.name, "version": s.version, "sha256": s.sha256} for s in analyzer_data.sources()
    ] + [{"name": "analyzed-request-examples", "version": "n/a", "sha256": _examples_hash()}]


def _examples_hash() -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


__all__ = [
    "GATE_SIZE",
    "SEED_SET_SIZE",
    "ArchitectItem",
    "from_labels",
    "load_items",
    "seed_items",
    "sources",
]
