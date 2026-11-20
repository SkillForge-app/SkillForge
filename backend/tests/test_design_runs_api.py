import os
from contextlib import nullcontext
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Only allow this test module to run against the dedicated test DB.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL.endswith("/skillforge_test"):
    pytest.skip(
        "Tests require DATABASE_URL pointing to skillforge_test",
        allow_module_level=True,
    )

from backend.app.api.routes.design_runs import pipeline_dependency
from backend.app.db.models import DesignRun
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.pipeline.outcome import StepOutcome
from backend.app.services.design_runs import get_session_factory
from backend.tests.pipeline_stubs import ScriptedPipeline, analyzed, ok, valid_spec


engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@pytest.fixture
def session():
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def make_client(session):
    """make_client(pipeline) -> TestClient that uses `pipeline` and the test's transaction.

    The background task opens its own session in production; here it gets the test session, so
    its writes are visible to the test and are rolled back at the end.
    """
    def build(pipeline):
        def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[pipeline_dependency] = lambda: pipeline
        app.dependency_overrides[get_session_factory] = lambda: (lambda: nullcontext(session))
        client = TestClient(app)
        return client

    try:
        yield build
    finally:
        for key in (get_db, pipeline_dependency, get_session_factory):
            app.dependency_overrides.pop(key, None)


