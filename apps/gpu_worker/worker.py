from __future__ import annotations

import logging
import threading
from typing import Any

from shiju.service.generation_service import GenerationService

from .api_client import WorkerApiClient


LOGGER = logging.getLogger(__name__)


class GpuWorker:
    def __init__(
        self,
        worker_id: str,
        client: WorkerApiClient,
        service: GenerationService,
        capabilities: dict[str, Any],
        *,
        heartbeat_seconds: int = 15,
    ):
        self.worker_id = worker_id
        self.client = client
        self.service = service
        self.capabilities = capabilities
        self.heartbeat_seconds = heartbeat_seconds
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def run_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self.client.claim(self.worker_id, self.capabilities)
            except Exception:
                LOGGER.exception("领取任务失败")
                self._stopping.wait(5)
                continue
            if not job:
                continue
            self._execute(job)

    def _execute(self, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()
        try:
            result = self.service.execute(job["kind"], job["request"])
            self.client.complete(job_id, self.worker_id, result)
            LOGGER.info("任务完成", extra={"job_id": job_id})
        except Exception as exc:
            LOGGER.exception("任务执行失败", extra={"job_id": job_id})
            code = str(getattr(exc, "code", "WORKER_EXECUTION_ERROR"))
            self.client.fail(
                job_id,
                self.worker_id,
                code,
                str(exc),
                retryable=code in {"CUDA_RUNTIME_ERROR", "CONTROL_PLANE_UNAVAILABLE"},
            )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            try:
                self.client.heartbeat(job_id, self.worker_id)
            except Exception:
                LOGGER.exception("任务心跳失败", extra={"job_id": job_id})

