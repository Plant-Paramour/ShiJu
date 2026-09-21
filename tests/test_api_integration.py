import json
import time

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


class FakeWebAgent:
    def __init__(self):
        self.calls = []

    def respond(self, message, session_id=None):
        self.calls.append((message, session_id))
        return {"session_id": session_id or "web-session-1", "reply": "山在，水在。"}


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
    assert "/v1/poetry/jobs" in schema["paths"]
    assert "/v1/agent/chat" in schema["paths"]


def test_web_agent_route_and_static_site(tmp_path):
    settings = ApiSettings(
        database_path=tmp_path / "api.db",
        agent_token="agent-secret",
        worker_token="worker-secret",
    )
    service = FakeWebAgent()
    client = TestClient(create_app(settings, agent_service=service))

    response = client.post(
        "/v1/agent/chat",
        json={"message": "说一句山水", "session_id": "existing-session"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "session_id": "existing-session",
        "reply": "山在，水在。",
    }
    assert service.calls == [("说一句山水", "existing-session")]

    page = client.get("/web/prosody-checker/")
    assert page.status_code == 200
    assert "与诗矩对谈" in page.text


def test_web_agent_route_is_disabled_without_configuration(tmp_path):
    client = _client(tmp_path)
    response = client.post("/v1/agent/chat", json={"message": "你好"})
    assert response.status_code == 503


def test_edited_agent_proposal_submits_directly_and_candidate_score_is_saved(tmp_path):
    client = _client(tmp_path)
    login = client.post("/v1/auth/login", json={"username": "Test1", "password": "Test1"}).json()
    headers = {"Authorization": f"Bearer {login['token']}"}
    conversation = client.post("/v1/conversations", headers=headers, json={"title": "春山"}).json()
    proposal_id = "proposal-web-submit"
    original = {
        "meter_type": "唐诗",
        "form_name": "五言绝句",
        "theme": "春山",
        "requirement": "写春山。",
        "candidate_count": 1,
    }
    with client.app.state.jobs.database.connect() as connection:
        connection.execute(
            "INSERT INTO agent_proposals(conversation_id,user_id,proposal_id,kind,payload_json,prepared_turn,updated_at) VALUES (?,?,?,?,?,?,?)",
            (conversation["id"], login["user"]["id"], proposal_id, "generate", json.dumps(original), 1, time.time()),
        )

    submitted = client.post(
        f"/v1/agent/proposals/{proposal_id}/submit",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "requirement": "写雨后春山，只生成两首。",
            "candidate_count": 2,
            "meter_type": "唐诗",
            "form_name": "七言绝句",
            "rhyme_dict_name": "Pinshui",
            "strict_polyphonic": False,
            "num_lines": None,
            "task_options": {"allow_aojiu": True},
        },
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    state = client.get(f"/v1/poetry/jobs/{job_id}/state", headers=headers).json()
    assert state["request"]["candidate_count"] == 2
    assert state["request"]["requirement"] == "写雨后春山，只生成两首。"
    assert state["request"]["rhyme_dict_name"] == "Pinshui"

    client.app.state.jobs.update_candidate(
        job_id,
        1,
        status="succeeded",
        title="春山",
        content="山雨初收晚照明，溪云欲散鸟先鸣。",
        finished_at=time.time(),
    )
    evaluation = {
        "version": 1,
        "rhyme_book_name": "平水韵",
        "form_name": "七言绝句",
        "structure_score": 100,
        "tonal_score": 90,
        "rhyme_score": 100,
        "result": {"issues": [], "lines": [], "rhymeGroups": []},
    }
    saved = client.put(
        f"/v1/poetry/jobs/{job_id}/candidates/1/evaluation",
        headers=headers,
        json={"evaluation": evaluation},
    )
    assert saved.status_code == 200
    poems = client.get("/v1/profile/poems", headers=headers).json()["items"]
    assert len(poems) == 1
    assert poems[0]["candidate_ordinal"] == 1
    assert poems[0]["evaluation"]["rhyme_book_name"] == "平水韵"
