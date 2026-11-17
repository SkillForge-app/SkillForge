from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.db.models import Project, SpecVersion, Compilation, Job, Artifact
from backend.app.schemas.runs import RunCreate, RunResponse, RunResultCreate


router = APIRouter(prefix="/api/v1/runs", tags=["Runs"])


def to_run_response(compilation: Compilation) -> RunResponse:
    return RunResponse(
        id=compilation.id,
        project_id=compilation.project_id,
        spec_version_id=compilation.spec_version_id,
        target_platform=compilation.target_platform,
        status=compilation.status,
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunCreate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(
        Project.id == payload.project_id
    ).first()

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    spec_version = db.query(SpecVersion).filter(
        SpecVersion.id == payload.spec_version_id,
        SpecVersion.project_id == payload.project_id,
    ).first()

    if spec_version is None:
        raise HTTPException(status_code=404, detail="Agent version not found")

    compilation = Compilation(
        project_id=payload.project_id,
        spec_version_id=payload.spec_version_id,
        target_platform=payload.target_platform,
        status="pending",
    )

    try:
        db.add(compilation)
        db.flush()

        job = Job(
            compilation_id=compilation.id,
            job_type="compiler_run",
            status="queued",
            attempts=0,
        )
        db.add(job)
        db.commit()
        db.refresh(compilation)

        return to_run_response(compilation)

    except Exception:
        db.rollback()
        raise


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    compilation = db.query(Compilation).filter(
        Compilation.id == run_id
    ).first()

    if compilation is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return to_run_response(compilation)


@router.post("/{run_id}/result", response_model=RunResponse)
def submit_run_result(
    run_id: UUID,
    payload: RunResultCreate,
    db: Session = Depends(get_db),
):
    compilation = db.query(Compilation).filter(
        Compilation.id == run_id
    ).first()

    if compilation is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if compilation.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail="Invalid run status transition",
        )

    now = datetime.now(timezone.utc)

    try:
        compilation.status = payload.status
        compilation.error_message = payload.error
        compilation.completed_at = now

        jobs = db.query(Job).filter(
            Job.compilation_id == compilation.id
        ).all()

        for job in jobs:
            job.status = payload.status
            if job.started_at is None:
                job.started_at = now
            job.completed_at = now
            job.error_message = payload.error

        for name, value in payload.artifacts.items():
            artifact = Artifact(
                compilation_id=compilation.id,
                file_path=name,
                file_type="file",
                storage_url=value,
            )
            db.add(artifact)

        db.commit()
        db.refresh(compilation)

        return to_run_response(compilation)

    except Exception:
        db.rollback()
        raise
