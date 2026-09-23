from __future__ import annotations

from apps.agent.openai_client import OpenAICompatibleChatModel, chat_completions_url
from apps.agent.transport import JsonTransportError
from apps.agent.sse import iter_sse_lines, merge_openai_stream


def test_chat_completions_url_accepts_root_v1_and_full_endpoint():
    assert chat_completions_url("https://example.com") == (
        "https://example.com/v1/chat/completions"
    )
    assert chat_completions_url("https://example.com/v1/") == (
        "https://example.com/v1/chat/completions"
    )
    assert chat_completions_url("https://example.com/openai/chat/completions") == (
        "https://example.com/openai/chat/completions"
    )


def test_openai_compatible_client_sends_tools_and_extracts_message():
    captured = {}

    def transport(method, url, headers, payload, timeout_seconds):
        captured["method"] = method
        captured["url"] = url
        captured["authorization"] = headers["Authorization"]
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return {"choices": [{"message": {"role": "assistant", "content": "你好"}}]}

    model = OpenAICompatibleChatModel(
        base_url="https://example.com/v1",
        api_key="secret",
        model="example-model",
        transport=transport,
    )
    message = model.complete(
        [{"role": "user", "content": "你好"}],
        [{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
    )

    assert message["content"] == "你好"
    assert captured["authorization"] == "Bearer secret"
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["payload"]["model"] == "example-model"
    assert captured["payload"]["tool_choice"] == "auto"
    assert captured["payload"]["tools"][0]["function"]["name"] == "lookup"


def test_openai_sse_merges_text_and_split_tool_arguments():
    chunks = iter_sse_lines(
        [
            'data: {"choices":[{"delta":{"content":"你"}}]}\n', '\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"lookup","arguments":"{\\"text\\":"}}]}}]}\n', '\n',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"春\\"}"}}]},"finish_reason":"tool_calls"}]}\n', '\n',
            'data: [DONE]\n', '\n',
        ]
    )
    events = list(merge_openai_stream(chunks))
    assert events[0] == {"type": "assistant.delta", "text": "你"}
    finished = next(event for event in events if event.get("type") == "turn.finished")
    assert finished["tool_calls"][0]["id"] == "call-1"
    assert finished["tool_calls"][0]["function"]["arguments"] == '{"text":"春"}'


def test_stream_falls_back_to_non_stream_response():
    calls = []

    def transport(method, url, headers, payload, timeout_seconds):
        calls.append(payload["stream"])
        return {"choices": [{"message": {"role": "assistant", "content": "普通回复"}}]}

    def stream_transport(*args):
        raise JsonTransportError("stream unsupported", status_code=400)

    model = OpenAICompatibleChatModel(
        base_url="https://example.com/v1", api_key="secret", model="m",
        transport=transport, stream_transport=stream_transport,
    )
    events = list(model.stream([], []))
    assert events == [
        {"type": "assistant.delta", "text": "普通回复"},
        {"type": "turn.finished", "finish_reason": "stop", "tool_calls": []},
    ]
    assert calls == [False]
