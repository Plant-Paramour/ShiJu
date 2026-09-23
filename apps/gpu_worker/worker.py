from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from typing import Any

from shiju.service.generation_service import GenerationService

from .api_client import WorkerApiClient


LOGGER = logging.getLogger(__name__)


class WorkerCancelled(RuntimeError):
    pass


class GpuWorker:
    def __init__(
        self,
        worker_id: str,
        client: WorkerApiClient,
        service: GenerationService | None,
        capabilities: dict[str, Any],
        *,
        heartbeat_seconds: int = 15,
        process_runner=None,
    ):
        self.worker_id = worker_id
        self.client = client
        self.service = service
        self.capabilities = capabilities
        self.heartbeat_seconds = heartbeat_seconds
        self._stopping = threading.Event()
        self.process_runner = process_runner

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
            LOGGER.info("领取任务: job_id=%s kind=%s", job["job_id"], job["kind"])
            self._execute(job)

    def _execute(self, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        heartbeat_stop = threading.Event()
        cancel_requested = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, heartbeat_stop, cancel_requested),
            daemon=True,
        )
        heartbeat.start()
        try:
            if self.service is not None:
                result = self.service.execute(job["kind"], job["request"])
            elif self.process_runner is not None:
                result = self.process_runner(
                    job["kind"], job["request"],
                    lambda event_type, payload: self._report_candidate_event(job_id, event_type, payload),
                    cancel_requested.is_set,
                )
            else:
                raise RuntimeError("GPU Worker 未配置任务执行子进程")
            if cancel_requested.is_set():
                raise WorkerCancelled("任务已由用户取消")
            self.client.complete(job_id, self.worker_id, result)
            LOGGER.info("任务完成: job_id=%s", job_id)
        except WorkerCancelled:
            self.client.acknowledge_cancel(job_id, self.worker_id)
            LOGGER.info("任务已取消: job_id=%s", job_id)
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

    def _report_candidate_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        ordinal = int(payload.get("ordinal", 0) or 0)
        if ordinal < 1:
            return
        fields: dict[str, Any] = {"attempt": int(payload.get("attempt", 0) or 0)}
        if event_type == "candidate.started":
            fields.update(status="running", partial_text="", error="", started_at=time.time())
        elif event_type == "candidate.delta":
            fields.update(status="running", partial_text=str(payload.get("partial_text") or ""))
        elif event_type == "candidate.retry":
            fields.update(status="retrying", error=str(payload.get("error") or "协议校验失败"))
        elif event_type == "candidate.completed":
            fields.update(status="succeeded", partial_text=str(payload.get("text") or payload.get("content") or ""),
                          raw_text=str(payload.get("raw_output") or ""), title=payload.get("title"),
                          content=payload.get("content"), error="", finished_at=time.time())
        elif event_type == "candidate.failed":
            fields.update(status="failed", error=str(payload.get("error") or "生成失败"), finished_at=time.time())
        else:
            return
        self.client.candidate_update(job_id, self.worker_id, ordinal, **fields)

    def _heartbeat_loop(self, job_id: str, stop: threading.Event, cancel_requested: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            try:
                if self.client.heartbeat(job_id, self.worker_id):
                    cancel_requested.set()
                    return
            except Exception:
                LOGGER.exception("任务心跳失败", extra={"job_id": job_id})
