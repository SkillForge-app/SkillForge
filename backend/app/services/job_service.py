from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Compilation, Job


def claim_next_job(db: Session) -> Job | None:
    """Atomically claim the oldest queued compiler job."""

    try:
        statement = (
            select(Job)
            .where(
                Job.status == "queued",
                Job.job_type == "compiler_run",
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        job = db.execute(statement).scalars().first()

        if job is None:
            db.commit()
            return None

        compilation = db.get(Compilation, job.compilation_id)

        if compilation is None:
            job.status = "failed"
            job.error_message = "Associated compilation was not found."
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return None

        if compilation.status not in ("pending", "running"):
            job.status = "failed"
            job.error_message = "Compilation is not in a processable state."
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return None

        now = datetime.now(timezone.utc)

        job.status = "running"
        job.attempts += 1
        job.started_at = now
        job.completed_at = None
        job.error_message = None

        compilation.status = "running"
        compilation.error_message = None
        compilation.completed_at = None

        db.commit()
        db.refresh(job)

        return job

    except Exception:
        db.rollback()
        raise
