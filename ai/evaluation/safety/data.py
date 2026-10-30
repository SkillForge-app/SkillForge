"""Safety test sets (AI-06): red-team (must be blocked) and benign (must be allowed).

A file with `status: incomplete` is not finished yet: its coverage gaps are reported as
warnings and the AI-06 gate cannot pass. Once its status is `draft` or `reviewed`, every gap
is an error. Rules: LABELLING.md.
"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import Field, ValidationError, model_validator

from core.analysis.types import HARM_CATEGORIES, HarmCategory, SafetyCondition
from core.spec import Issue, schema_issues
from core.spec.models import Id, Line, SpecModel, Text
from core.spec.validator import IssueSeverity
from evaluation.analyzer import data as analyzer_data

SAFETY_DIR = Path(__file__).resolve().parent
FILES: dict[str, Path] = {
    "redteam": SAFETY_DIR / "redteam.yaml",
    "benign": SAFETY_DIR / "benign-tricky.yaml",
    "dev": SAFETY_DIR / "safety-dev.yaml",
}
SetName = Literal["redteam", "benign", "dev", "normal"]
AttackStyle = Literal[
    "direct",
    "euphemism",
    "fiction_wrapper",
    "education_wrapper",
    "authority_claim",
    "prompt_injection",
    "two_turn",
    "arabic",
]
ATTACK_STYLES: tuple[AttackStyle, ...] = get_args(AttackStyle)
ARABIC = re.compile(r"[؀-ۿ]")

REDTEAM_SIZE = 60
MIN_PER_CATEGORY = 5
MIN_PER_ATTACK = 3
BENIGN_SIZE = 60
MIN_BENIGN_ARABIC = 5
DEV_BLOCK = DEV_ALLOW = 10


class QA(SpecModel):
    question: Line
    answer: Text


class SafetyItem(SpecModel):
    id: Id
    text: str = Field(min_length=1, max_length=4000)
    expected: Literal["allow", "block"]
    category: HarmCategory | None = None
    attack: AttackStyle | None = None
    answers: list[QA] = Field(default_factory=list)
    expected_conditions: list[SafetyCondition] = Field(default_factory=list)
    notes: Line | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "SafetyItem":
        if self.expected == "block" and self.category is None:
            raise ValueError("a block item needs a category")
        if self.expected == "allow" and (self.category or self.attack):
            raise ValueError("an allow item has no category or attack style")
        if self.expected == "block" and self.expected_conditions:
            raise ValueError("a block item has no expected conditions")
        return self


class SafetyFile(SpecModel):
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    split: Literal["redteam", "benign", "dev"]
    status: Literal["incomplete", "draft", "reviewed"]
    source: str | None = None
    requests: list[SafetyItem]


@dataclass(frozen=True)
class SafetyEvalItem:
    id: str
    source: str
    text: str
    expected: str
    category: str | None
    attack: str | None
    answers: tuple[tuple[str, str], ...]
    expected_conditions: tuple[str, ...]

    @property
    def answer_pairs(self) -> list[dict[str, Any]]:
        return [{"question": q, "answer": a} for q, a in self.answers]


class SafetyDataError(ValueError):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("invalid safety data:\n" + "\n".join(f"  {i}" for i in issues))


def load_file(split: str) -> SafetyFile:
    path = FILES[split]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return SafetyFile.model_validate_json(json.dumps(data, default=str))
    except ValidationError as exc:
        issues = [
            Issue(f"{path.name}#{i.path}", i.code, i.message)
            for i in schema_issues(exc, SafetyFile)
        ]
        raise SafetyDataError(issues) from None


def _items(split: str) -> list[SafetyEvalItem]:
    return [
        SafetyEvalItem(
            id=r.id,
            source=split,
            text=r.text,
            expected=r.expected,
            category=r.category,
            attack=r.attack,
            answers=tuple((a.question, a.answer) for a in r.answers),
            expected_conditions=tuple(r.expected_conditions),
        )
        for r in load_file(split).requests
    ]


def normal_items() -> list[SafetyEvalItem]:
    """Everyday requests (the analyzer's gate, dev and Arabic sets): all must be allowed."""
    items = []
    for name in ("gate", "dev", "arabic"):
        for i in analyzer_data.load_set(name):
            items.append(
                SafetyEvalItem(
                    id=f"{name}:{i.id}",
                    source="normal",
                    text=i.text,
                    expected="allow",
                    category=None,
                    attack=None,
                    answers=(),
                    expected_conditions=(),
                )
            )
    return items


def load_set(name: SetName) -> list[SafetyEvalItem]:
    return normal_items() if name == "normal" else _items(name)


def status(split: str) -> str:
    return load_file(split).status


def sources() -> list[dict[str, str]]:
    out = []
    for split, path in FILES.items():
        f = load_file(split)
        out.append(
            {
                "name": f.name,
                "version": f.version,
                "status": f.status,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    out += [
        {"name": s.name, "version": s.version, "status": "n/a", "sha256": s.sha256}
        for s in analyzer_data.sources()
    ]
    return out


# ------------------------------------------------------------------ checks


def coverage_gaps(split: str, items: list[SafetyEvalItem]) -> list[str]:
    """What is still missing for a file to be complete. Empty means complete."""
    gaps = []
    if split == "redteam":
        if len(items) != REDTEAM_SIZE:
            gaps.append(f"{len(items)} of {REDTEAM_SIZE} items")
        if any(i.expected != "block" for i in items):
            gaps.append("every red-team item must be expected: block")
        categories = Counter(i.category for i in items)
        for c in HARM_CATEGORIES:
            if c != "other" and categories[c] < MIN_PER_CATEGORY:
                gaps.append(f"category {c}: {categories[c]} of {MIN_PER_CATEGORY}")
        attacks = Counter(i.attack for i in items)
        for a in ATTACK_STYLES:
            if attacks[a] < MIN_PER_ATTACK:
                gaps.append(f"attack {a}: {attacks[a]} of {MIN_PER_ATTACK}")
        if any(i.attack == "two_turn" and not i.answers for i in items):
            gaps.append("two_turn items need answers")
        if any(i.attack is None for i in items):
            gaps.append("every red-team item needs an attack style")
    elif split == "benign":
        if len(items) != BENIGN_SIZE:
            gaps.append(f"{len(items)} of {BENIGN_SIZE} items")
        if any(i.expected != "allow" for i in items):
            gaps.append("every benign item must be expected: allow")
        arabic = sum(bool(ARABIC.search(i.text)) for i in items)
        if arabic < MIN_BENIGN_ARABIC:
            gaps.append(f"Arabic items: {arabic} of {MIN_BENIGN_ARABIC}")
    elif split == "dev":
        counts = Counter(i.expected for i in items)
        if counts["block"] != DEV_BLOCK:
            gaps.append(f"block items: {counts['block']} of {DEV_BLOCK}")
        if counts["allow"] != DEV_ALLOW:
            gaps.append(f"allow items: {counts['allow']} of {DEV_ALLOW}")
    return gaps


def check_data() -> list[Issue]:
    issues: list[Issue] = []
    try:
        files = {split: load_file(split) for split in FILES}
    except SafetyDataError as exc:
        return exc.issues
    for split, f in files.items():
        where = FILES[split].name
        if f.split != split:
            issues.append(Issue(f"{where}#/split", "wrong_split", f"must be {split}"))
        items = _items(split)
        severity: IssueSeverity = "warning" if f.status == "incomplete" else "error"
        code = "incomplete" if f.status == "incomplete" else "coverage"
        issues += [Issue(where, code, gap, severity) for gap in coverage_gaps(split, items)]
        seen: set[str] = set()
        for n, item in enumerate(items):
            if item.id in seen:
                issues.append(Issue(f"{where}#/requests/{n}/id", "duplicate_id", item.id))
            seen.add(item.id)
            if (item.attack == "arabic") != bool(
                ARABIC.search(item.text)
            ) and item.expected == "block":
                issues.append(
                    Issue(f"{where}#/requests/{n}", "language", "attack arabic <=> Arabic text")
                )
    issues += _check_overlaps()
    return issues


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _check_overlaps() -> list[Issue]:
    issues = []
    first: dict[str, str] = {}
    everything = [(f"{i.source}:{i.id}", i.text) for split in FILES for i in _items(split)]
    everything += [(i.id, i.text) for i in normal_items()]  # includes the seed requests
    for where, text in everything:
        key = _norm(text)
        if key in first and first[key] != where:
            issues.append(Issue(where, "duplicate_text", f"same text as {first[key]}"))
        first.setdefault(key, where)
    return issues
