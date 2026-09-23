from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiSettings:
    database_path: Path
    agent_token: str
    worker_token: str
    database_url: str | None = None
    max_request_bytes: int = 65536
    worker_lease_seconds: int = 300
    web_agent_enabled: bool = False
    auth_secret: str = "change-me-auth-secret"
    agent_global_concurrency: int = 32
    agent_user_concurrency: int = 2
    agent_daily_quota: int = 200

    @classmethod
    def from_env(cls) -> "ApiSettings":
        database_url = os.getenv("DATABASE_URL", "").strip() or None
        production = os.getenv("SHIJU_ENV", "development").lower() in {"production", "prod"}
        if production and not database_url:
            raise ValueError("生产环境必须配置 DATABASE_URL（PostgreSQL）")
        auth_secret = os.getenv("SHIJU_AUTH_SECRET", "change-me-auth-secret")
        if production and auth_secret == "change-me-auth-secret":
            raise ValueError("生产环境必须配置 SHIJU_AUTH_SECRET")
        return cls(
            database_path=Path(os.getenv("SHIJU_DATABASE_PATH", "var/shiju.db")),
            database_url=database_url,
            agent_token=os.getenv("SHIJU_AGENT_TOKEN", "change-me-agent"),
            worker_token=os.getenv("SHIJU_WORKER_TOKEN", "change-me-worker"),
            max_request_bytes=int(os.getenv("SHIJU_MAX_REQUEST_BYTES", "65536")),
            worker_lease_seconds=int(os.getenv("SHIJU_WORKER_LEASE_SECONDS", "300")),
            web_agent_enabled=os.getenv("SHIJU_WEB_AGENT_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            auth_secret=auth_secret,
            agent_global_concurrency=int(os.getenv("SHIJU_AGENT_GLOBAL_CONCURRENCY", "32")),
            agent_user_concurrency=int(os.getenv("SHIJU_AGENT_USER_CONCURRENCY", "2")),
            agent_daily_quota=int(os.getenv("SHIJU_AGENT_DAILY_QUOTA", "200")),
        )
