from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .openai_client import ChatModel
from .prompts import SYSTEM_PROMPT


class AgentTurnPaused(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolContext:
    user_message: str
    turn_index: int


class AgentSession:
    def __init__(self, model: ChatModel, toolbox, *, max_tool_rounds: int = 8, classifier_model: ChatModel | None = None):
        self._model = model
        self._classifier_model = classifier_model
        self._toolbox = toolbox
        self._max_tool_rounds = max_tool_rounds
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        pending = getattr(toolbox, "pending", None)
        pending_job_id = str(getattr(pending, "submitted_job_id", "") or "").strip()
        if pending_job_id:
            self._messages.append({
                "role": "system",
                "content": (
                    "内部任务上下文：本对话最近已提交的真实诗词任务 job_id："
                    f"{pending_job_id}。用户询问该任务的进度或生成正文时，"
                    "必须调用 get_poetry_job 查询，不要要求用户再次提供 job_id。"
                ),
            })
        self._turn_index = 0
        self._submitted_jobs: list[dict[str, Any]] = []
        self._prepared_proposals: list[dict[str, Any]] = []

    @property
    def messages(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._messages)

    @property
    def submitted_jobs(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._submitted_jobs)

    def reset(self) -> None:
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._turn_index = 0
        self._toolbox.reset()

    def load_history(self, messages: list[Mapping[str, Any]]) -> None:
        """恢复已持久化的用户/助手消息，系统提示仍由当前版本控制。"""
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        submitted_jobs: list[str] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                self._messages.append({"role": role, "content": content})
            job_id = str(message.get("job_id") or "").strip()
            if job_id:
                submitted_jobs.append(job_id)
        if submitted_jobs:
            # 网页按钮提交任务不经过当前 Agent turn；把持久化的任务标识
            # 作为内部上下文恢复，模型才能在后续追问时查询真实成稿。
            ids = ", ".join(dict.fromkeys(submitted_jobs))
            self._messages.append({
                "role": "system",
                "content": (
                    "内部任务上下文：以下是本对话中最近已提交的真实诗词任务 job_id："
                    f"{ids}。用户询问刚才生成的作品、进度、点评或核对时，"
                    "必须优先调用 get_poetry_job 查询对应任务；不要要求用户再次提供 job_id。"
                ),
            })
        pending = getattr(self._toolbox, "pending", None)
        pending_job_id = str(getattr(pending, "submitted_job_id", "") or "").strip()
        if pending_job_id and pending_job_id not in submitted_jobs:
            self._messages.append({
                "role": "system",
                "content": (
                    "内部任务上下文：本对话最近已提交的真实诗词任务 job_id："
                    f"{pending_job_id}。用户询问该任务的进度或生成正文时，"
                    "必须调用 get_poetry_job 查询，不要要求用户再次提供 job_id。"
                ),
            })
        self._turn_index = sum(1 for item in self._messages if item["role"] == "user")

    def respond(self, user_message: str) -> str:
        text = user_message.strip()
        if not text:
            raise ValueError("用户消息不能为空")
        self._turn_index += 1
        self._submitted_jobs = []
        self._prepared_proposals = []
        context = ToolContext(text, self._turn_index)
        self._messages.append({"role": "user", "content": text})
        self._append_task_classification(text)

        for _ in range(self._max_tool_rounds):
            message = self._model.complete(self._messages, self._toolbox.schemas())
            assistant = self._normalize_assistant_message(message)
            self._messages.append(assistant)
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                content = assistant.get("content")
                submit_fallback = getattr(
                    self._toolbox, "submit_pending_if_confirmed", None
                )
                fallback = submit_fallback(context) if submit_fallback else None
                if fallback:
                    self._submitted_jobs.append(fallback)
                    job_id = fallback.get("job_id")
                    status = fallback.get("status", "queued")
                    suffix = f"\n\n任务已实际提交，job_id：{job_id}，当前状态：{status}。"
                    content = (content or "") + suffix
                content = content if isinstance(content, str) and content else "暂时无法生成有效回复。"
                return self._append_prompt_disclosure(content)
            for call in tool_calls:
                result = self._execute_tool_call(call, context)
                self._messages.append(result)
        raise RuntimeError("Agent 工具调用轮次超过上限")

    def respond_stream(self, user_message: str, cancellation_event=None):
        """逐轮消费上游 SSE；工具只在参数完整后执行。"""
        text = user_message.strip()
        if not text:
            raise ValueError("用户消息不能为空")
        self._turn_index += 1
        self._submitted_jobs = []
        self._prepared_proposals = []
        context = ToolContext(text, self._turn_index)
        self._messages.append({"role": "user", "content": text})
        self._append_task_classification(text)

        for _ in range(self._max_tool_rounds):
            if cancellation_event is not None and cancellation_event.is_set():
                raise AgentTurnPaused("Agent turn paused")
            stream_method = getattr(self._model, "stream", None)
            if callable(stream_method):
                content_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                try:
                    model_events = stream_method(self._messages, self._toolbox.schemas(), cancellation_event=cancellation_event)
                except TypeError:
                    model_events = stream_method(self._messages, self._toolbox.schemas())
                for event in model_events:
                    if cancellation_event is not None and cancellation_event.is_set():
                        raise AgentTurnPaused("Agent turn paused")
                    event_type = event.get("type")
                    if event_type == "assistant.delta":
                        piece = str(event.get("text") or "")
                        content_parts.append(piece)
                        yield {"event_type": "assistant.delta", "payload": {"text": piece}}
                    elif event_type in {"tool.name.delta", "tool.arguments.delta"}:
                        yield {"event_type": "tool.delta", "payload": dict(event)}
                    elif event_type == "turn.finished":
                        tool_calls = list(event.get("tool_calls") or [])
                    elif event.get("error"):
                        raise RuntimeError(str(event["error"]))
                message = {"role": "assistant", "content": "".join(content_parts) or None}
                if tool_calls:
                    message["tool_calls"] = tool_calls
            else:
                message = self._model.complete(self._messages, self._toolbox.schemas())
                if message.get("content"):
                    yield {"event_type": "assistant.delta", "payload": {"text": str(message["content"])}}

            assistant = self._normalize_assistant_message(message)
            if cancellation_event is not None and cancellation_event.is_set():
                raise AgentTurnPaused("Agent turn paused")
            self._messages.append(assistant)
            calls = assistant.get("tool_calls") or []
            if not calls:
                content = assistant.get("content")
                submit_fallback = getattr(self._toolbox, "submit_pending_if_confirmed", None)
                fallback = submit_fallback(context) if submit_fallback else None
                if fallback:
                    self._submitted_jobs.append(fallback)
                    yield {"event_type": "job.submitted", "payload": fallback}
                    suffix = f"\n\n任务已实际提交，job_id：{fallback.get('job_id')}，当前状态：{fallback.get('status', 'queued')}。"
                    content = (content or "") + suffix
                    yield {"event_type": "assistant.delta", "payload": {"text": suffix}}
                reply = content if isinstance(content, str) and content else "暂时无法生成有效回复。"
                disclosed = self._append_prompt_disclosure(reply)
                if disclosed != reply:
                    suffix = disclosed[len(reply):]
                    yield {"event_type": "assistant.delta", "payload": {"text": suffix}}
                    reply = disclosed
                yield {"event_type": "turn.completed", "payload": {"reply": reply, "jobs": list(self._submitted_jobs)}}
                return

            for call in calls:
                if cancellation_event is not None and cancellation_event.is_set():
                    raise AgentTurnPaused("Agent turn paused")
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                call_id = str(call.get("id") or "missing-tool-call-id")
                yield {"event_type": "tool.started", "payload": {"tool_call_id": call_id, "name": name}}
                submitted_before = len(self._submitted_jobs)
                result = self._execute_tool_call(call, context)
                try:
                    output = json.loads(result["content"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    output = {"ok": False, "error": "工具结果无法解析"}
                yield {"event_type": "tool.completed", "payload": {"tool_call_id": call_id, "name": name, "output": output}}
                for job in self._submitted_jobs[submitted_before:]:
                    yield {"event_type": "job.submitted", "payload": job}
                self._messages.append(result)
        raise RuntimeError("Agent 工具调用轮次超过上限")

    def _append_task_classification(self, user_message: str) -> None:
        """Classify only the current request before the main model sees tools."""
        if self._classifier_model is None:
            return
        messages = [
            {"role": "system", "content": (
                "你是诗词任务路由器。只根据下一条用户消息判断任务类型。"
                "若用户提供了一句或多句必须保留的诗句，并要求补全其余诗句，"
                "或者要求修改已有诗句，输出 partial_generate；只有用户没有提供任何固定诗句、"
                "要求从零创作整首作品时输出 generate。只能输出 JSON："
                "{\"task_type\":\"generate\"} 或 {\"task_type\":\"partial_generate\"}。"
            )},
            {"role": "user", "content": user_message},
        ]
        try:
            result = self._classifier_model.complete(messages, [])
            raw = str(result.get("content") or "").strip()
            try:
                parsed = json.loads(raw)
                task_type = parsed.get("task_type")
            except json.JSONDecodeError:
                match = re.search(r'"task_type"\s*:\s*"(generate|partial_generate)"', raw)
                task_type = match.group(1) if match else None
        except (Exception,):
            task_type = None
        if task_type not in {"generate", "partial_generate"}:
            return
        self._messages.append({
            "role": "system",
            "content": (
                f"内部任务路由结果：{task_type}。必须遵守该分类选择工具；"
                "partial_generate 场景必须把固定句写入 fixed_lines，不能把固定句仅写入 requirement。"
            ),
        })

    @staticmethod
    def _normalize_assistant_message(message: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "content",
            "tool_calls",
            "function_call",
            "reasoning_content",
            "refusal",
            "annotations",
            "audio",
        }
        normalized: dict[str, Any] = {"role": "assistant"}
        normalized.update({key: value for key, value in message.items() if key in allowed})
        normalized.setdefault("content", None)
        return normalized

    def _execute_tool_call(self, call: Mapping[str, Any], context: ToolContext) -> dict:
        call_id = str(call.get("id") or "missing-tool-call-id")
        function = call.get("function") or {}
        name = str(function.get("name") or "")
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else dict(raw_arguments)
            )
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            output = self._toolbox.execute(name, arguments, context)
            if name in {"prepare_generation", "prepare_partial_generation"} and isinstance(output, dict):
                self._prepared_proposals.append(output)
            if name in {"submit_generation", "submit_partial_generation"} and isinstance(output, dict) and output.get("job_id"):
                self._submitted_jobs.append(output)
            body = {"ok": True, "result": output}
        except Exception as exc:
            body = {"ok": False, "error": str(exc)}
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(body, ensure_ascii=False),
        }

    def _append_prompt_disclosure(self, content: str) -> str:
        if not self._prepared_proposals:
            return content
        sections = []
        for prepared in self._prepared_proposals:
            prompt = str(prepared.get("editable_prompt") or "").strip() or "（未填写）"
            count = prepared.get("candidate_count", 1)
            kind = "部分生成提示词" if prepared.get("kind") == "partial_generate" else "创作提示词"
            sections.append(
                f"{kind}（可修改）：\n{prompt}\n候选数量：{count}（支持 1 至 5）"
            )
        return content.rstrip() + "\n\n" + "\n\n".join(sections)
