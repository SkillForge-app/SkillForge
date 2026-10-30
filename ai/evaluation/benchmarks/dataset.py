"""Benchmark datasets (AI-04, contract B2): seed skills with prompts, rubrics and labelled requests.

People edit one YAML file per skill in `<benchmark>/skills/`. A release freezes them into
`<benchmark>/releases/<version>/` as JSONL files with JSON Schemas, a data card and a manifest of
sha256 hashes. That release folder is what Data Engineering stores (DE-10); every evaluation run
records `dataset`, `version` and `dataset_sha256` from the manifest.

    skills, issues = load_benchmark(SEED_DIR)
    write_release(SEED_DIR, "0.1.0")
"""

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from core.spec import (
    HIGH_RISK_AREAS,
    KINDS,
    SPEC_VERSION,
    Issue,
    Kind,
    RiskLevel,
    SpecValidationError,
    load_spec,
    schema_issues,
)
from core.spec.models import Domain, Id, Line, SkillName, SpecModel, TargetList, Title

AI_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = Path(__file__).resolve().parent
SEED_DIR = BENCHMARKS_DIR / "seed"
DATASET_NAME = "skillforge-seed-benchmark"

# ------------------------------------------------------------------ closed vocabularies
# Shared ones (Kind, DomainArea, RiskLevel, targets) come from core.spec; these are benchmark-only.

RequestStyle = Literal["clear", "vague", "detailed"]
RubricType = Literal["quality", "procedure", "guardrail", "format"]
ReviewStatus = Literal["draft", "reviewed"]
PromptTag = Literal["short", "detailed", "edge-case", "near-miss", "unrelated"]
PromptKind = Literal["test", "should_not_trigger"]

REQUEST_STYLES: tuple[RequestStyle, ...] = get_args(RequestStyle)
TECHNICAL_AREAS = frozenset({"technology", "data"})

# The standard size of every seed skill (agreed for AI-04).
TEST_PROMPTS = 8
SHOULD_NOT_TRIGGER = 6
MIN_NEAR_MISSES = 3
RUBRIC_ITEMS = (5, 8)

# What the whole seed benchmark must cover.
SEED_SKILLS = 10
MIN_TECHNICAL = 4
MIN_NON_TECHNICAL = 4

PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1500)]
SpecPath = Annotated[str, StringConstraints(pattern=r"^examples/skillspec/[a-z0-9-]+\.yaml$")]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


# ------------------------------------------------------------------ source models


class RequestLabels(SpecModel):
    kind: Kind
    domain: Domain
    risk: RiskLevel
    targets: TargetList = Field(min_length=1)


class LabelledRequest(SpecModel):
    """What a user would type to ask SkillForge for this skill, with the correct labels (AI-05)."""

    id: Id
    style: RequestStyle
    text: PromptText
    labels: RequestLabels


class Prompt(SpecModel):
    id: Id
    text: PromptText
    tags: list[PromptTag] = Field(default_factory=list)


class NegativePrompt(Prompt):
    closer_skill: SkillName | None = Field(
        default=None, description="The seed skill this prompt really belongs to, if any."
    )


class RubricItem(SpecModel):
    id: Id
    text: Line
    type: RubricType
    critical: bool = Field(default=False, description="A failed critical item fails the answer.")


class Review(SpecModel):
    status: ReviewStatus = "draft"
    reviewer: Title | None = None


class SeedSkill(SpecModel):
    name: SkillName
    title: Title
    kind: Kind
    domain: Domain
    risk: RiskLevel
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    targets: TargetList = Field(min_length=1)
    spec: SpecPath | None = None
    review: Review = Field(default_factory=Review)
    requests: list[LabelledRequest]
    test_prompts: list[Prompt]
    should_not_trigger: list[NegativePrompt]
    rubric: list[RubricItem]

    @property
    def area(self) -> str:
        return self.domain.split("/", 1)[0]

    @property
    def technical(self) -> bool:
        return self.area in TECHNICAL_AREAS


# ------------------------------------------------------------------ release record models


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillRecord(_Record):
    name: str
    title: str
    kind: str
    domain: str
    domain_area: str
    risk: str
    technical: bool
    summary: str
    targets: list[str]
    spec: str | None
    review_status: str
    reviewer: str | None


