import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL.endswith("/skillforge_test"):
    pytest.skip(
        "Tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.db.models import Project, SpecVersion, Compilation, Job
from backend.app.services.job_service import claim_next_job


engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def create_queued_job(db):
    project = Project(name="Job Service Test")
    db.add(project)
    db.flush()

    spec_version = SpecVersion(
        project_id=project.id,
        version_number=1,
        spec_data={},
    )
    db.add(spec_version)
    db.flush()

    compilation = Compilation(
        project_id=project.id,
        spec_version_id=spec_version.id,
        target_platform="claude_code",
        status="pending",
    )
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
    db.refresh(job)

    return job.id, compilation.id


def test_claim_next_job_updates_job_and_compilation(db):
    job_id, compilation_id = create_queued_job(db)

    job = claim_next_job(db)

    assert job is not None
    assert job.id == job_id
    assert job.status == "running"
    assert job.attempts == 1
    assert job.started_at is not None

    compilation = db.get(Compilation, compilation_id)

    assert compilation.status == "running"


def test_claim_next_job_returns_none_when_queue_is_empty(db):
    job = claim_next_job(db)

    assert job is None


def test_running_job_is_not_claimed_again(db):
    job_id, _ = create_queued_job(db)

    first_claim = claim_next_job(db)
    second_claim = claim_next_job(db)

    assert first_claim.id == job_id
    assert second_claim is None
