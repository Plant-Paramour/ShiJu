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


def test_jobs_can_be_restored_by_user_and_conversation(tmp_path):
    repository, _ = _repository(tmp_path)
    with repository.database.connect() as connection:
        connection.execute(
            "INSERT INTO users(id, username, password_hash, display_name) VALUES ('user-1', 'restore-user', 'unused', 'Restore User')"
        )
        connection.execute(
            "INSERT INTO conversations(id, user_id, title, created_at, updated_at) VALUES ('conversation-1', 'user-1', '春', 1, 1), ('conversation-2', 'user-1', '秋', 2, 2)"
        )
    first = repository.submit(
        "generate",
        {"theme": "春"},
        user_id="user-1",
        conversation_id="conversation-1",
    )
    repository.submit(
        "generate",
        {"theme": "秋"},
        user_id="user-1",
        conversation_id="conversation-2",
    )

    restored = repository.list_for_user("user-1", "conversation-1")

    assert [job.id for job in restored] == [first.id]
    assert restored[0].conversation_id == "conversation-1"
    assert repository.list_for_user("user-1", active_only=True)[0].status == "queued"


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


def test_succeeded_candidate_is_archived_and_evaluation_is_persisted(tmp_path):
    repository, _ = _repository(tmp_path)
    with repository.database.connect() as connection:
        connection.execute(
            "INSERT INTO users(id, username, password_hash, display_name) VALUES ('user-1', 'poet', 'unused', 'Poet')"
        )
    request = {
        "meter_type": "唐诗",
        "form_name": "五言绝句",
        "theme": "春山",
        "candidate_count": 2,
    }
    job = repository.submit("generate", request, user_id="user-1")

    repository.update_candidate(
        job.id,
        1,
        status="succeeded",
        title="春山",
        content="春山含宿雨，幽径起新烟。\n鸟过青林外，钟来古寺边。",
        finished_at=1000.0,
    )

    from apps.api.user_repository import UserRepository

    poems = UserRepository(repository.database).list_poems("user-1")
    assert len(poems) == 1
    assert poems[0]["candidate_ordinal"] == 1

    evaluation = {"version": 1, "rhyme_book_name": "平水韵", "structure_score": 100}
    repository.save_candidate_evaluation(job.id, 1, evaluation, user_id="user-1")

    snapshot = repository.snapshot(job.id)
    poems = UserRepository(repository.database).list_poems("user-1")
    assert snapshot["request"]["theme"] == "春山"
    assert snapshot["candidates"][0]["evaluation"] == evaluation
    assert poems[0]["evaluation"] == evaluation


def test_archived_poem_evaluation_survives_missing_candidate_row(tmp_path):
    repository, _ = _repository(tmp_path)
    with repository.database.connect() as connection:
        connection.execute(
            "INSERT INTO users(id, username, password_hash, display_name) VALUES ('user-1', 'poet', 'unused', 'Poet')"
        )
    job = repository.submit("generate", {"meter_type": "宋词", "form_name": "浣溪沙"}, user_id="user-1")
    with repository.database.connect() as connection:
        connection.execute(
            "INSERT INTO poems(id,user_id,job_id,title,content,meter_type,form_name,created_at,work_type,candidate_ordinal) "
            "VALUES ('poem-1','user-1',?,'浣溪沙','一曲新词','宋词','浣溪沙',1000,'宋词',1)",
            (job.id,),
        )

    evaluation = {"version": 1, "structure_score": 100}
    repository.save_candidate_evaluation(job.id, 1, evaluation, user_id="user-1")

    from apps.api.user_repository import UserRepository
    assert UserRepository(repository.database).list_poems("user-1")[0]["evaluation"] == evaluation