class PromptRecord(_Record):
    id: str = Field(description="<skill>/<prompt id>, stable across versions.")
    skill: str
    kind: PromptKind
    text: str
    tags: list[str]
    closer_skill: str | None
    domain: str = Field(description="The skill's domain; a domain-only label for AI-05.")


class RubricRecord(_Record):
    id: str
    skill: str
    text: str
    type: str
    critical: bool


class RequestRecord(_Record):
    """A labelled skill request: ready to use as AI-05 (Request Analyzer) training/test data."""

    id: str
    skill: str
    style: str
    text: str
    kind: str
    domain: str
    domain_area: str
    risk: str
    targets: list[str]


RECORD_FILES: dict[str, type[_Record]] = {
    "skills.jsonl": SkillRecord,
    "prompts.jsonl": PromptRecord,
    "rubrics.jsonl": RubricRecord,
    "requests.jsonl": RequestRecord,
}


# ------------------------------------------------------------------ loading and checks


class BenchmarkError(ValueError):
    def __init__(self, message: str, issues: Iterable[Issue] = ()) -> None:
        self.issues = tuple(issues)
        lines = "".join(f"\n  {issue}" for issue in self.issues)
        super().__init__(message + lines)


def load_benchmark(root: Path = SEED_DIR) -> tuple[list[SeedSkill], list[Issue]]:
    """Load `<root>/skills/*.yaml`, then run every cross-check. Paths are `<file>#<pointer>`."""
    skills: list[SeedSkill] = []
    issues: list[Issue] = []
    files = sorted((root / "skills").glob("*.yaml"))
    for path in files:
        where = f"skills/{path.name}#"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            skill = SeedSkill.model_validate_json(json.dumps(data, default=str))
        except yaml.YAMLError as exc:
            issues.append(Issue(where, "yaml_syntax", str(exc)))
            continue
        except ValidationError as exc:
            issues += [_at(where, i) for i in schema_issues(exc, SeedSkill)]
            continue
        if skill.name != path.stem:
            issues.append(Issue(f"{where}/name", "name_mismatch", "name must match the file name"))
        skills.append(skill)
    if len(skills) == len(files):  # cross-checks need every file to load
        issues += check_benchmark(skills)
    return skills, issues


def check_benchmark(skills: list[SeedSkill]) -> list[Issue]:
    issues: list[Issue] = []
    names = {s.name for s in skills}
    for skill in skills:
        issues += [_at(f"skills/{skill.name}.yaml#", i) for i in _check_skill(skill, names)]
    issues += _check_unique_texts(skills)
    issues += _check_coverage(skills)
    return issues


