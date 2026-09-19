from apps.gpu_worker.worker import GpuWorker


class FakeClient:
    def __init__(self):
        self.completed = []
        self.failed = []

    def complete(self, job_id, worker_id, result):
        self.completed.append((job_id, worker_id, result))

    def fail(self, job_id, worker_id, code, message, retryable):
        self.failed.append((job_id, worker_id, code, message, retryable))

    def heartbeat(self, job_id, worker_id):
        return None


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

