from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSettings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    poetry_api_base_url: str = "http://127.0.0.1:8000"
    poetry_api_token: str = "change-me-agent"
    request_timeout_seconds: float = 90.0
    max_tool_rounds: int = 8

    @classmethod
    def from_env(cls) -> "AgentSettings":
        base_url = os.getenv("SHIJU_LLM_BASE_URL", "").strip()
        api_key = os.getenv("SHIJU_LLM_API_KEY", "").strip()
        model = os.getenv("SHIJU_LLM_MODEL", "").strip()
        missing = [
            name
            for name, value in (
                ("SHIJU_LLM_BASE_URL", base_url),
                ("SHIJU_LLM_API_KEY", api_key),
                ("SHIJU_LLM_MODEL", model),
            )
            if not value
        ]
        if missing:
            raise ValueError("缺少 Agent 配置: " + ", ".join(missing))
        return cls(
            llm_base_url=base_url,
            llm_api_key=api_key,
            llm_model=model,
            poetry_api_base_url=os.getenv(
                "SHIJU_POETRY_API_BASE_URL", "http://127.0.0.1:8000"
            ).strip(),
            poetry_api_token=os.getenv("SHIJU_AGENT_TOKEN", "change-me-agent").strip(),
            request_timeout_seconds=float(os.getenv("SHIJU_LLM_TIMEOUT_SECONDS", "90")),
            max_tool_rounds=int(os.getenv("SHIJU_AGENT_MAX_TOOL_ROUNDS", "8")),
        )

