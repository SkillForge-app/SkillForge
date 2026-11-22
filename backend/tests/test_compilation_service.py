import json
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL.endswith("/skillforge_test"):
    pytest.skip(
        "Tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.db.models import (
    Project, SpecVersion, Compilation, Job, Artifact
)
from backend.app.services.compilation_service import compile_job
from backend.tests.skillspec_fixtures import load_valid_spec


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


def create_running_job(db, platform="claude_code"):
    project = Project(name="Compilation Service Test")
    db.add(project)
    db.flush()

    spec_version = SpecVersion(
        project_id=project.id,
        version_number=1,
        spec_data=json.loads(json.dumps(load_valid_spec(), default=str)),
    )
    db.add(spec_version)
    db.flush()

    compilation = Compilation(
        project_id=project.id,
        spec_version_id=spec_version.id,
        target_platform=platform,
        status="running",
    )
    db.add(compilation)
    db.flush()

    job = Job(
        compilation_id=compilation.id,
        job_type="compiler_run",
        status="running",
        attempts=1,
    )
    db.add(job)
    db.commit()

    return job.id, compilation.id


@pytest.mark.parametrize("platform", ["claude_code", "codex"])
def test_compile_job_saves_artifacts(db, tmp_path, monkeypatch, platform):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    job_id, compilation_id = create_running_job(db, platform)

    compile_job(db, job_id)

    job = db.get(Job, job_id)
    compilation = db.get(Compilation, compilation_id)

    assert job.status == "completed"
    assert compilation.status == "completed"

    artifacts = db.execute(
        select(Artifact).where(
            Artifact.compilation_id == compilation_id
        )
    ).scalars().all()

    expected_files = {
        "claude_code": {
            "CLAUDE.md",
            ".claude/settings.json",
            ".claude/agents/ai-engineer.md",
            ".claude/commands/build-eval-set.md",
            ".claude/commands/design-rag.md",
            ".claude/commands/review-ai-risk.md",
        },
        "codex": {
            "AGENTS.md",
            ".codex/config.toml",
        },
    }

    assert {artifact.file_path for artifact in artifacts} == expected_files[platform]

    for artifact in artifacts:
        assert artifact.content_hash
        assert len(artifact.content_hash) == 64
        assert artifact.storage_url
        assert (tmp_path / artifact.storage_url).is_file()


def test_compile_job_marks_unsupported_platform_failed(
    db, tmp_path, monkeypatch
):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    job_id, compilation_id = create_running_job(
        db, platform="unsupported"
    )

    compile_job(db, job_id)

    job = db.get(Job, job_id)
    compilation = db.get(Compilation, compilation_id)

    assert job.status == "failed"
    assert compilation.status == "failed"
    assert "Unsupported target platform" in job.error_message

    artifacts = db.execute(
        select(Artifact).where(
            Artifact.compilation_id == compilation_id
        )
    ).scalars().all()

    assert artifacts == []
