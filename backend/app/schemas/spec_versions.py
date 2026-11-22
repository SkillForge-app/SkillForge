from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SpecValidationRequest(BaseModel):
    spec: dict[str, Any]


class ValidationIssueResponse(BaseModel):
    path: str
    code: str
    message: str
    severity: str


class SpecValidationResponse(BaseModel):
    valid: bool
    errors: list[ValidationIssueResponse]
    warnings: list[ValidationIssueResponse]


class SpecVersionCreate(BaseModel):
    spec: dict[str, Any]


class SpecVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version_number: int
    spec_data: dict[str, Any]
    created_at: datetime


class SpecVersionDiffResponse(BaseModel):
    project_id: UUID
    from_version: int
    to_version: int
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    changed: list[dict[str, Any]]
