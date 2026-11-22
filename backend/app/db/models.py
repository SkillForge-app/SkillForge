from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_repositories_project", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    repository_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(
        String(255), server_default=text("'main'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_repositories_project_id", "project_id"),
    )


class SpecVersion(Base):
    __tablename__ = "spec_versions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
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
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_project_spec_version"),
        UniqueConstraint("id", "project_id", name="uq_spec_version_project"),
        CheckConstraint("version_number > 0", name="chk_spec_version_positive"),
        Index("idx_spec_versions_project_id", "project_id"),
    )


class Compilation(Base):
    __tablename__ = "compilations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_compilations_project"),
        nullable=False,
    )
    spec_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    compilation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("compilations.id", name="fk_jobs_compilation"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'queued'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_job_status",
        ),
        CheckConstraint("attempts >= 0", name="chk_job_attempts"),
        Index("idx_jobs_compilation_id", "compilation_id"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
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
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("compilation_id", "file_path", name="uq_artifact_compilation_path"),
        Index("idx_artifacts_compilation_id", "compilation_id"),
    )


class DesignRun(Base):
    """One run of the AI pipeline (analyze, clarify, design) for a project.

    A completed run points to the spec version it created. `analyzed` holds the analyzed request
    while the run waits for answers; it is cleared when the request is blocked.
    """

    __tablename__ = "design_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_design_runs_project"),
        nullable=False,
    )
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    selected_targets: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'queued'"),
    )
    step: Mapped[str | None] = mapped_column(String(30))
    analyzed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progress: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    user_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    spec_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("spec_versions.id", name="fk_design_runs_spec_version"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'needs_input', 'completed', "
            "'blocked', 'retry_later', 'failed')",
            name="chk_design_run_status",
        ),
        Index("idx_design_runs_project_id", "project_id"),
    )


# ---------------------------------------------------------------------------
# Evaluation Schema v2
# ---------------------------------------------------------------------------


class EvaluationTask(Base):
    """Reusable definition of an AI evaluation task."""

    __tablename__ = "evaluation_tasks"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dataset_version: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("name", "task_type", name="uq_evaluation_task_name_type"),
        Index("idx_evaluation_tasks_task_type", "task_type"),
    )


class EvaluationExperiment(Base):
    """Groups evaluation runs under a named experiment."""

    __tablename__ = "evaluation_experiments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        Index("idx_evaluation_experiments_name", "name"),
    )


class EvaluationRun(Base):
    """A single execution of an evaluation task."""

    __tablename__ = "evaluation_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evaluation_tasks.id", name="fk_evaluation_runs_task", ondelete="RESTRICT"),
        nullable=False,
    )
    experiment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "evaluation_experiments.id",
            name="fk_evaluation_runs_experiment",
            ondelete="SET NULL",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'queued'"),
    )
    split: Mapped[str | None] = mapped_column(String(100))
    live: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    model: Mapped[str | None] = mapped_column(String(255))
    prompt_id: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    data_sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    report_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    gates: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_evaluation_run_status",
        ),
        CheckConstraint(
            "prompt_version IS NULL OR prompt_version > 0",
            name="chk_evaluation_run_prompt_version",
        ),
        Index("idx_evaluation_runs_task_id", "task_id"),
        Index("idx_evaluation_runs_experiment_id", "experiment_id"),
        Index("idx_evaluation_runs_status", "status"),
        Index("idx_evaluation_runs_created_at", "created_at"),
    )


class EvaluationArtifact(Base):
    """A report or raw output file generated by an evaluation run."""

    __tablename__ = "evaluation_artifacts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", name="fk_evaluation_artifacts_run", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    storage_url: Mapped[str | None] = mapped_column(Text)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "file_path", name="uq_evaluation_artifact_run_path"),
        Index("idx_evaluation_artifacts_run_id", "run_id"),
        Index("idx_evaluation_artifacts_type", "artifact_type"),
    )


class EvaluationScore(Base):
    """A numeric metric produced by an evaluation run."""

    __tablename__ = "evaluation_scores"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", name="fk_evaluation_scores_run", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "metric_name", name="uq_evaluation_score_run_metric"),
        Index("idx_evaluation_scores_run_id", "run_id"),
        Index("idx_evaluation_scores_metric_name", "metric_name"),
    )
