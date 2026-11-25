"""Load immutable AI-04 releases and optional human rubric labels for AI-16."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evaluation.benchmarks.dataset import (
    PromptRecord,
    RubricRecord,
    SkillRecord,
    verify_release,
)

Condition = Literal["with_skill", "without_skill"]
RecordT = TypeVar("RecordT", bound=BaseModel)


class HumanLabel(BaseModel):
    """Human rubric scores for an exact, previously generated benchmark answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str
    prompt: str = Field(min_length=1)
    condition: Condition
    answer: str = Field(min_length=1)
    rubric_scores: dict[str, bool] = Field(min_length=1)
    reviewer: str = Field(min_length=1)


@dataclass(frozen=True)
class SkillBenchmark:
    dataset: str
    version: str
    dataset_sha256: str
    skill: SkillRecord
    prompts: tuple[PromptRecord, ...]
    rubric: tuple[RubricRecord, ...]


def _read_jsonl(path: Path, model: type[RecordT]) -> Iterator[RecordT]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            yield model.model_validate_json(line)
        except ValidationError as exc:
            raise ValueError(f"invalid record in {path.name}:{line_number}: {exc}") from exc


def load_skill(release_dir: Path, skill_name: str) -> SkillBenchmark:
    """Load one skill's test prompts and rubric after verifying release integrity."""
    manifest_path = release_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read release manifest at {manifest_path}: {exc}") from exc

    issues = verify_release(release_dir)
    if issues:
        raise ValueError(
            "benchmark release failed integrity verification: "
            + "; ".join(str(issue) for issue in issues)
        )

    skills = [
        record
        for record in _read_jsonl(release_dir / "skills.jsonl", SkillRecord)
        if record.name == skill_name
    ]
    if len(skills) != 1:
        raise ValueError(f"expected exactly one skill named {skill_name!r}, found {len(skills)}")
    prompts = tuple(
        record
        for record in _read_jsonl(release_dir / "prompts.jsonl", PromptRecord)
        if record.skill == skill_name and record.kind == "test"
    )
    rubric = tuple(
        record
        for record in _read_jsonl(release_dir / "rubrics.jsonl", RubricRecord)
        if record.skill == skill_name
    )
    if not prompts:
        raise ValueError(f"skill {skill_name!r} has no test prompts in the release")
    if not rubric:
        raise ValueError(f"skill {skill_name!r} has no rubric items in the release")

    return SkillBenchmark(
        dataset=manifest["dataset"],
        version=manifest["version"],
        dataset_sha256=manifest["dataset_sha256"],
        skill=skills[0],
        prompts=prompts,
        rubric=rubric,
    )


def load_calibration(path: Path) -> tuple[HumanLabel, ...]:
    """Read human decisions from JSONL without modifying the immutable benchmark."""
    records = tuple(_read_jsonl(path, HumanLabel))
    if not records:
        raise ValueError(f"human calibration file is empty: {path}")
    keys = [
        (
            row.prompt_id,
            row.condition,
            hashlib.sha256(row.answer.encode("utf-8")).hexdigest(),
            row.reviewer,
        )
        for row in records
    ]
    if len(keys) != len(set(keys)):
        raise ValueError(f"human calibration file contains duplicate labels: {path}")
    return records
