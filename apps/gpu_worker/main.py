from __future__ import annotations

import logging
import os
import signal
import socket
from pathlib import Path

from shiju.generation.engine import GenerationEngine
from shiju.generation.model_runner import ModelRunner
from shiju.generation.result import ModelSettings
from shiju.service.generation_service import GenerationService

from .api_client import WorkerApiClient
from .worker import GpuWorker


def build_worker() -> GpuWorker:
    model_name = os.getenv("SHIJU_MODEL_PATH")
    if not model_name:
        raise RuntimeError("必须设置 SHIJU_MODEL_PATH")
    control_url = os.getenv("SHIJU_CONTROL_URL", "http://127.0.0.1:8000")
    token = os.getenv("SHIJU_WORKER_TOKEN", "change-me-worker")
    worker_id = os.getenv("SHIJU_WORKER_ID", socket.gethostname())
    quantization = os.getenv("SHIJU_QUANTIZATION", "8bit")
    runner = ModelRunner(ModelSettings(model_name=model_name, quantization=quantization))
    engine = GenerationEngine(
        runner,
        rhyme_dir=Path(os.getenv("SHIJU_RHYME_DIR", "Rhyme")),
        meter_source=Path(os.getenv("SHIJU_METER_DIR", "Songci_Meter")),
    )
    return GpuWorker(
        worker_id,
        WorkerApiClient(control_url, token),
        GenerationService(engine),
        capabilities={
            "model": model_name,
            "quantization": quantization,
            "tasks": ["generate", "rewrite"],
            "concurrency": 1,
        },
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("SHIJU_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = build_worker()
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.run_forever()


if __name__ == "__main__":
    main()

