from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Protocol

from .transport import JsonTransportError, request_json


class PoetryJobs(Protocol):
    def submit_generate(self, payload: Mapping[str, Any], idempotency_key: str) -> dict: ...

    def submit_rewrite(self, payload: Mapping[str, Any], idempotency_key: str) -> dict: ...

    def get_job(self, job_id: str) -> dict: ...


class PoetryApiError(RuntimeError):
    pass


class HttpPoetryJobs:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
        transport: Callable[..., dict[str, Any]] = request_json,
    ):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def submit_generate(self, payload: Mapping[str, Any], idempotency_key: str) -> dict:
        return self._request(
            "POST",
            "/v1/poetry/jobs/generate",
            payload,
            idempotency_key=idempotency_key,
        )

    def submit_rewrite(self, payload: Mapping[str, Any], idempotency_key: str) -> dict:
        return self._request(
            "POST",
            "/v1/poetry/jobs/rewrite",
            payload,
            idempotency_key=idempotency_key,
        )

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/poetry/jobs/{job_id}")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {self._token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            data = self._transport(
                method,
                self._base_url + path,
                headers,
                dict(payload) if payload is not None else None,
                self._timeout_seconds,
            )
        except (JsonTransportError, OSError, ValueError) as exc:
            raise PoetryApiError(f"诗词任务 API 请求失败: {exc}") from exc
        if not isinstance(data, dict):
            raise PoetryApiError("诗词任务 API 返回的不是 JSON 对象")
        return data