def _check_skill(skill: SeedSkill, names: set[str]) -> Iterator[Issue]:
    if len(skill.test_prompts) != TEST_PROMPTS:
        yield Issue("/test_prompts", "count", f"needs {TEST_PROMPTS} test prompts")
    if len(skill.should_not_trigger) != SHOULD_NOT_TRIGGER:
        yield Issue("/should_not_trigger", "count", f"needs {SHOULD_NOT_TRIGGER} prompts")
    near = sum("near-miss" in p.tags for p in skill.should_not_trigger)
    if near < MIN_NEAR_MISSES:
        yield Issue(
            "/should_not_trigger",
            "too_few_near_misses",
            f"needs at least {MIN_NEAR_MISSES} prompts tagged near-miss",
        )
    low, high = RUBRIC_ITEMS
    if not low <= len(skill.rubric) <= high:
        yield Issue("/rubric", "count", f"needs {low} to {high} rubric items")
    if sorted(r.style for r in skill.requests) != sorted(REQUEST_STYLES):
        yield Issue(
            "/requests", "request_styles", "needs one clear, one vague and one detailed request"
        )

    seen: dict[str, str] = {}
    lists: list[tuple[str, list[Any]]] = [
        ("requests", skill.requests),
        ("test_prompts", skill.test_prompts),
        ("should_not_trigger", skill.should_not_trigger),
        ("rubric", skill.rubric),
    ]
    for field, items in lists:
        for i, item in enumerate(items):
            if item.id in seen:
                yield Issue(
                    f"/{field}/{i}/id", "duplicate_id", f'id "{item.id}" used by {seen[item.id]}'
                )
            else:
                seen[item.id] = f"/{field}/{i}"

    high_risk_area = skill.area in HIGH_RISK_AREAS
    if high_risk_area and skill.risk != "high":
        yield Issue(
            "/risk", "risk_mismatch", f"{skill.area} is a high-risk area: risk must be high"
        )
    if not high_risk_area and skill.risk == "high":
        yield Issue("/risk", "risk_mismatch", "risk high is only for legal, medical and finance")
    if skill.risk == "high" and not any(r.critical and r.type == "guardrail" for r in skill.rubric):
        yield Issue(
            "/rubric",
            "high_risk_needs_critical_guardrail",
            "add a critical guardrail rubric item (disclaimer or human review)",
        )

    for i, request in enumerate(skill.requests):
        for field in ("kind", "domain", "risk"):
            if getattr(request.labels, field) != getattr(skill, field):
                yield Issue(
                    f"/requests/{i}/labels/{field}",
                    "label_mismatch",
                    f"label must equal the skill's {field}",
                )

    for i, prompt in enumerate(skill.should_not_trigger):
        if prompt.closer_skill is not None and (
            prompt.closer_skill not in names or prompt.closer_skill == skill.name
        ):
            yield Issue(
                f"/should_not_trigger/{i}/closer_skill",
                "unknown_closer_skill",
                "closer_skill must name another seed skill",
            )

    if skill.spec:
        yield from _check_spec(skill)


def _check_spec(skill: SeedSkill) -> Iterator[Issue]:
    assert skill.spec is not None
    try:
        spec = load_spec(AI_ROOT / skill.spec)
    except (OSError, SpecValidationError) as exc:
        yield Issue("/spec", "spec_invalid", f"{skill.spec} does not load: {type(exc).__name__}")
        return
    for field, value in (
        ("name", spec.skill.name),
        ("kind", spec.skill.kind),
        ("domain", spec.skill.domain),
    ):
        if getattr(skill, field) != value:
            yield Issue(f"/{field}", "spec_mismatch", f"{field} differs from {skill.spec}")
    for field, spec_prompts, ours in (
        ("test_prompts", spec.evaluation.test_prompts, skill.test_prompts),
        ("should_not_trigger", spec.evaluation.should_not_trigger, skill.should_not_trigger),
    ):
        texts = {_norm(p.text) for p in ours}
        for i, text in enumerate(spec_prompts):
            if _norm(text) not in texts:
                yield Issue(
                    f"/{field}",
                    "spec_prompt_missing",
                    f"{skill.spec} evaluation.{field}[{i}] is not in the benchmark",
                )


def _check_unique_texts(skills: list[SeedSkill]) -> Iterator[Issue]:
    first: dict[str, str] = {}
    for skill in skills:
        entries: list[tuple[str, str]] = [
            (f"/requests/{i}/text", r.text) for i, r in enumerate(skill.requests)
        ]
        entries += [(f"/test_prompts/{i}/text", p.text) for i, p in enumerate(skill.test_prompts)]
        entries += [
            (f"/should_not_trigger/{i}/text", p.text)
            for i, p in enumerate(skill.should_not_trigger)
        ]
        for pointer, text in entries:
            where = f"skills/{skill.name}.yaml#{pointer}"
            key = _norm(text)
            if key in first:
                yield Issue(where, "duplicate_text", f"same text as {first[key]}")
            else:
                first[key] = where


