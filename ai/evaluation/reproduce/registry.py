"""The experiment registry (AI-25): ai/evaluation/experiments.yaml, one entry per report."""

import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.spec import Issue, schema_issues
from evaluation.reproduce.strict import DuplicateKeyError, yaml_unique

AI_DIR = Path(__file__).resolve().parents[2]
REGISTRY = AI_DIR / "evaluation" / "experiments.yaml"
# Everything `reproduce` extracts goes under here, in folders it creates and removes itself.
TEMP_ROOT = Path(tempfile.gettempdir()) / "skillforge-reproduce"
Kind = Literal["offline", "live", "rescore"]
Status = Literal["active", "pending-merge"]
# final: the report a decision rests on (the done-when: every final entry reproduces);
# superseded: an intermediate round replaced by a later report (may stay reproduces: false);
# invalid: a run that measured nothing (e.g. a provider failure); like superseded, it never
# counts toward the done-when, and the doc lists it on its own.
Role = Literal["final", "superseded", "invalid"]
# How an offline entry's command gets its model: `fake` (the fake LLM backend: no model at
# all) or `local-model` (the real gateway with the pinned local embedding model, no key, no
# network). Set per entry, never globally: a fake backend in place of a model would give a
# meaningless report, so `check` rejects `fake` for code that embeds.
LlmBackend = Literal["fake", "local-model"]
SHA = r"^[0-9a-f]{40}$"
# A repo-relative path under ai/: forward slashes, no empty, `.` or `..` segment. `run` and
# `check` join these to the repo or an extracted tree; nothing may point outside them.
_REPO_PATH = re.compile(r"ai(?:/[A-Za-z0-9_.-]+)+")
# The only commands `run` executes: an evaluation module, with this tool's own interpreter.
_MODULE = re.compile(r"evaluation(?:\.[a-z_][a-z0-9_]*)+")


def _repo_path(value: str) -> str:
    if not _REPO_PATH.fullmatch(value) or any(s in (".", "..") for s in value.split("/")):
        raise ValueError("must be a path under ai/ with no '.' or '..' segment")
    return value


RepoPath = Annotated[str, AfterValidator(_repo_path)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Input(_Model):
    """A data file the experiment read, hashed as it was at `recorded_at`."""

    path: RepoPath
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash: str = "sha256-lf"


class IgnoreExtra(_Model):
    """A field ignored for this entry only, beyond the global list. Needs a written reason."""

    field: str
    reason: str = Field(min_length=10)


class TrackedRun(_Model):
    """The id-only copy of a live run's raw predictions (evaluation/reproduce/track.py)."""

    path: RepoPath
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # the raw local file, as recorded
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # the tracked file, LF-normalised
    lines: int = Field(ge=1)


class NotRecomputable(_Model):
    """A report metric the tracked run cannot support, and why. Never used to hide a
    difference: a listed metric is simply not compared."""

    metric: str  # e.g. mentioned_targets.exact_match
    reason: str = Field(min_length=10)


class Entry(_Model):
    id: str
    experiment: str
    task: str
    question: str
    kind: Kind
    status: Status = "active"
    role: Role
    superseded_by: str | None = None  # a superseded entry: the final entry that replaced it
    branch: str | None = None  # where a pending-merge report lives today
    report: RepoPath  # repo-relative path of the report (.json) or release manifest
    # The commit whose code and data produced the report: the commit that added it, or (for a
    # report generated after its code was committed) that code commit. Must be in history.
    recorded_at: str = Field(pattern=SHA)
    command: list[str] | None = None
    llm_backend: LlmBackend | None = None  # required for offline entries
    model: str | None = None
    prompt: str | None = None
    cost_usd: float | None = None
    inputs: list[Input] = Field(default_factory=list)
    ignore_extra: list[IgnoreExtra] = Field(default_factory=list)
    tracked_run: TrackedRun | None = None  # live and rescore entries
    not_recomputable: list[NotRecomputable] = Field(default_factory=list)
    reproduces: bool | None = None  # set by `reproduce run`; None = not run yet
    reproduces_note: str | None = None
    # Offline: the report's sha256-lf as the run that set `reproduces` compared it (`reproduce
    # run` prints it). Required once `reproduces` is set; check fails if the report changes.
    report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # A section added by hand after the generated part of a live report's .md, and why
    # (evaluation/reproduce/twins.py). It may only follow that part, never change it.
    md_addendum: str | None = Field(default=None, min_length=10)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("command")
    @classmethod
    def _python_m_evaluation(cls, command: list[str] | None) -> list[str] | None:
        if command is not None and (
            len(command) < 3 or command[:2] != ["python", "-m"] or not _MODULE.fullmatch(command[2])
        ):
            raise ValueError("a command must be `python -m evaluation.<module> [args]`")
        return command

    @model_validator(mode="after")
    def _offline_needs_a_backend(self) -> "Entry":
        if self.kind == "offline" and self.llm_backend is None:
            raise ValueError("an offline entry must set llm_backend: fake or local-model")
        if self.superseded_by is not None and self.role != "superseded":
            raise ValueError("only a superseded entry names superseded_by")
        return self

    @property
    def needs_model(self) -> bool:
        return self.llm_backend == "local-model"


class DataFile(_Model):
    path: RepoPath
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
    try:  # a duplicate key would silently keep the last value (e.g. a second `reproduces`)
        data: Any = yaml_unique(path.read_text(encoding="utf-8"))
    except DuplicateKeyError as exc:
        raise RegistryError([Issue(path.name, "duplicate_key", str(exc))]) from None
    try:
        return Registry.model_validate_json(json.dumps(data, default=str))
    except ValidationError as exc:
        issues = [
            Issue(f"{path.name}#{i.path}", i.code, i.message) for i in schema_issues(exc, Registry)
        ]
        raise RegistryError(issues) from None


__all__ = [
    "REGISTRY",
    "DataFile",
    "Entry",
    "Input",
    "NotRecomputable",
    "Registry",
    "RegistryError",
    "TrackedRun",
    "load_registry",
]
