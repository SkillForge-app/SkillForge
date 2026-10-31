
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue
from sqlalchemy import DateTime, ForeignKey

from backend.app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            name="fk_repositories_project",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    repository_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(
        String(255),
        server_default=text("'main'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_repositories_project_id", "project_id"),
    )


class SpecVersion(Base):
    __tablename__ = "spec_versions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_spec_versions_project"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "version_number",
            name="uq_project_spec_version",
        ),
        UniqueConstraint(
            "id", "project_id",
            name="uq_spec_version_project",
        ),
        CheckConstraint(
            "version_number > 0",
            name="chk_spec_version_positive",
        ),
        Index("idx_spec_versions_project_id", "project_id"),
    )


class Compilation(Base):
    __tablename__ = "compilations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_compilations_project"),
        nullable=False,
    )
    spec_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    target_platform: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["spec_version_id", "project_id"],
            ["spec_versions.id", "spec_versions.project_id"],
            name="fk_compilations_spec_version",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_compilation_status",
        ),
        Index("idx_compilations_project_id", "project_id"),
        Index("idx_compilations_spec_version_id", "spec_version_id"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    compilation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("compilations.id", name="fk_jobs_compilation"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'queued'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_job_status",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="chk_job_attempts",
        ),
        Index("idx_jobs_compilation_id", "compilation_id"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    compilation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("compilations.id", name="fk_artifacts_compilation"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    storage_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint(
            "compilation_id", "file_path",
            name="uq_artifact_compilation_path",
        ),
        Index("idx_artifacts_compilation_id", "compilation_id"),
    )
