from __future__ import annotations

import json
import sys

from apps.agent.framework import AgentSession
from apps.agent.tools import AgentToolbox


class FakeJobs:
    def submit_generate(self, payload, idempotency_key):
        raise AssertionError("不应提交任务")

    def submit_rewrite(self, payload, idempotency_key):
        raise AssertionError("不应提交任务")

    def get_job(self, job_id):
        return {"job_id": job_id, "status": "queued"}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((list(messages), list(tools)))
        return self.responses.pop(0)


def test_task_classifier_is_given_only_current_message_and_injected_before_tools(tmp_path):
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    classifier = ScriptedModel([{"role": "assistant", "content": '{"task_type":"partial_generate"}'}])
    main = ScriptedModel([{"role": "assistant", "content": "已识别为部分生成。"}])
    session = AgentSession(main, AgentToolbox(root, FakeJobs()), classifier_model=classifier)

    assert session.respond("给我颈联，请补成七律") == "已识别为部分生成。"
    assert classifier.calls[0][0][-1] == {"role": "user", "content": "给我颈联，请补成七律"}
    injected = main.calls[0][0][-1]
    assert injected["role"] == "system"
    assert "partial_generate" in injected["content"]
    assert "prepare_partial_generation" in {item["function"]["name"] for item in main.calls[0][1]}


def test_agent_executes_tool_and_returns_follow_up_text(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "list_rhyme_books", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "目前支持四本韵书。"},
        ]
    )
    session = AgentSession(model, AgentToolbox(root, FakeJobs()))

    assert session.respond("有哪些韵书？") == "目前支持四本韵书。"
    second_messages = model.calls[1][0]
    assert second_messages[-1]["role"] == "tool"
    tool_output = json.loads(second_messages[-1]["content"])
    assert tool_output["ok"] is True
    assert len(tool_output["result"]["rhyme_books"]) == 4


def test_agent_returns_tool_error_to_model_instead_of_crashing():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "bad-1",
                        "type": "function",
                        "function": {"name": "missing_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "assistant", "content": "这个工具暂不可用。"},
        ]
    )
    session = AgentSession(model, AgentToolbox(root, FakeJobs()))

    assert session.respond("调用不存在的工具") == "这个工具暂不可用。"
    output = json.loads(model.calls[1][0][-1]["content"])
    assert output["ok"] is False
    assert "未知工具" in output["error"]


def test_host_submits_confirmed_pending_proposal_when_model_omits_submit_tool():
    from pathlib import Path

    class SubmittingJobs(FakeJobs):
        def submit_generate(self, payload, idempotency_key):
            return {"job_id": "real-job-1", "status": "queued"}

    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "prepare-1",
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
            {"role": "assistant", "content": "方案已经准备好，请确认。"},
            {"role": "assistant", "content": "已经提交，正在排队。"},
        ]
    )
    session = AgentSession(
        model,
        AgentToolbox(Path(__file__).resolve().parents[1], SubmittingJobs()),
    )

    session.respond("先看春山五绝的创作方案，暂不生成")
    reply = session.respond("确认生成")

    assert "real-job-1" in reply
    assert session.submitted_jobs[-1]["job_id"] == "real-job-1"


def test_host_leaves_direct_generation_for_the_editable_web_submit():
    from pathlib import Path

    class SubmittingJobs(FakeJobs):
        def submit_generate(self, payload, idempotency_key):
            return {"job_id": "direct-job-1", "status": "queued"}

    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "prepare-direct",
                        "type": "function",
                        "function": {
                            "name": "prepare_generation",
                            "arguments": json.dumps(
                                {
                                    "meter_type": "唐诗",
                                    "form_name": "五言绝句",
                                    "theme": "春山",
                                    "requirement": "只写一首，以新雨后的山色起兴。",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "已按要求处理。"},
        ]
    )
    session = AgentSession(
        model,
        AgentToolbox(Path(__file__).resolve().parents[1], SubmittingJobs()),
    )

    reply = session.respond("请写一首春山五绝")

    assert session.submitted_jobs == ()
    assert "创作提示词（可修改）" in reply
    assert "只写一首，以新雨后的山色起兴。" in reply
    assert "候选数量：1" in reply


def test_agent_modules_do_not_load_torch():
    before = set(sys.modules)
    __import__("apps.agent.main")
    newly_loaded = set(sys.modules).difference(before)
    assert "torch" not in newly_loaded


def test_agent_stream_yields_text_deltas_before_completion(tmp_path):
    class StreamingModel:
        def stream(self, messages, tools):
            yield {"type": "assistant.delta", "text": "你"}
            yield {"type": "assistant.delta", "text": "好"}
            yield {"type": "turn.finished", "finish_reason": "stop", "tool_calls": []}

    session = AgentSession(StreamingModel(), AgentToolbox(tmp_path, FakeJobs()))
    events = list(session.respond_stream("你好"))

    assert [event["event_type"] for event in events] == [
        "assistant.delta", "assistant.delta", "turn.completed"
    ]
    assert events[-1]["payload"]["reply"] == "你好"
