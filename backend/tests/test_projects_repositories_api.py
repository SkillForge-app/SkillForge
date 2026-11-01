import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Only allow this test module to run against the dedicated test DB.
database_url = os.environ.get("DATABASE_URL", "")
if not database_url.endswith("/skillforge_test"):
    pytest.skip(
        "Task 12 tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.main import app
from backend.app.db.session import get_db

engine = create_engine(database_url, pool_pre_ping=True)


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


def create_project(client):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": f"Task 12 Test {uuid4()}",
            "description": "Automated API test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_repository(client, project_id):
    response = client.post(
        f"/api/v1/projects/{project_id}/repositories",
        json={
            "provider": "github",
            "repository_url": "https://github.com/example/test-repo",
            "default_branch": "main",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_crud(client):
    project = create_project(client)
    project_id = project["id"]

    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["id"] == project_id

    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    assert any(p["id"] == project_id for p in response.json())

    response = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Updated Task 12 Project"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Task 12 Project"

    response = client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 404


def test_repository_crud(client):
    project = create_project(client)
    project_id = project["id"]

    repository = create_repository(client, project_id)
    repository_id = repository["id"]

    assert repository["project_id"] == project_id

    response = client.get(f"/api/v1/repositories/{repository_id}")
    assert response.status_code == 200
    assert response.json()["id"] == repository_id

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories"
    )
    assert response.status_code == 200
    assert any(r["id"] == repository_id for r in response.json())

    response = client.patch(
        f"/api/v1/repositories/{repository_id}",
        json={"default_branch": "develop"},
    )
    assert response.status_code == 200
    assert response.json()["default_branch"] == "develop"

    response = client.delete(f"/api/v1/repositories/{repository_id}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/repositories/{repository_id}")
    assert response.status_code == 404


def test_missing_resources_return_404(client):
    missing_id = str(uuid4())

    assert client.get(
        f"/api/v1/projects/{missing_id}"
    ).status_code == 404

    assert client.get(
        f"/api/v1/repositories/{missing_id}"
    ).status_code == 404

    assert client.post(
        f"/api/v1/projects/{missing_id}/repositories",
        json={
            "provider": "github",
            "repository_url": "https://github.com/example/repo",
            "default_branch": "main",
        },
    ).status_code == 404


def test_invalid_project_returns_422(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": ""},
    )
    assert response.status_code == 422


def test_invalid_repository_returns_422(client):
    project = create_project(client)

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories",
        json={
            "provider": "github",
            "repository_url": "not-a-valid-url",
        },
    )
    assert response.status_code == 422


def test_project_with_repository_cannot_be_deleted(client):
    project = create_project(client)
    create_repository(client, project["id"])

    response = client.delete(
        f"/api/v1/projects/{project['id']}"
    )
    assert response.status_code == 409, response.text
