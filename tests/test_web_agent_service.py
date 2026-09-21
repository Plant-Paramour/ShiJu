from __future__ import annotations

import json

from apps.agent.web_service import RepositoryPoetryJobs, WebAgentService
from apps.api.database import Database
from apps.api.job_repository import JobRepository
from apps.api.user_repository import UserRepository
from shiju.service.gpu_provider import ManualGpuProvider


class RecordingModel:
    def complete(self, messages, tools):
        user_messages = [item["content"] for item in messages if item["role"] == "user"]
        return {
            "role": "assistant",
            "content": f"第{len(user_messages)}轮：{user_messages[-1]}",
        }


class NoopJobs:
    def submit_generate(self, payload, idempotency_key):
        raise AssertionError("本测试不应提交生成任务")

    def submit_rewrite(self, payload, idempotency_key):
        raise AssertionError("本测试不应提交重写任务")

    def get_job(self, job_id):
        return {"job_id": job_id, "status": "queued"}


def test_web_agent_keeps_context_per_session_and_isolates_sessions():
    from pathlib import Path

    service = WebAgentService(
        RecordingModel(),
        NoopJobs(),
        Path(__file__).resolve().parents[1],
    )

    first = service.respond("你好")
    second = service.respond("继续", first["session_id"])
    separate = service.respond("新对话")

    assert first["reply"] == "第1轮：你好"
    assert second["reply"] == "第2轮：继续"
    assert separate["reply"] == "第1轮：新对话"
    assert separate["session_id"] != first["session_id"]


def test_web_agent_rejects_invalid_session_id():
    from pathlib import Path

    service = WebAgentService(
        RecordingModel(),
        NoopJobs(),
        Path(__file__).resolve().parents[1],
    )

    try:
        service.respond("你好", "../../invalid")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("无效 session_id 应被拒绝")


def test_pending_proposal_survives_service_restart(tmp_path):
    class ScriptedModel:
        def __init__(self, responses):
            self.responses = list(responses)

        def complete(self, messages, tools):
            return self.responses.pop(0)

    database = Database(tmp_path / "agent.db")
    database.initialize()
    users = UserRepository(database)
    users.seed_defaults()
    user = users.authenticate("Test1", "Test1")
    conversation = users.create_conversation(user["id"], "春山")
    jobs = RepositoryPoetryJobs(JobRepository(database), ManualGpuProvider())
    root = tmp_path.parents[0]
    prepare_model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "prepare",
                        "type": "function",
                        "function": {
                            "name": "prepare_generation",
                            "arguments": json.dumps(
                                {
                                    "meter_type": "唐诗",
                                    "form_name": "五言绝句",
                                    "theme": "春山",
                                    "requirement": "写春山。",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "方案已准备，请确认。"},
        ]
    )
    first_service = WebAgentService(prepare_model, jobs, root)
    first = first_service.respond(
        "先看春山五绝的创作方案，暂不生成",
        conversation["id"],
        user_id=user["id"],
        conversation_id=conversation["id"],
    )

    restarted = WebAgentService(
        ScriptedModel([{"role": "assistant", "content": "已经提交。"}]),
        jobs,
        root,
    )
    second = restarted.respond(
        "确认生成",
        conversation["id"],
        history=[
            {"role": "user", "content": "先看春山五绝的创作方案，暂不生成"},
            {"role": "assistant", "content": first["reply"]},
        ],
        user_id=user["id"],
        conversation_id=conversation["id"],
    )

    assert second["job_id"]
    assert JobRepository(database).get(second["job_id"]).conversation_id == conversation["id"]