def _check_coverage(skills: list[SeedSkill]) -> Iterator[Issue]:
    if len(skills) != SEED_SKILLS:
        yield Issue("", "coverage", f"the seed benchmark needs {SEED_SKILLS} skills")
    technical = sum(s.technical for s in skills)
    if technical < MIN_TECHNICAL or len(skills) - technical < MIN_NON_TECHNICAL:
        yield Issue(
            "",
            "coverage",
            f"needs at least {MIN_TECHNICAL} technical and {MIN_NON_TECHNICAL} "
            "non-technical skills",
        )
    missing_kinds = set(KINDS) - {s.kind for s in skills}
    if missing_kinds:
        yield Issue("", "coverage", f"no skill of kind {sorted(missing_kinds)}")
    missing_risk = set(HIGH_RISK_AREAS) - {s.area for s in skills}
    if missing_risk:
        yield Issue("", "coverage", f"no skill in high-risk area {sorted(missing_risk)}")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _at(prefix: str, issue: Issue) -> Issue:
    return Issue(prefix + issue.path, issue.code, issue.message, issue.severity)


# ------------------------------------------------------------------ releases


def records(skills: list[SeedSkill]) -> dict[str, list[_Record]]:
    out: dict[str, list[_Record]] = {name: [] for name in RECORD_FILES}
    for skill in sorted(skills, key=lambda s: s.name):
        out["skills.jsonl"].append(
            SkillRecord(
                name=skill.name,
                title=skill.title,
                kind=skill.kind,
                domain=skill.domain,
                domain_area=skill.area,
                risk=skill.risk,
                technical=skill.technical,
                summary=skill.summary,
                targets=list(skill.targets),
                spec=skill.spec,
                review_status=skill.review.status,
                reviewer=skill.review.reviewer,
            )
        )
        prompts: list[tuple[PromptKind, Prompt]] = [("test", p) for p in skill.test_prompts]
        prompts += [("should_not_trigger", p) for p in skill.should_not_trigger]
        for kind, prompt in prompts:
            out["prompts.jsonl"].append(
                PromptRecord(
                    id=f"{skill.name}/{prompt.id}",
                    skill=skill.name,
                    kind=kind,
                    text=prompt.text,
                    tags=list(prompt.tags),
                    closer_skill=getattr(prompt, "closer_skill", None),
                    domain=skill.domain,
                )
            )
        for item in skill.rubric:
            out["rubrics.jsonl"].append(
                RubricRecord(
                    id=f"{skill.name}/{item.id}",
                    skill=skill.name,
                    text=item.text,
                    type=item.type,
                    critical=item.critical,
                )
            )
        for request in skill.requests:
            out["requests.jsonl"].append(
                RequestRecord(
                    id=f"{skill.name}/{request.id}",
                    skill=skill.name,
                    style=request.style,
                    text=request.text,
                    kind=request.labels.kind,
                    domain=request.labels.domain,
                    domain_area=request.labels.domain.split("/", 1)[0],
                    risk=request.labels.risk,
                    targets=list(request.labels.targets),
                )
            )
    return out


def render_release(skills: list[SeedSkill], version: str) -> dict[str, bytes]:
    """Every file of a release except manifest.json, as bytes. Deterministic for given input."""
    files: dict[str, bytes] = {}
    data = records(skills)
    for name, rows in data.items():
        files[name] = "".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows
        ).encode("utf-8")
    for name, model in RECORD_FILES.items():
        schema = model.model_json_schema()
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
        text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        files[f"schemas/{name.replace('.jsonl', '.schema.json')}"] = text.encode("utf-8")
    files["README.md"] = _data_card(skills, version, {n: len(r) for n, r in data.items()}).encode()
    return files


@dataclass(frozen=True)
class Release:
    path: Path
    manifest: dict[str, Any]


