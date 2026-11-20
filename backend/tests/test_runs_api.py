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
        "Tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.main import app
from backend.app.db.session import get_db


engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@pytest.fixture
def client():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
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


def create_run(client):
    project = client.post(
        "/api/v1/projects",
        json={
            "name": f"Runs API Test {uuid4()}",
            "description": "Testing compiler runs",
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    version = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": load_valid_spec()},
    )
    assert version.status_code == 201

    response = client.post(
        "/api/v1/runs",
        json={
            "project_id": project_id,
            "spec_version_id": version.json()["id"],
            "target_platform": "claude_code",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_and_get_run(client):
    run = create_run(client)

    assert run["status"] == "pending"
    assert run["target_platform"] == "claude_code"

    response = client.get(f"/api/v1/runs/{run['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == run["id"]
    assert response.json()["status"] == "pending"


def test_create_run_with_missing_project_returns_404(client):
    response = client.post(
        "/api/v1/runs",
        json={
            "project_id": str(uuid4()),
            "spec_version_id": str(uuid4()),
            "target_platform": "claude_code",
        },
    )

    assert response.status_code == 404


def test_get_missing_run_returns_404(client):
    response = client.get(f"/api/v1/runs/{uuid4()}")

    assert response.status_code == 404


def test_submit_run_result_and_reject_duplicate(client):
    run = create_run(client)

    result = client.post(
        f"/api/v1/runs/{run['id']}/result",
        json={
            "status": "completed",
            "artifacts": {
                "CLAUDE.md": "generated/CLAUDE.md",
            },
        },
    )

    assert result.status_code == 200
    assert result.json()["status"] == "completed"

    duplicate = client.post(
        f"/api/v1/runs/{run['id']}/result",
        json={"status": "completed"},
    )

    assert duplicate.status_code == 409


def test_download_is_refused_until_the_run_is_completed(client):
    run = create_run(client)

    response = client.get(f"/api/v1/runs/{run['id']}/download")

    assert response.status_code == 409


def test_download_of_an_unknown_run_is_404(client):
    assert client.get(f"/api/v1/runs/{uuid4()}/download").status_code == 404


def test_download_returns_the_compiled_files_as_a_zip(client, tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile

    from backend.app.core.config import settings
    from backend.app.services.compilation_service import compile_job
    from backend.app.services.job_service import claim_next_job
    from backend.app.db.session import get_db as real_get_db

    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)
    run = create_run(client)

    db = next(app.dependency_overrides[real_get_db]())
    job = claim_next_job(db)
    compile_job(db, job.id)

    response = client.get(f"/api/v1/runs/{run['id']}/download")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert names, "the zip has no files"
        for name in names:
            on_disk = (tmp_path / run["id"] / name).read_bytes()
            assert archive.read(name) == on_disk
            assert hashlib.sha256(on_disk).hexdigest()
