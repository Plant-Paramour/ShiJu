import os

import pytest

from apps.agent.gateway import EndpointConfig, ModelGateway
from apps.agent.transport import JsonTransportError


class FakeModel:
    def __init__(self, *, base_url, **kwargs):
        self.base_url = base_url

    def complete(self, messages, tools):
        if "bad" in self.base_url:
            raise JsonTransportError("busy", status_code=503)
        return {"role": "assistant", "content": "ok"}

    def stream(self, messages, tools):
        yield {"type": "assistant.delta", "text": "ok"}


def test_gateway_fails_over_by_tier(monkeypatch):
    monkeypatch.setattr("apps.agent.gateway.OpenAICompatibleChatModel", FakeModel)
    os.environ["GW_BAD"] = "bad-key"
    os.environ["GW_GOOD"] = "good-key"
    gateway = ModelGateway([
        EndpointConfig("bad", "https://bad", "m", "GW_BAD", tier="primary"),
        EndpointConfig("good", "https://good", "m", "GW_GOOD", tier="secondary"),
    ])
    assert gateway.complete([], []) == {"role": "assistant", "content": "ok"}
    assert gateway.status()[0]["failures"] == 1


def test_gateway_does_not_retry_client_error(monkeypatch):
    class ClientError(FakeModel):
        def complete(self, messages, tools):
            raise JsonTransportError("bad request", status_code=400)

    monkeypatch.setattr("apps.agent.gateway.OpenAICompatibleChatModel", ClientError)
    os.environ["GW_CLIENT"] = "key"
    gateway = ModelGateway([EndpointConfig("client", "https://client", "m", "GW_CLIENT")], max_attempts=3)
    with pytest.raises(Exception):
        gateway.complete([], [])
    assert gateway.status()[0]["failures"] == 1


def test_gateway_stream_keeps_interface(monkeypatch):
    monkeypatch.setattr("apps.agent.gateway.OpenAICompatibleChatModel", FakeModel)
    os.environ["GW_STREAM"] = "key"
    gateway = ModelGateway([EndpointConfig("stream", "https://good", "m", "GW_STREAM")])
    assert list(gateway.stream([], [])) == [{"type": "assistant.delta", "text": "ok"}]


def test_gateway_stream_does_not_fail_over_after_first_event(monkeypatch):
    class PartialFailure(FakeModel):
        def stream(self, messages, tools):
            yield {"type": "assistant.delta", "text": "partial"}
            raise JsonTransportError("connection lost", status_code=503)

    monkeypatch.setattr("apps.agent.gateway.OpenAICompatibleChatModel", PartialFailure)
    os.environ["GW_PARTIAL"] = "key"
    gateway = ModelGateway([
        EndpointConfig("partial", "https://partial", "m", "GW_PARTIAL"),
        EndpointConfig("fallback", "https://fallback", "m", "GW_PARTIAL", tier="secondary"),
    ])
    iterator = gateway.stream([], [])
    assert next(iterator)["text"] == "partial"
    with pytest.raises(Exception, match="已开始后中断"):
        next(iterator)


def test_gateway_loads_toml(tmp_path, monkeypatch):
    config = tmp_path / "gateway.toml"
    config.write_text(
        "[[endpoints]]\nprovider_id='p'\nbase_url='https://example'\nmodel='m'\nsecret_ref='GW_TOML'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GW_TOML", "secret")
    gateway = ModelGateway.from_toml(config)
    assert gateway.status()[0]["provider_id"] == "p"
