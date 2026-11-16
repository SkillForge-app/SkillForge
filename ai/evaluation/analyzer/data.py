"""Labelled skill requests for the Request Analyzer (AI-05).

Sets:
- gate:   the 30 requests of a pinned seed-benchmark release + requests-test.yaml (70) = 100.
          The 90%-per-field done-when of AI-05 is measured on exactly these.
- dev:    requests-dev.yaml (20). Prompt tuning and few-shot examples only.
- arabic: requests-arabic.yaml (10). Reported, never gated.
Rules for labels: LABELLING.md.
"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from core.spec import DOMAIN_AREAS, HIGH_RISK_AREAS, Issue, Kind, RiskLevel, Target, schema_issues
from core.spec.models import Domain, Id, Line, SpecModel, TargetList
from evaluation.benchmarks.dataset import SEED_DIR, RequestStyle

ANALYZER_DIR = Path(__file__).resolve().parent
SEED_RELEASE = "0.1.0"  # move to 1.0.0 once the reviewed seed benchmark is released
SetName = Literal["gate", "dev", "arabic"]
FILES: dict[str, Path] = {
    "test": ANALYZER_DIR / "requests-test.yaml",
    "dev": ANALYZER_DIR / "requests-dev.yaml",
    "arabic": ANALYZER_DIR / "requests-arabic.yaml",
}
EXPECTED = {"test": 70, "dev": 20, "arabic": 10}
GATE_SIZE = 100
SEED_COVERED_AREAS = frozenset(
    {"technology", "data", "marketing", "legal", "medical", "finance", "hr", "writing"}
)
ARABIC = re.compile(r"[؀-ۿ]")


class LabelledRequest(SpecModel):
    id: Id
    text: str = Field(min_length=1, max_length=4000)
    style: RequestStyle
    kind: Kind
    domain: Domain
    risk: RiskLevel
    needs_clarification: bool
    mentioned_targets: TargetList = Field(default_factory=list)
    notes: Line | None = None


class LabelFile(SpecModel):
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    split: Literal["test", "dev", "arabic"]
    requests: list[LabelledRequest]


@dataclass(frozen=True)
class EvalItem:
    """One labelled request, from any source, in the form the evaluation uses."""

    id: str
    source: str  # "seed" or the file split
    text: str
    kind: str
    domain: str
    risk: str
    needs_clarification: bool
    mentioned_targets: tuple[Target, ...] | None  # None: not labelled (seed requests)

    @property
    def domain_area(self) -> str:
        return self.domain.split("/", 1)[0]


@dataclass(frozen=True)
class DataSource:
    name: str
    version: str
    sha256: str


class DataError(ValueError):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("invalid labelled requests:\n" + "\n".join(f"  {i}" for i in issues))


def load_file(split: str) -> LabelFile:
    path = FILES[split]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return LabelFile.model_validate_json(json.dumps(data, default=str))
    except ValidationError as exc:
        issues = [
            Issue(f"{path.name}#{i.path}", i.code, i.message) for i in schema_issues(exc, LabelFile)
        ]
        raise DataError(issues) from None


def seed_requests(release: str = SEED_RELEASE) -> list[EvalItem]:
    path = SEED_DIR / "releases" / release / "requests.jsonl"
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        items.append(
            EvalItem(
                id=row["id"],
                source="seed",
                text=row["text"],
                kind=row["kind"],
                domain=row["domain"],
                risk=row["risk"],
                needs_clarification=row["style"] == "vague",
                mentioned_targets=None,  # seed targets are UI choices, not text
            )
        )
    return items


def file_items(split: str) -> list[EvalItem]:
    labelled = load_file(split)
    return [
        EvalItem(
            id=r.id,
            source=split,
            text=r.text,
            kind=r.kind,
            domain=r.domain,
            risk=r.risk,
            needs_clarification=r.needs_clarification,
            mentioned_targets=tuple(r.mentioned_targets),
        )
        for r in labelled.requests
    ]


def load_set(name: SetName) -> list[EvalItem]:
    if name == "gate":
        return seed_requests() + file_items("test")
    return file_items(name)


def sources(release: str = SEED_RELEASE) -> list[DataSource]:
    """Versions and fingerprints of every data file, for evaluation reports (DE-10)."""
    manifest = json.loads(
        (SEED_DIR / "releases" / release / "manifest.json").read_text(encoding="utf-8")
    )
    out = [DataSource(manifest["dataset"], manifest["version"], manifest["dataset_sha256"])]
    for split, path in FILES.items():
        out.append(
            DataSource(
                load_file(split).name,
                load_file(split).version,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return out


# ------------------------------------------------------------------ checks


def check_data() -> list[Issue]:
    issues: list[Issue] = []
    try:
        sets = {split: load_file(split) for split in FILES}
    except DataError as exc:
        return exc.issues
    for split, labelled in sets.items():
        where = FILES[split].name
        if labelled.split != split:
            issues.append(Issue(f"{where}#/split", "wrong_split", f"must be {split}"))
        if len(labelled.requests) != EXPECTED[split]:
            issues.append(Issue(f"{where}#/requests", "count", f"needs {EXPECTED[split]}"))
        seen: set[str] = set()
        for i, r in enumerate(labelled.requests):
            at = f"{where}#/requests/{i}"
            if r.id in seen:
                issues.append(Issue(f"{at}/id", "duplicate_id", f"{r.id} is used twice"))
            seen.add(r.id)
            area = r.domain.split("/", 1)[0]
            if (area in HIGH_RISK_AREAS) != (r.risk == "high"):
                issues.append(
                    Issue(
                        f"{at}/risk", "risk_rule", "risk is high exactly for legal/medical/finance"
                    )
                )
            if r.needs_clarification != (r.style == "vague"):
                issues.append(
                    Issue(f"{at}/needs_clarification", "vague_rule", "true exactly when vague")
                )
            if (split == "arabic") != bool(ARABIC.search(r.text)):
                issues.append(Issue(f"{at}/text", "language", "Arabic only in the arabic set"))
    issues += _check_overlaps()
    issues += _check_gate_coverage()
    return issues


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _check_overlaps() -> list[Issue]:
    issues = []
    first: dict[str, str] = {}
    everything = [("seed", i) for i in seed_requests()]
    everything += [(split, i) for split in FILES for i in file_items(split)]
    for source, item in everything:
        key = _norm(item.text)
        if key in first:
            issues.append(
                Issue(f"{source}:{item.id}", "duplicate_text", f"same text as {first[key]}")
            )
        else:
            first[key] = f"{source}:{item.id}"
    return issues


@dataclass(frozen=True)
class Coverage:
    size: int
    kinds: dict[str, int]
    risks: dict[str, int]
    styles: dict[str, int]
    areas: dict[str, int]
    with_targets: int


def gate_coverage() -> Coverage:
    gate = load_set("gate")
    seed_styles = Counter(
        json.loads(line)["style"]
        for line in (SEED_DIR / "releases" / SEED_RELEASE / "requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    styles = Counter(r.style for r in load_file("test").requests) + seed_styles
    return Coverage(
        size=len(gate),
        kinds=dict(Counter(i.kind for i in gate)),
        risks=dict(Counter(i.risk for i in gate)),
        styles=dict(styles),
        areas=dict(Counter(i.domain_area for i in gate)),
        with_targets=sum(bool(i.mentioned_targets) for i in gate),
    )


# Minimums for the 100-request gate set (agreed in the AI-05 plan).
MIN_PER_STYLE = 25
MIN_ROLE = MIN_TASK = 25
MIN_WORKFLOW = 15
MIN_MEDIUM = 10
MIN_HIGH = 15
MIN_NEW_AREA = 5
MIN_WITH_TARGETS = 10


def _check_gate_coverage() -> list[Issue]:
    c = gate_coverage()
    problems = []
    if c.size != GATE_SIZE:
        problems.append(f"gate set has {c.size} requests, needs {GATE_SIZE}")
    for style in ("clear", "vague", "detailed"):
        if c.styles.get(style, 0) < MIN_PER_STYLE:
            problems.append(f"style {style}: {c.styles.get(style, 0)} < {MIN_PER_STYLE}")
    for kind, minimum in (("role", MIN_ROLE), ("task", MIN_TASK), ("workflow", MIN_WORKFLOW)):
        if c.kinds.get(kind, 0) < minimum:
            problems.append(f"kind {kind}: {c.kinds.get(kind, 0)} < {minimum}")
    if c.risks.get("medium", 0) < MIN_MEDIUM:
        problems.append(f"risk medium: {c.risks.get('medium', 0)} < {MIN_MEDIUM}")
    if c.risks.get("high", 0) < MIN_HIGH:
        problems.append(f"risk high: {c.risks.get('high', 0)} < {MIN_HIGH}")
    for area in sorted(set(DOMAIN_AREAS) - SEED_COVERED_AREAS):
        if c.areas.get(area, 0) < MIN_NEW_AREA:
            problems.append(f"area {area}: {c.areas.get(area, 0)} < {MIN_NEW_AREA}")
    if c.with_targets < MIN_WITH_TARGETS:
        problems.append(f"requests naming a platform: {c.with_targets} < {MIN_WITH_TARGETS}")
    return [Issue("gate", "coverage", p) for p in problems]
