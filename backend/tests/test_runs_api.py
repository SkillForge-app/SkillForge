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
