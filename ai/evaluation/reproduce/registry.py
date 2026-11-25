"""The experiment registry (AI-25): ai/evaluation/experiments.yaml, one entry per report."""

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.spec import Issue, schema_issues

AI_DIR = Path(__file__).resolve().parents[2]
REGISTRY = AI_DIR / "evaluation" / "experiments.yaml"
Kind = Literal["offline", "live", "rescore"]
Status = Literal["active", "pending-merge"]
SHA = r"^[0-9a-f]{40}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Input(_Model):
    """A data file the experiment read, hashed as it was at `recorded_at`."""

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash: str = "sha256-lf"


class IgnoreExtra(_Model):
    """A field ignored for this entry only, beyond the global list. Needs a written reason."""

    field: str
    reason: str = Field(min_length=10)


class Entry(_Model):
    id: str
    experiment: str
    task: str
    question: str
    kind: Kind
    status: Status = "active"
    branch: str | None = None  # where a pending-merge report lives today
    report: str  # repo-relative path of the report (.json) or release manifest
    recorded_at: str = Field(pattern=SHA)  # the commit that added the report
    command: list[str] | None = None
    model: str | None = None
    prompt: str | None = None
    cost_usd: float | None = None
    inputs: list[Input] = Field(default_factory=list)
    ignore_extra: list[IgnoreExtra] = Field(default_factory=list)
    reproduces: bool | None = None  # set by `reproduce run`; None = not run yet
    reproduces_note: str | None = None
    limitations: list[str] = Field(default_factory=list)


class DataFile(_Model):
    path: str
    why: str


class Registry(_Model):
    version: Literal[1]
    ignore: list[str]
    data_files: list[DataFile] = Field(default_factory=list)
    experiments: list[Entry]

    def entry(self, entry_id: str) -> Entry:
        return next(e for e in self.experiments if e.id == entry_id)


class RegistryError(ValueError):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__("invalid experiments.yaml:\n" + "\n".join(f"  {i}" for i in issues))


def load_registry(path: Path = REGISTRY) -> Registry:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return Registry.model_validate_json(json.dumps(data, default=str))
    except ValidationError as exc:
        issues = [
            Issue(f"{path.name}#{i.path}", i.code, i.message) for i in schema_issues(exc, Registry)
        ]
        raise RegistryError(issues) from None


__all__ = ["REGISTRY", "DataFile", "Entry", "Input", "Registry", "RegistryError", "load_registry"]
