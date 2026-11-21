"""Store and drive design runs: the database side of pipeline/runner.py.

The API starts a run and returns at once (202); `execute_start` and `execute_answers` then run in
a FastAPI background task, in the API process. That is enough for the demo. When the queue is
chosen (compose.yaml: RQ, recommended), these two functions are what the worker calls instead.
They block the event loop for the few milliseconds of each database write; the pipeline's own
network calls are awaited as normal.
"""
import asyncio
from backend.app.pipeline.core_adapter import get_pipeline
import copy
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.models import DesignRun, SpecVersion
from backend.app.pipeline import runner
from backend.app.pipeline.outcome import DesignPipeline
from backend.app.pipeline.runner import TERMINAL_STATUSES, RunState

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Please try again in a few minutes."


@contextmanager
def session_scope():
    """A session for a background task, which runs after the request's own session is closed."""
    from backend.app.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_session_factory() -> SessionFactory:
    """FastAPI dependency. Tests replace it so background work uses the test's transaction."""
    return session_scope


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_run(db: Session, project_id: UUID, request_text: str, targets: Sequence[str]) -> DesignRun:
    run = DesignRun(
        project_id=project_id,
        request_text=request_text,
        selected_targets=list(targets),
        status="queued",
        progress=[],
        issues=[],
        usage={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def claim_for_answers(db: Session, run_id: UUID) -> bool:
    """Move needs_input -> running in one statement, so two answer requests cannot both win."""
    claimed = (
        db.query(DesignRun)
        .filter(DesignRun.id == run_id, DesignRun.status == "needs_input")
        .update({"status": "running", "updated_at": _now()}, synchronize_session=False)
    )
    db.commit()
    return claimed == 1


def existing_skill_names(db: Session, project_id: UUID) -> list[str]:
    """Skill names used by other projects, so the Architect picks a name that is still free."""
    rows = (
        db.query(SpecVersion.spec_data["skill"]["name"].astext)
        .filter(SpecVersion.project_id != project_id)
        .distinct()
        .all()
    )
    return sorted(name for (name,) in rows if name)


def to_state(run: DesignRun) -> RunState:
    return RunState(
        status=run.status,
        step=run.step,
        analyzed=copy.deepcopy(run.analyzed) if run.analyzed is not None else None,
        progress=list(run.progress or []),
        user_message=run.user_message,
        error_code=run.error_code,
        issues=list(run.issues or []),
        usage={**(run.usage or {})},
    )


def apply_state(run: DesignRun, state: RunState) -> None:
    # New objects every time: SQLAlchemy does not see changes made inside a JSONB value.
    run.status = state.status
    run.step = state.step
    run.analyzed = copy.deepcopy(state.analyzed) if state.analyzed is not None else None
    run.progress = list(state.progress)
    run.issues = list(state.issues)
    run.usage = dict(state.usage)
    run.user_message = state.user_message
    run.error_code = state.error_code
    run.updated_at = _now()
    if state.status in TERMINAL_STATUSES and run.completed_at is None:
        run.completed_at = run.updated_at


def add_spec_version(db: Session, project_id: UUID, spec: dict[str, Any]) -> SpecVersion:
    latest = (
        db.query(func.max(SpecVersion.version_number))
        .filter(SpecVersion.project_id == project_id)
        .scalar()
    )
    version = SpecVersion(
        project_id=project_id,
        version_number=(latest or 0) + 1,
        spec_data=spec,
    )
    db.add(version)
    db.flush()
    return version


def _saver(db: Session, run: DesignRun) -> Callable[[RunState], None]:
    def save(state: RunState) -> None:
        apply_state(run, state)
        # The spec version and the "completed" status are committed together, so a client that
        # sees "completed" always finds the version.
        if state.status == "completed" and state.spec is not None and run.spec_version_id is None:
            run.spec_version_id = add_spec_version(db, run.project_id, state.spec).id
        db.commit()

    return save


async def execute_start(session_factory: SessionFactory, pipeline: DesignPipeline, run_id: UUID) -> None:
    await _execute(session_factory, run_id, lambda db, run, save: runner.start(
        pipeline,
        to_state(run),
        run.request_text,
        run.selected_targets,
        existing_skill_names(db, run.project_id),
        save=save,
    ))


async def execute_answers(
    session_factory: SessionFactory,
    pipeline: DesignPipeline,
    run_id: UUID,
    answers: Sequence[dict[str, Any]],
) -> None:
    def call(db: Session, run: DesignRun, save: Callable[[RunState], None]):
        state = to_state(run)
        # claim_for_answers already moved the row to "running"; the runner expects the state the
        # run was claimed from.
        state.status = "needs_input"
        return runner.answer(
            pipeline, state, answers, existing_skill_names(db, run.project_id), save=save
        )

    await _execute(session_factory, run_id, call)


async def _execute(session_factory: SessionFactory, run_id: UUID, call: Callable[..., Any]) -> None:
    with session_factory() as db:
        run = db.get(DesignRun, run_id)
        if run is None:
            logger.error("Design run %s vanished before it could start", run_id)
            return

        try:
            await call(db, run, _saver(db, run))
        except Exception:
            # Details go to the log only; the user gets the generic message.
            logger.exception("Design run %s crashed", run_id)
            db.rollback()
            run = db.get(DesignRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error_code = "internal_error"
                run.user_message = INTERNAL_ERROR_MESSAGE
                run.updated_at = _now()
                run.completed_at = run.updated_at
                db.commit()
def _mark_pipeline_initialization_failed(run_id: UUID) -> None:
    with session_scope() as db:
        run = db.get(DesignRun, run_id)

        if run is None:
            logger.error(
                "Design run %s not found after pipeline initialization failure",
                run_id,
            )
            return

        run.status = "failed"
        run.error_code = "internal_error"
        run.user_message = INTERNAL_ERROR_MESSAGE
        run.updated_at = _now()
        run.completed_at = run.updated_at
        db.commit()


def execute_start_job(run_id: str) -> None:
    parsed_run_id = UUID(run_id)

    try:
        pipeline = get_pipeline()
    except Exception:
        logger.exception(
            "Failed to initialize pipeline for design run %s",
            parsed_run_id,
        )
        _mark_pipeline_initialization_failed(parsed_run_id)
        return

    asyncio.run(
        execute_start(
            session_scope,
            pipeline,
            parsed_run_id,
        )
    )


def execute_answers_job(
    run_id: str,
    answers: list[dict[str, Any]],
) -> None:
    parsed_run_id = UUID(run_id)

    try:
        pipeline = get_pipeline()
    except Exception:
        logger.exception(
            "Failed to initialize pipeline for design run %s",
            parsed_run_id,
        )
        _mark_pipeline_initialization_failed(parsed_run_id)
        return

    asyncio.run(
        execute_answers(
            session_scope,
            pipeline,
            parsed_run_id,
            answers,
        )
    )