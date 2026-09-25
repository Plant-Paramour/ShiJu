from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.settings import ApiSettings


class FakeAgent:
    def respond(self, message, session_id=None):
        return {"session_id": session_id or "local", "reply": "本地测试"}


def test_local_database_migrations_and_readiness(tmp_path):
    settings = ApiSettings(database_path=tmp_path / "stage-one.db", agent_token="a", worker_token="w")
    client = TestClient(create_app(settings, agent_service=FakeAgent()))
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"
    with client.app.state.jobs.database.connect() as connection:
        migrations = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert migrations == 14
        assert connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def test_local_agent_daily_quota_returns_429(tmp_path):
    settings = ApiSettings(
        database_path=tmp_path / "quota.db",
        agent_token="a",
        worker_token="w",
        agent_global_concurrency=2,
        agent_user_concurrency=1,
        agent_daily_quota=1,
    )
    client = TestClient(create_app(settings, agent_service=FakeAgent()))
    assert client.post("/v1/agent/chat", json={"message": "第一次"}).status_code == 200
    limited = client.post("/v1/agent/chat", json={"message": "第二次"})
    assert limited.status_code == 429


def test_production_settings_require_database_and_secret(monkeypatch):
    monkeypatch.setenv("SHIJU_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        ApiSettings.from_env()
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/shiju")
    monkeypatch.delenv("SHIJU_AUTH_SECRET", raising=False)
    with pytest.raises(ValueError, match="SHIJU_AUTH_SECRET"):
        ApiSettings.from_env()
