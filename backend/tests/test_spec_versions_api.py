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
    return json.loads(json.dumps(yaml.safe_load(path.read_text(encoding="utf-8-sig")), default=str))


def create_project(client):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": f"Spec API Test {uuid4()}",
            "description": "Testing SkillSpec versions",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_validate_valid_skillspec(client):
    response = client.post(
        "/api/v1/specs/validate",
        json={"spec": load_valid_spec()},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["errors"] == []


def test_validate_invalid_skillspec(client):
    response = client.post(
        "/api/v1/specs/validate",
        json={"spec": {}},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert len(response.json()["errors"]) > 0


def test_create_and_list_spec_versions(client):
    project_id = create_project(client)
    spec = load_valid_spec()

    first = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": spec},
    )

    assert first.status_code == 201
    assert first.json()["version_number"] == 1

    second = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": spec},
    )

    assert second.status_code == 201
    assert second.json()["version_number"] == 2

    response = client.get(
        f"/api/v1/projects/{project_id}/versions"
    )

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["version_number"] == 2


def test_diff_spec_versions(client):
    project_id = create_project(client)

    first_spec = load_valid_spec()
    second_spec = load_valid_spec()
    second_spec["skill"]["summary"] = "Updated summary for diff test"

    first = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": first_spec},
    )
    second = client.post(
        f"/api/v1/projects/{project_id}/versions",
        json={"spec": second_spec},
    )

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get(
        f"/api/v1/projects/{project_id}/versions/diff",
        params={"from_version": 1, "to_version": 2},
    )

    assert response.status_code == 200
    assert len(response.json()["changed"]) > 0
    assert any(
        item["path"] == "skill.summary"
        for item in response.json()["changed"]
    )
