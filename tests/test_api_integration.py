from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import ApiSettings


def _client(tmp_path):
    settings = ApiSettings(
        database_path=tmp_path / "api.db",
        agent_token="agent-secret",
        worker_token="worker-secret",
    )
    return TestClient(create_app(settings))


def test_async_job_contract_from_submission_through_worker_completion(tmp_path):
    client = _client(tmp_path)
    agent_headers = {"Authorization": "Bearer agent-secret"}
    worker_headers = {"Authorization": "Bearer worker-secret"}

    response = client.post(
        "/v1/poetry/jobs/generate",
        headers={**agent_headers, "Idempotency-Key": "request-1"},
        json={
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "theme": "春山",
            "candidate_count": 1,
        },
    )
    assert response.status_code == 202
    submitted = response.json()
    assert submitted["status"] == "queued"
    assert submitted["waiting_for_worker"] is True

    repeated = client.post(
        "/v1/poetry/jobs/generate",
        headers={**agent_headers, "Idempotency-Key": "request-1"},
        json={
            "meter_type": "唐诗",
            "form_name": "五言绝句",
            "theme": "春山",
            "candidate_count": 1,
        },
    )
    assert repeated.json()["job_id"] == submitted["job_id"]

    claim = client.post(
        "/internal/v1/workers/claim",
        headers=worker_headers,
        json={"worker_id": "t4-1", "capabilities": {"model": "fake"}, "wait_seconds": 0},
    )
    assert claim.status_code == 200
    assert claim.json()["job_id"] == submitted["job_id"]

    complete = client.post(
        f"/internal/v1/jobs/{submitted['job_id']}/complete",
        headers=worker_headers,
        json={"worker_id": "t4-1", "result": {"text": "春山如画"}},
    )
    assert complete.status_code == 204

    status = client.get(
        f"/v1/poetry/jobs/{submitted['job_id']}",
        headers=agent_headers,
    )
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["result"] == {"text": "春山如画"}


def test_api_auth_and_openapi_tool_routes(tmp_path):
    client = _client(tmp_path)
    assert client.get("/health/live").status_code == 200
    assert client.get("/v1/poetry/jobs/missing").status_code == 401

    schema = client.get("/openapi.json").json()
    assert "/v1/poetry/jobs/generate" in schema["paths"]
    assert "/v1/poetry/jobs/rewrite" in schema["paths"]
    assert "/v1/poetry/jobs/{job_id}" in schema["paths"]

