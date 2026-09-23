import time

from apps.gpu_worker.worker import GpuWorker, WorkerCancelled


class FakeClient:
    def __init__(self):
        self.completed = []
        self.failed = []
        self.cancelled = []

    def complete(self, job_id, worker_id, result):
        self.completed.append((job_id, worker_id, result))

    def fail(self, job_id, worker_id, code, message, retryable):
        self.failed.append((job_id, worker_id, code, message, retryable))

    def heartbeat(self, job_id, worker_id):
        return False

    def acknowledge_cancel(self, job_id, worker_id):
        self.cancelled.append((job_id, worker_id))


class FakeService:
    def execute(self, kind, payload):
        return {"kind": kind, "payload": payload}


def test_fake_worker_executes_and_reports_result():
    client = FakeClient()
    worker = GpuWorker("worker-1", client, FakeService(), {"model": "fake"})

    worker._execute({"job_id": "job-1", "kind": "rewrite", "request": {"line": 2}})

    assert client.completed == [
        ("job-1", "worker-1", {"kind": "rewrite", "payload": {"line": 2}})
    ]
    assert client.failed == []


def test_worker_stops_process_runner_after_cancel_signal():
    client = FakeClient()
    client.heartbeat = lambda job_id, worker_id: True

    def process_runner(kind, payload, on_event, should_cancel):
        deadline = time.time() + 1
        while time.time() < deadline:
            if should_cancel():
                raise WorkerCancelled()
            time.sleep(0.005)
        raise AssertionError("未收到取消信号")

    worker = GpuWorker(
        "worker-1",
        client,
        None,
        {"model": "fake"},
        heartbeat_seconds=0.01,
        process_runner=process_runner,
    )
    worker._execute({"job_id": "job-1", "kind": "generate", "request": {}})

    assert client.cancelled == [("job-1", "worker-1")]
    assert client.completed == []
    assert client.failed == []

