from __future__ import annotations

import logging
import multiprocessing
import os
import queue
import signal
import socket
from pathlib import Path


from .api_client import WorkerApiClient
from .worker import GpuWorker, WorkerCancelled


LOGGER = logging.getLogger(__name__)


class WorkerProcessError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _run_generation_process(event_queue, model_name: str, quantization: str, rhyme_dir: str, meter_dir: str, kind: str, payload: dict):
    """在任务子进程内加载模型，返回结果后主动释放 CUDA。"""
    from shiju.generation.engine import GenerationEngine
    from shiju.generation.model_runner import ModelRunner
    from shiju.generation.result import ModelSettings
    from shiju.service.generation_service import GenerationService
    runner = ModelRunner(ModelSettings(model_name=model_name, quantization=quantization))
    try:
        runner.load()
        def emit(event_type, event_payload):
            event_queue.put(("event", event_type, event_payload))
        return GenerationService(GenerationEngine(runner, rhyme_dir=rhyme_dir, meter_source=meter_dir), event_callback=emit).execute(kind, payload)
    finally:
        runner._model = None
        runner._tokenizer = None
        try:
            import torch
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        except Exception:
            pass


def _process_entry(queue, model_name, quantization, rhyme_dir, meter_dir, kind, payload):
    try:
        result = _run_generation_process(queue, model_name, quantization, rhyme_dir, meter_dir, kind, payload)
        queue.put(("result", True, result))
    except Exception as exc:
        queue.put(("result", False, (str(getattr(exc, "code", "WORKER_EXECUTION_ERROR")), type(exc).__name__, str(exc))))


def build_worker() -> GpuWorker:
    model_name = os.getenv("SHIJU_MODEL_PATH")
    if not model_name:
        raise RuntimeError("必须设置 SHIJU_MODEL_PATH")
    model_path = Path(model_name)
    if model_path.is_absolute() and not model_path.exists():
        raise RuntimeError(f"SHIJU_MODEL_PATH 不存在: {model_path}")
    control_url = os.getenv("SHIJU_CONTROL_URL", "http://127.0.0.1:8000")
    token = os.getenv("SHIJU_WORKER_TOKEN", "change-me-worker")
    worker_id = os.getenv("SHIJU_WORKER_ID", socket.gethostname())
    quantization = os.getenv("SHIJU_QUANTIZATION", "8bit")
    rhyme_dir = str(Path(os.getenv("SHIJU_RHYME_DIR", "Rhyme")))
    meter_dir = str(Path(os.getenv("SHIJU_METER_DIR", "Songci_Meter")))
    def process_runner(kind, payload, on_event=None, should_cancel=None):
        context = multiprocessing.get_context("spawn")
        event_queue = context.Queue()
        process = context.Process(target=_process_entry, args=(event_queue, model_name, quantization, rhyme_dir, meter_dir, kind, payload))
        process.start()
        outcome = None
        while process.is_alive() or outcome is None:
            if should_cancel and should_cancel():
                process.terminate()
                process.join(timeout=10)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                raise WorkerCancelled("任务已由用户取消")
            try:
                message = event_queue.get(timeout=0.25)
            except queue.Empty:
                if not process.is_alive(): break
                continue
            if message[0] == "event":
                if on_event: on_event(message[1], message[2])
            elif message[0] == "result":
                outcome = (message[1], message[2])
                if not process.is_alive(): break
        process.join()
        if outcome is None:
            raise WorkerProcessError("WORKER_PROCESS_FAILED", f"GPU 子进程异常退出，退出码 {process.exitcode}")
        ok, value = outcome
        if not ok: raise WorkerProcessError(value[0], f"{value[1]}: {value[2]}")
        return value
    return GpuWorker(
        worker_id,
        WorkerApiClient(control_url, token),
        None,
        capabilities={
            "model": model_name,
            "quantization": quantization,
            "tasks": ["generate", "partial_generate", "rewrite"],
            "concurrency": 1,
        },
        process_runner=process_runner,
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("SHIJU_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = build_worker()
    LOGGER.info(
        "Worker 已连接控制面，开始领取任务: worker_id=%s control_url=%s",
        worker.worker_id,
        worker.client.base_url,
    )
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.run_forever()


if __name__ == "__main__":
    main()
