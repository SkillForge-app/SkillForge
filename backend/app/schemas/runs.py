from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    spec_version_id: UUID
    target_platform: Literal["claude_code", "codex"]


class RunResponse(BaseModel):
    id: UUID
    project_id: UUID
    spec_version_id: UUID
    target_platform: str
    status: Literal["pending", "running", "completed", "failed"]


class RunResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed"]
    artifacts: dict[str, str] = {}
    error: str | None = None
