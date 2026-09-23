from __future__ import annotations

import re
import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shiju.contracts import JobKind

from .framework import AgentSession
from .jobs import PoetryJobs
from .openai_client import ChatModel, OpenAICompatibleChatModel
from .gateway import ModelGateway
from .settings import AgentSettings
from .tools import AgentToolbox


class RepositoryPoetryJobs(PoetryJobs):
    """让同进程 Agent 直接使用控制面的任务仓储。"""

    def __init__(
        self,
        repository,
        gpu_provider,
        *,
        user_id: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
    ):
        self._repository = repository
        self._gpu_provider = gpu_provider
        self._user_id = user_id
        self._conversation_id = conversation_id

    def bind(self, user_id: str | None, conversation_id: str | None):
        return type(self)(
            self._repository,
            self._gpu_provider,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    def submit_generate(
        self, payload: Mapping[str, Any], idempotency_key: str
    ) -> dict:
        return self._submit(JobKind.GENERATE.value, payload, idempotency_key)

    def submit_rewrite(
        self, payload: Mapping[str, Any], idempotency_key: str
    ) -> dict:
        return self._submit(JobKind.REWRITE.value, payload, idempotency_key)

    def get_job(self, job_id: str) -> dict:
        return self._repository.snapshot(job_id)

    def load_pending_proposal(self) -> dict[str, Any] | None:
        if not self._user_id or not self._conversation_id:
            return None
        with self._repository.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_proposals WHERE conversation_id = ? AND user_id = ?",
                (self._conversation_id, self._user_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["proposal_id"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"]),
            "prepared_turn": row["prepared_turn"],
            "submitted_job_id": row["submitted_job_id"],
        }

    def save_pending_proposal(self, proposal: Mapping[str, Any]) -> None:
        if not self._user_id or not self._conversation_id:
            return
        payload = json.dumps(proposal["payload"], ensure_ascii=False, separators=(",", ":"))
        with self._repository.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_proposals(
                    conversation_id, user_id, proposal_id, kind, payload_json,
                    prepared_turn, submitted_job_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    proposal_id = excluded.proposal_id,
                    kind = excluded.kind,
                    payload_json = excluded.payload_json,
                    prepared_turn = excluded.prepared_turn,
                    submitted_job_id = excluded.submitted_job_id,
                    updated_at = excluded.updated_at
                """,
                (
                    self._conversation_id,
                    self._user_id,
                    proposal["id"],
                    proposal["kind"],
                    payload,
                    proposal["prepared_turn"],
                    proposal.get("submitted_job_id"),
                    time.time(),
                ),
            )

    def _submit(
        self,
        kind: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict:
        job = self._repository.submit(
            kind,
            payload,
            idempotency_key=idempotency_key,
            user_id=self._user_id,
            conversation_id=self._conversation_id,
        )
        self._gpu_provider.ensure_running()
        return {
            "job_id": job.id,
            "status": job.status,
            "waiting_for_worker": not self._repository.has_live_worker(),
        }


@dataclass
class _WebSession:
    agent: AgentSession
    lock: threading.Lock
    last_used_at: float
    model: str | None = None


DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
DEEPSEEK_V4_FLASH_UPSTREAM = "deepseek-v4-flash-nv-cc"


class _FallbackChatModel:
    """先调用首选端点；只有尚未产出流内容时才切换到网关。"""

    def __init__(self, primary: ChatModel, fallback: ChatModel | None):
        self._primary = primary
        self._fallback = fallback

    def complete(self, messages, tools):
        try:
            return self._primary.complete(messages, tools)
        except Exception:
            if self._fallback is None:
                raise
            return self._fallback.complete(messages, tools)

    def stream(self, messages, tools):
        def generate():
            emitted = False
            try:
                for event in self._primary.stream(messages, tools):
                    emitted = True
                    yield event
                return
            except Exception:
                if emitted or self._fallback is None:
                    raise
            yield from self._fallback.stream(messages, tools)

        return generate()


class _FrontendModelRouter:
    """将前端展示模型名映射为上游名，并为 v4 提供默认端点优先策略。"""

    def __init__(
        self,
        default_model: ChatModel,
        default_v4: ChatModel | None,
        gateway: ModelGateway | None,
        default_factory: Callable[[str], ChatModel] | None = None,
    ):
        self._default_model = default_model
        self._default_v4 = default_v4
        self._gateway = gateway
        self._default_factory = default_factory

    def for_model(self, model: str | None):
        if model in {DEEPSEEK_V4_FLASH, DEEPSEEK_V4_FLASH_UPSTREAM}:
            fallback = self._gateway.for_model(DEEPSEEK_V4_FLASH_UPSTREAM) if self._gateway else None
            if self._default_v4 is not None:
                return _FallbackChatModel(self._default_v4, fallback)
            if fallback is not None:
                return fallback
        if self._default_factory is not None and model:
            return self._default_factory(model)
        return self._default_model.for_model(model) if hasattr(self._default_model, "for_model") else self._default_model


class WebAgentService:
    _SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

    def __init__(
        self,
        model: ChatModel,
        jobs: PoetryJobs,
        project_root: str | Path,
        *,
        max_tool_rounds: int = 8,
        max_sessions: int = 200,
        session_ttl_seconds: int = 6 * 60 * 60,
        clock: Callable[[], float] = time.time,
    ):
        self._model = model
        self._jobs = jobs
        self._project_root = Path(project_root)
        self._max_tool_rounds = max_tool_rounds
        self._max_sessions = max_sessions
        self._session_ttl_seconds = session_ttl_seconds
        self._clock = clock
        self._sessions: dict[str, _WebSession] = {}
        self._sessions_lock = threading.Lock()

    @classmethod
    def from_env(cls, repository, gpu_provider, project_root: str | Path):
        settings = AgentSettings.from_env()
        gateway = None
        default_factory = None
        if settings.gateway_config_path:
            gateway = ModelGateway.from_toml(settings.gateway_config_path, max_attempts=settings.gateway_max_attempts)
            model = gateway
        else:
            # 未配置模型网关时，Web 服务直接调用默认兼容端点，避免把
            # 单端点故障包装成“模型网关无可用端点”。
            model = OpenAICompatibleChatModel(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
            default_factory = lambda selected_model: OpenAICompatibleChatModel(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=selected_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
        default_v4 = None
        if settings.llm_base_url and settings.llm_api_key:
            default_v4 = OpenAICompatibleChatModel(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=DEEPSEEK_V4_FLASH_UPSTREAM,
                timeout_seconds=settings.request_timeout_seconds,
            )
        model = _FrontendModelRouter(model, default_v4, gateway, default_factory)
        jobs = RepositoryPoetryJobs(repository, gpu_provider)
        return cls(
            model,
            jobs,
            project_root,
            max_tool_rounds=settings.max_tool_rounds,
        )

    def respond(
        self,
        message: str,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        active_id, entry = self._get_or_create_session(
            session_id,
            history=history,
            user_id=user_id,
            conversation_id=conversation_id,
            model=model,
        )
        with entry.lock:
            reply = entry.agent.respond(message)
            entry.last_used_at = self._clock()
        result = {"session_id": active_id, "reply": reply}
        submitted = list(entry.agent.submitted_jobs)
        if submitted:
            result["jobs"] = submitted
            result["job_id"] = submitted[-1]["job_id"]
        return result

    def generate_conversation_title(self, message: str) -> str:
        """用固定的轻量模型为新会话生成一次短标题。"""
        fallback = " ".join(str(message or "").split())[:15] or "新建对话"
        model = self._model.for_model("deepseek-v3.2-guiji-cc") if hasattr(self._model, "for_model") else self._model
        try:
            result = model.complete(
                [
                    {"role": "system", "content": "你负责给 AI 对话生成标题。只输出一个简洁中文标题，不要引号、标点、解释，最多 15 个汉字。"},
                    {"role": "user", "content": str(message or "")[:2000]},
                ],
                [],
            )
            title = " ".join(str(result.get("content") or "").split()).strip(" \"'“”‘’：:。.!！?？")
            return title[:15] or fallback
        except Exception:
            return fallback

    def respond_stream(
        self,
        message: str,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
    ):
        active_id, entry = self._get_or_create_session(
            session_id, history=history, user_id=user_id, conversation_id=conversation_id, model=model
        )
        with entry.lock:
            for event in entry.agent.respond_stream(message):
                if event["event_type"] == "turn.completed":
                    event["payload"]["session_id"] = active_id
                yield event
            entry.last_used_at = self._clock()

    def _get_or_create_session(
        self,
        session_id: str | None,
        *,
        history: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
    ) -> tuple[str, _WebSession]:
        if session_id is not None and not self._SESSION_ID.fullmatch(session_id):
            raise ValueError("session_id 格式无效")
        active_id = session_id or uuid.uuid4().hex
        now = self._clock()
        with self._sessions_lock:
            self._remove_expired(now)
            entry = self._sessions.get(active_id)
            if entry is None:
                self._make_room()
                jobs = (
                    self._jobs.bind(user_id, conversation_id)
                    if hasattr(self._jobs, "bind")
                    else self._jobs
                )
                entry = _WebSession(
                    agent=AgentSession(
                        self._model.for_model(model) if hasattr(self._model, "for_model") else self._model,
                        AgentToolbox(self._project_root, jobs),
                        max_tool_rounds=self._max_tool_rounds,
                    ),
                    lock=threading.Lock(),
                    last_used_at=now,
                    model=model,
                )
                if history:
                    entry.agent.load_history(history)
                self._sessions[active_id] = entry
            elif model != entry.model:
                # 模型选择器对同一会话也应立即生效，同时保留已有对话上下文。
                jobs = (
                    self._jobs.bind(user_id, conversation_id)
                    if hasattr(self._jobs, "bind")
                    else self._jobs
                )
                previous_messages = list(entry.agent.messages)
                entry.agent = AgentSession(
                    self._model.for_model(model) if hasattr(self._model, "for_model") else self._model,
                    AgentToolbox(self._project_root, jobs),
                    max_tool_rounds=self._max_tool_rounds,
                )
                entry.agent.load_history(previous_messages)
                entry.model = model
        return active_id, entry

    def _remove_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, entry in self._sessions.items()
            if now - entry.last_used_at > self._session_ttl_seconds
            and not entry.lock.locked()
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def _make_room(self) -> None:
        if len(self._sessions) < self._max_sessions:
            return
        available = [
            (session_id, entry)
            for session_id, entry in self._sessions.items()
            if not entry.lock.locked()
        ]
        if not available:
            raise RuntimeError("Agent 会话已满，请稍后重试")
        oldest_id, _ = min(available, key=lambda item: item[1].last_used_at)
        self._sessions.pop(oldest_id, None)
