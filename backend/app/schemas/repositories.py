
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RepositoryCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    repository_url: HttpUrl
    default_branch: str = Field(
        default="main",
        min_length=1,
        max_length=255,
    )


class RepositoryUpdate(BaseModel):
    provider: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    repository_url: HttpUrl | None = None
    default_branch: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    provider: str
    repository_url: str
    default_branch: str | None
    created_at: datetime