def write_release(
    root: Path, version: str, *, created: date | None = None, dataset: str = DATASET_NAME
) -> Release:
    """Validate the sources and freeze them into `<root>/releases/<version>/`. Never overwrites."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise BenchmarkError(f"version {version!r} is not MAJOR.MINOR.PATCH")
    target = root / "releases" / version
    if target.exists():
        raise BenchmarkError(f"release {version} already exists; releases are immutable")
    skills, issues = load_benchmark(root)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise BenchmarkError(f"cannot release {version}: the benchmark has errors", errors)
    drafts = sorted(s.name for s in skills if s.review.status != "reviewed")
    if int(version.split(".")[0]) >= 1 and drafts:
        raise BenchmarkError(f"{version} needs every skill reviewed; still draft: {drafts}")

    files = render_release(skills, version)
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}
    manifest = {
        "dataset": dataset,
        "version": version,
        "created": (created or date.today()).isoformat(),
        "skillspec_version": SPEC_VERSION,
        "counts": {
            "skills": len(skills),
            "test_prompts": sum(len(s.test_prompts) for s in skills),
            "should_not_trigger": sum(len(s.should_not_trigger) for s in skills),
            "rubric_items": sum(len(s.rubric) for s in skills),
            "labelled_requests": sum(len(s.requests) for s in skills),
        },
        "review": {"reviewed": len(skills) - len(drafts), "draft": len(drafts)},
        "files": hashes,
        "dataset_sha256": _dataset_hash(hashes),
    }
    for name, body in files.items():
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(body)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return Release(target, manifest)


def verify_release(path: Path) -> list[Issue]:
    """Check a release folder against its manifest: no file changed, missing or added."""
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    issues: list[Issue] = []
    listed: dict[str, str] = manifest["files"]
    present = {
        p.relative_to(path).as_posix()
        for p in path.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    for name in sorted(present - set(listed)):
        issues.append(Issue(name, "unexpected_file", "file is not listed in manifest.json"))
    for name, digest in listed.items():
        file = path / name
        if not file.exists():
            issues.append(Issue(name, "missing_file", "file listed in manifest.json is missing"))
        elif hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            issues.append(
                Issue(name, "changed_file", "file changed after release (sha256 differs)")
            )
    if _dataset_hash(listed) != manifest["dataset_sha256"]:
        issues.append(Issue("manifest.json", "changed_file", "dataset_sha256 does not match files"))
    return issues


def _dataset_hash(hashes: dict[str, str]) -> str:
    lines = "".join(f"{name}:{digest}\n" for name, digest in sorted(hashes.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _data_card(skills: list[SeedSkill], version: str, counts: dict[str, int]) -> str:
    rows = "\n".join(
        f"| {s.name} | {s.kind} | {s.domain} | {s.risk} | {'yes' if s.technical else 'no'} "
        f"| {s.review.status} |"
        for s in sorted(skills, key=lambda s: s.name)
    )
    return f"""# {DATASET_NAME} {version}

Seed benchmark for SkillForge (AI-04). Generated by `python -m evaluation.benchmarks release`;
do not edit. Integrity: every file's sha256 is in `manifest.json`. Record `dataset`, `version`
and `dataset_sha256` with every evaluation run (DE-10).

## Purpose and intended uses
- AI-16 evaluation harness: run each `test` prompt with and without the skill; grade with the
  skill's rubric (LLM judge, calibrated on human labels).
- AI-17 trigger accuracy: `test` prompts must load the skill, `should_not_trigger` prompts must
  not. Prompts tagged `near-miss` are the hard negatives; `closer_skill` names the right skill.
- AI-05 Request Analyzer: `requests.jsonl` holds labelled skill requests (kind, domain, risk,
  targets). Prompts in `prompts.jsonl` carry the skill's domain only, not kind or risk.

## Files
| File | One record per line |
|------|---------------------|
| skills.jsonl | a seed skill ({counts["skills.jsonl"]}) |
| prompts.jsonl | a test or should_not_trigger prompt ({counts["prompts.jsonl"]}) |
| rubrics.jsonl | a rubric item; `critical` = must pass ({counts["rubrics.jsonl"]}) |
| requests.jsonl | a labelled skill request ({counts["requests.jsonl"]}) |
| schemas/*.schema.json | JSON Schema (draft 2020-12) for each record type |

Ids (`<skill>/<id>`) are stable across versions.

## Skills
| Skill | Kind | Domain | Risk | Technical | Review |
|-------|------|--------|------|-----------|--------|
{rows}

## How it was made
Written by the AI team as synthetic data: no real people, companies or personal data. Each
skill is reviewed by a person before a 1.x release (`review_status`).

## Versions
MAJOR: record schema changes. MINOR: any prompt, rubric item or label added, changed or removed
(scores are not comparable across minor versions). PATCH: metadata or data card only.

Licence: internal SkillForge use.
"""
