from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.models import DesignRun, Project, SpecVersion
from backend.app.db.session import get_db
from backend.app.pipeline.core_adapter import PipelineUnavailable, get_pipeline
from backend.app.pipeline.outcome import DesignPipeline
from backend.app.schemas.design_runs import (
    DesignRunAnswers,
    DesignRunCreate,
    DesignRunResponse,
)
from backend.app.services.design_runs import (
    SessionFactory,
    claim_for_answers,
    create_run,
    execute_answers,
    execute_start,
    get_session_factory,
)


router = APIRouter(prefix="/api/v1", tags=["Design Runs"])


def pipeline_dependency() -> DesignPipeline:
    """The AI pipeline. Tests replace this with a stub through `app.dependency_overrides`."""
    try:
        return get_pipeline()
    except PipelineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


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
        raise HTTPException(status_code=404, detail="Design run not found")
    return run


@router.post(
    "/design-runs",
    response_model=DesignRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_design_run(
    payload: DesignRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    pipeline: DesignPipeline = Depends(pipeline_dependency),
    session_factory: SessionFactory = Depends(get_session_factory),
):
    """Start a design run. It returns at once; poll GET /design-runs/{id} for the progress."""
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    run = create_run(db, payload.project_id, payload.request, payload.targets)
    background_tasks.add_task(execute_start, session_factory, pipeline, run.id)
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
    db.refresh(run)  # a background task may have saved newer state than this session has cached
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
        raise HTTPException(status_code=404, detail="Project not found")

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    pipeline: DesignPipeline = Depends(pipeline_dependency),
    session_factory: SessionFactory = Depends(get_session_factory),
):
    """Answer the clarifying questions (any of them may be skipped) and continue the design."""
    run = _get_run(db, run_id)

    if run.status != "needs_input":
        raise HTTPException(
            status_code=409,
            detail=f"This run is {run.status}; it is not waiting for answers",
        )

    asked = {question["id"] for question in (run.analyzed or {}).get("questions", [])}
    unknown = sorted({item.question_id for item in payload.answers} - asked)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Answers to questions that were not asked: {', '.join(unknown)}",
        )

    if not claim_for_answers(db, run_id):
        raise HTTPException(status_code=409, detail="This run is already continuing")

    answers = [item.model_dump() for item in payload.answers]
    background_tasks.add_task(execute_answers, session_factory, pipeline, run_id, answers)

    db.refresh(run)
    return _response(db, run)
