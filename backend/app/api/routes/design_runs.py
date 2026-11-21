import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.models import DesignRun, Project, SpecVersion
from backend.app.db.session import get_db
from backend.app.pipeline.core_adapter import PipelineUnavailable, get_pipeline
from backend.app.pipeline.outcome import DesignPipeline
from backend.app.queues import skills_queue
from backend.app.schemas.design_runs import (
    DesignRunAnswers,
    DesignRunCreate,
    DesignRunResponse,
)
from backend.app.services.design_runs import (
    claim_for_answers,
    create_run,
)


logger = logging.getLogger(__name__)

QUEUE_ERROR_MESSAGE = (
    "The design service is temporarily unavailable. Please try again."
)

router = APIRouter(prefix="/api/v1", tags=["Design Runs"])


def pipeline_dependency() -> DesignPipeline:
    """Ensure the AI pipeline is available."""
    try:
        return get_pipeline()
    except PipelineUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _response(db: Session, run: DesignRun) -> DesignRunResponse:
    version_number = None

    if run.spec_version_id is not None:
        version = db.get(SpecVersion, run.spec_version_id)
        version_number = version.version_number if version else None

    questions = []

    if run.status == "needs_input" and run.analyzed:
        questions = list(run.analyzed.get("questions", []))

    return DesignRunResponse(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        step=run.step,
        questions=questions,
        progress=list(run.progress or []),
        user_message=run.user_message,
        error_code=run.error_code,
        issues=list(run.issues or []),
        usage=dict(run.usage or {}),
        spec_version_id=run.spec_version_id,
        version_number=version_number,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


def _get_run(db: Session, run_id: UUID) -> DesignRun:
    run = db.get(DesignRun, run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Design run not found",
        )

    return run


@router.post(
    "/design-runs",
    response_model=DesignRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_design_run(
    payload: DesignRunCreate,
    db: Session = Depends(get_db),
    pipeline: DesignPipeline = Depends(pipeline_dependency),
):
    """Create a design run and enqueue its execution in RQ."""
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    run = create_run(
        db,
        payload.project_id,
        payload.request,
        payload.targets,
    )

    try:
        skills_queue.enqueue(
            "backend.app.services.design_runs.execute_start_job",
            str(run.id),
        )
    except Exception:
        logger.exception(
            "Failed to enqueue design run %s",
            run.id,
        )

        now = datetime.now(timezone.utc)

        run.status = "failed"
        run.error_code = "queue_unavailable"
        run.user_message = QUEUE_ERROR_MESSAGE
        run.updated_at = now
        run.completed_at = now

        db.commit()
        db.refresh(run)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR_MESSAGE,
        )

    return _response(db, run)


@router.get(
    "/design-runs/{run_id}",
    response_model=DesignRunResponse,
)
def get_design_run(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    run = _get_run(db, run_id)
    db.refresh(run)

    return _response(db, run)


@router.get(
    "/projects/{project_id}/design-runs",
    response_model=list[DesignRunResponse],
)
def list_design_runs(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    runs = (
        db.query(DesignRun)
        .filter(DesignRun.project_id == project_id)
        .order_by(DesignRun.created_at.desc(), DesignRun.id)
        .all()
    )

    return [_response(db, run) for run in runs]


@router.post(
    "/design-runs/{run_id}/answers",
    response_model=DesignRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def answer_design_run(
    run_id: UUID,
    payload: DesignRunAnswers,
    db: Session = Depends(get_db),
    pipeline: DesignPipeline = Depends(pipeline_dependency),
):
    """Submit answers and enqueue continuation of the design run in RQ."""
    run = _get_run(db, run_id)

    if run.status != "needs_input":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This run is {run.status}; it is not waiting for answers",
        )

    asked = {
        question["id"]
        for question in (run.analyzed or {}).get("questions", [])
    }

    unknown = sorted(
        {item.question_id for item in payload.answers} - asked
    )

    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Answers to questions that were not asked: {', '.join(unknown)}",
        )

    if not claim_for_answers(db, run_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This run is already continuing",
        )

    answers = [item.model_dump() for item in payload.answers]

    try:
        skills_queue.enqueue(
            "backend.app.services.design_runs.execute_answers_job",
            str(run_id),
            answers,
        )
    except Exception:
        logger.exception(
            "Failed to enqueue answers for design run %s",
            run_id,
        )

        run.status = "needs_input"
        run.error_code = "queue_unavailable"
        run.user_message = QUEUE_ERROR_MESSAGE
        run.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(run)

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_ERROR_MESSAGE,
        )

    db.refresh(run)

    return _response(db, run)