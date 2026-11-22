import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL.endswith("/skillforge_test"):
    pytest.skip(
        "End-to-end tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.db.models import Artifact, Job


engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@pytest.fixture
def client_and_db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client, session, connection
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        transaction.rollback()
        connection.close()


def load_valid_spec():
    path = Path(__file__).parent / "fixtures" / "skillspec.yaml"
    return json.loads(
        json.dumps(
            yaml.safe_load(path.read_text(encoding="utf-8-sig")),
            default=str,
        )
    )


def test_design_spec_compile_end_to_end(
    client_and_db,
    monkeypatch,
    tmp_path,
):
    client, session, connection = client_and_db
    spec = load_valid_spec()

    # 1. Create a project through the API.
    project_response = client.post(
        "/api/v1/projects",
        json={
            "name": f"End-to-End Test {uuid4()}",
            "description": "Design to SkillSpec to compiler integration test",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    # 2. Validate the SkillSpec through the API.
    validation_response = client.post(
        "/api/v1/specs/validate",
        json={"spec": spec},
    )
    assert validation_response.status_code == 200, validation_response.text
    assert validation_response.json()["valid"] is True
    assert validation_response.json()["errors"] == []

    # 3. Save a version of the validated SkillSpec.
    version_response = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": spec},
    )
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()
    assert version["version_number"] == 1

    # 4. Request a Claude Code compilation through the API.
    run_response = client.post(
        "/api/v1/runs",
        json={
            "project_id": project_id,
            "spec_version_id": version["id"],
            "target_platform": "claude_code",
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    run_id = run["id"]
    assert run["status"] == "pending"

    # 5. Run the real worker using the test transaction's connection.
    from backend.app import worker
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    def test_session_factory():
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    monkeypatch.setattr(worker, "SessionLocal", test_session_factory)

    assert worker.process_one_job() is True

    # 6. Verify the completed run through the API.
    completed_response = client.get(f"/api/v1/runs/{run_id}")
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

    # 7. Verify the job was completed successfully.
    job = session.query(Job).filter_by(
        compilation_id=run_id,
    ).one()
    assert job.status == "completed"
    assert job.attempts == 1

    # 8. Verify the artifact record and generated file.
    artifacts = session.query(Artifact).filter_by(
        compilation_id=run_id,
    ).all()

    assert artifacts
    assert any(Path(artifact.file_path).name == "CLAUDE.md" for artifact in artifacts)
    assert any(artifact.content_hash for artifact in artifacts)

    generated_files = list(tmp_path.rglob("CLAUDE.md"))
    assert generated_files
    assert generated_files[0].is_file()
    assert generated_files[0].read_text(encoding="utf-8").strip()
