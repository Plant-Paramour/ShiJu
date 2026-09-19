import sys

import pytest

from apps.api.database import Database
from apps.api.job_repository import IdempotencyConflict, JobRepository


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


def _repository(tmp_path):
    database = Database(tmp_path / "jobs.db")
    database.initialize()
    clock = Clock()
    return JobRepository(database, clock=clock), clock


def test_job_submission_is_idempotent_and_conflicts_on_changed_payload(tmp_path):
    repository, _ = _repository(tmp_path)
    first = repository.submit("generate", {"theme": "春"}, idempotency_key="same")
    repeated = repository.submit("generate", {"theme": "春"}, idempotency_key="same")

    assert repeated.id == first.id
    with pytest.raises(IdempotencyConflict):
        repository.submit("generate", {"theme": "秋"}, idempotency_key="same")


def test_worker_claim_heartbeat_and_completion(tmp_path):
    repository, clock = _repository(tmp_path)
    submitted = repository.submit("generate", {"theme": "春"})

    claimed = repository.claim("worker-1", {"model": "fake"}, lease_seconds=30)
    assert claimed.id == submitted.id
    assert claimed.status == "running"
    assert repository.has_live_worker()

    clock.value += 10
    repository.heartbeat(claimed.id, "worker-1", lease_seconds=30)
    repository.complete(claimed.id, "worker-1", {"text": "春山"})
    completed = repository.get(claimed.id)
    assert completed.status == "succeeded"
    assert completed.result == {"text": "春山"}


def test_expired_lease_requeues_then_fails_after_second_attempt(tmp_path):
    repository, clock = _repository(tmp_path)
    submitted = repository.submit("rewrite", {"text": "旧句"}, max_attempts=2)
    first = repository.claim("worker-1", {}, lease_seconds=5)
    clock.value += 6
    second = repository.claim("worker-2", {}, lease_seconds=5)
    assert second.id == submitted.id
    assert second.attempts == 2

    clock.value += 6
    assert repository.claim("worker-3", {}, lease_seconds=5) is None
    assert repository.get(submitted.id).status == "failed"


def test_control_plane_modules_do_not_import_torch():
    before = set(sys.modules)
    __import__("apps.api.main")
    newly_loaded = set(sys.modules).difference(before)
    assert "torch" not in newly_loaded

