from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class WorkerApiClient:
    def __init__(self, base_url: str, token: str, *, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def claim(self, worker_id: str, capabilities: dict[str, Any]):
        return self._post(
            "/internal/v1/workers/claim",
            {"worker_id": worker_id, "capabilities": capabilities, "wait_seconds": 15},
        )

    def heartbeat(self, job_id: str, worker_id: str) -> None:
        self._post(
            f"/internal/v1/jobs/{job_id}/heartbeat",
            {"worker_id": worker_id},
        )

    def complete(self, job_id: str, worker_id: str, result: dict[str, Any]) -> None:
        self._post(
            f"/internal/v1/jobs/{job_id}/complete",
            {"worker_id": worker_id, "result": result},
        )

    def fail(
        self,
        job_id: str,
        worker_id: str,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        self._post(
            f"/internal/v1/jobs/{job_id}/fail",
            {
                "worker_id": worker_id,
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        )

    def _post(self, path: str, payload: dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()
                return json.loads(content.decode("utf-8")) if content else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"控制面请求失败 {exc.code}: {detail}") from exc

