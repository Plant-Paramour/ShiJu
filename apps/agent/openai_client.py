from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, Protocol

from .transport import JsonTransportError, request_json, request_sse
from .sse import iter_sse_lines, merge_openai_stream


class ChatModel(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]: ...


class ChatModelError(RuntimeError):
    pass


def chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


class OpenAICompatibleChatModel:
    """最小化 OpenAI Chat Completions 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        transport: Callable[..., dict[str, Any]] = request_json,
        stream_transport: Callable[..., Any] | None = None,
    ):
        self._url = chat_completions_url(base_url)
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._stream_transport = stream_transport

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "stream": False,
        }
        try:
            data = self._transport(
                "POST",
                self._url,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                payload,
                self._timeout_seconds,
            )
        except (JsonTransportError, OSError, ValueError) as exc:
            raise ChatModelError(f"大模型 API 请求失败: {exc}") from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatModelError("大模型 API 响应缺少 choices[0].message") from exc
        if not isinstance(message, dict):
            raise ChatModelError("大模型 API 返回的 message 不是对象")
        return message

    def stream(self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]):
        payload: dict[str, Any] = {
            "model": self._model, "messages": list(messages), "tools": list(tools),
            "tool_choice": "auto", "stream": True,
        }
        try:
            stream_transport = self._stream_transport or request_sse
            chunks = stream_transport("POST", self._url, {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, payload, self._timeout_seconds)
            return merge_openai_stream(iter_sse_lines(chunks))
        except (JsonTransportError, OSError, ValueError) as exc:
            raise ChatModelError(f"大模型 SSE 请求失败: {exc}") from exc