def create_project(client):
    response = client.post(
        "/api/v1/projects",
        json={"name": f"Design Run Test {uuid4()}", "description": "Design run API test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def start_run(client, project_id, **extra):
    return client.post(
        "/api/v1/design-runs",
        json={"project_id": project_id, "request": "I need an AI engineer skill", **extra},
    )


def happy_pipeline():
    return ScriptedPipeline(
        analyze=ok("analyze", analyzed(), usage={"calls": 2, "cost_usd": 0.01}),
        design=ok("design", valid_spec(), usage={"calls": 1, "cost_usd": 0.05}),
    )


def questions_pipeline():
    return ScriptedPipeline(
        analyze=StepOutcome(step="analyze", status="needs_input", value=analyzed(questions=True)),
        clarify=ok("clarify", analyzed()),
        design=ok("design", valid_spec()),
    )


def test_a_run_designs_a_skill_and_stores_it_as_a_spec_version(make_client):
    client = make_client(happy_pipeline())
    project_id = create_project(client)

    response = start_run(client, project_id, targets=["claude", "codex"])

    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert response.json()["status"] == "queued"

    run = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert run["status"] == "completed"
    assert run["step"] == "design"
    assert run["version_number"] == 1
    assert run["completed_at"] is not None
    assert run["usage"]["calls"] == 3
    assert [event["stage"] for event in run["progress"]] == ["started", "done"]

    versions = client.get(f"/api/v1/projects/{project_id}/versions").json()
    assert [item["id"] for item in versions] == [run["spec_version_id"]]
    assert versions[0]["spec_data"]["skill"]["name"] == "ai-engineer"


def test_the_pipeline_gets_the_text_and_the_chosen_targets(make_client):
    pipeline = happy_pipeline()
    client = make_client(pipeline)

    start_run(client, create_project(client), targets=["claude", "claude", "codex"])

    assert pipeline.calls[0] == ("analyze", ("I need an AI engineer skill", ["claude", "codex"]))


def test_a_second_run_creates_the_next_version(make_client):
    client = make_client(happy_pipeline())
    project_id = create_project(client)

    start_run(client, project_id)
    second = start_run(client, project_id).json()["id"]

    assert client.get(f"/api/v1/design-runs/{second}").json()["version_number"] == 2


def test_questions_are_shown_and_answers_finish_the_design(make_client):
    pipeline = questions_pipeline()
    client = make_client(pipeline)
    project_id = create_project(client)

    run_id = start_run(client, project_id).json()["id"]
    waiting = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert waiting["status"] == "needs_input"
    assert [item["id"] for item in waiting["questions"]] == ["q1", "q2", "q3"]
    assert waiting["spec_version_id"] is None

    response = client.post(
        f"/api/v1/design-runs/{run_id}/answers",
        json={"answers": [{"question_id": "q1", "text": "Python"}, {"question_id": "q2"}]},
    )

    assert response.status_code == 202, response.text
    finished = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert finished["status"] == "completed"
    assert finished["questions"] == []
    assert finished["version_number"] == 1
    assert pipeline.steps == ["analyze", "clarify", "design"]
    assert pipeline.calls[1][1][1] == [
        {"question_id": "q1", "text": "Python"},
        {"question_id": "q2", "text": None},
    ]


def test_answers_are_refused_unless_the_run_is_waiting_for_them(make_client):
    client = make_client(happy_pipeline())
    run_id = start_run(client, create_project(client)).json()["id"]

    response = client.post(f"/api/v1/design-runs/{run_id}/answers", json={"answers": []})

    assert response.status_code == 409


def test_answers_to_questions_that_were_not_asked_are_refused(make_client):
    client = make_client(questions_pipeline())
    run_id = start_run(client, create_project(client)).json()["id"]

    response = client.post(
        f"/api/v1/design-runs/{run_id}/answers",
        json={"answers": [{"question_id": "q5", "text": "x"}]},
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/design-runs/{run_id}").json()["status"] == "needs_input"


def test_answers_cannot_be_sent_twice(make_client):
    client = make_client(questions_pipeline())
    run_id = start_run(client, create_project(client)).json()["id"]
    url = f"/api/v1/design-runs/{run_id}/answers"

    assert client.post(url, json={"answers": []}).status_code == 202
    assert client.post(url, json={"answers": []}).status_code == 409


def test_a_blocked_request_stores_nothing(make_client, session):
    pipeline = ScriptedPipeline(
        analyze=StepOutcome(
            step="analyze",
            status="blocked",
            user_message="We can't create this skill.",
            error_code="blocked.fraud_scams",
        )
    )
    client = make_client(pipeline)
    project_id = create_project(client)

    run_id = start_run(client, project_id).json()["id"]

    run = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert run["status"] == "blocked"
    assert run["user_message"] == "We can't create this skill."
    assert run["error_code"] == "blocked.fraud_scams"
    assert run["spec_version_id"] is None
    assert client.get(f"/api/v1/projects/{project_id}/versions").json() == []
    assert session.get(DesignRun, run_id).analyzed is None
    assert pipeline.steps == ["analyze"]


@pytest.mark.parametrize("status", ["retry_later", "failed"])
def test_provider_problems_are_reported_without_a_version(make_client, status):
    pipeline = ScriptedPipeline(
        analyze=ok("analyze", analyzed()),
        design=StepOutcome(
            step="design", status=status, user_message="Try again.", error_code="provider_unavailable"
        ),
    )
    client = make_client(pipeline)
    project_id = create_project(client)

    run_id = start_run(client, project_id).json()["id"]

    run = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert run["status"] == status
    assert run["user_message"] == "Try again."
    assert client.get(f"/api/v1/projects/{project_id}/versions").json() == []


def test_a_spec_the_backend_rejects_is_not_stored(make_client):
    broken = valid_spec()
    broken["spec_version"] = "999"
    pipeline = ScriptedPipeline(analyze=ok("analyze", analyzed()), design=ok("design", broken))
    client = make_client(pipeline)
    project_id = create_project(client)

    run_id = start_run(client, project_id).json()["id"]

    run = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error_code"] == "invalid_spec"
    assert run["issues"]
    assert client.get(f"/api/v1/projects/{project_id}/versions").json() == []


def test_a_crashing_pipeline_gives_a_failed_run_without_details(make_client):
    class Crashing(ScriptedPipeline):
        async def analyze(self, text, targets):
            raise RuntimeError("secret internal detail")

    client = make_client(Crashing())
    run_id = start_run(client, create_project(client)).json()["id"]

    run = client.get(f"/api/v1/design-runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error_code"] == "internal_error"
    assert "secret internal detail" not in str(run)


def test_invalid_requests_and_unknown_ids(make_client):
    client = make_client(happy_pipeline())
    project_id = create_project(client)

    assert start_run(client, str(uuid4())).status_code == 404
    assert client.post(
        "/api/v1/design-runs", json={"project_id": project_id, "request": "   "}
    ).status_code == 422
    assert client.post(
        "/api/v1/design-runs",
        json={"project_id": project_id, "request": "x", "targets": ["bing"]},
    ).status_code == 422
    assert client.get(f"/api/v1/design-runs/{uuid4()}").status_code == 404
    assert client.get(f"/api/v1/projects/{uuid4()}/design-runs").status_code == 404


def test_list_design_runs_of_a_project(make_client):
    client = make_client(happy_pipeline())
    project_id = create_project(client)
    first = start_run(client, project_id).json()["id"]
    second = start_run(client, project_id).json()["id"]

    listing = client.get(f"/api/v1/projects/{project_id}/design-runs")

    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()} == {first, second}


def test_a_completed_run_can_be_queued_for_compilation(make_client):
    client = make_client(happy_pipeline())
    project_id = create_project(client)
    run_id = start_run(client, project_id).json()["id"]
    finished = client.get(f"/api/v1/design-runs/{run_id}").json()

    response = client.post(
        "/api/v1/runs",
        json={
            "project_id": project_id,
            "spec_version_id": finished["spec_version_id"],
            "target_platform": "claude_code",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
