"""Opt-in PostgreSQL 18 integration test for the disposable stage-three database."""

from __future__ import annotations

import os
import multiprocessing
import threading
import time
import uuid
import hashlib
from urllib.parse import urlparse

import pytest

from apps.api.database import Database
from apps.api.event_repository import EventRepository
from apps.api.job_repository import IdempotencyConflict, JobRepository
from apps.api.rate_limit import RequestRateLimiter
from apps.api.user_repository import UserRepository
from apps.agent.executor import AgentExecutor
from apps.agent.framework import AgentTurnPaused


class _PostgresCooperativeAgent:
    def __init__(self, *, wait_for_cancel=False):
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()

    def respond_stream(self, message, session_id=None, cancellation_event=None, **kwargs):
        self.started.set()
        yield {"event_type": "assistant.delta", "payload": {"text": "开始"}}
        if self.wait_for_cancel:
            while cancellation_event is None or not cancellation_event.wait(0.01):
                pass
            raise AgentTurnPaused("cancelled")
        yield {"event_type": "turn.completed", "payload": {"reply": "完成", "jobs": []}}


def _postgres_limit_acquire(url, identity, global_limit, user_limit, daily_limit, barrier, output):
    database = Database(url)
    limiter = RequestRateLimiter(
        global_concurrency=global_limit,
        user_concurrency=user_limit,
        daily_quota=daily_limit,
        database=database,
    )
    barrier.wait(timeout=10)
    output.put((identity, limiter.acquire(identity)))
    database.close()


@pytest.fixture
def stage3_postgres():
    url = os.getenv("SHIJU_STAGE3_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("set SHIJU_STAGE3_DATABASE_URL to the disposable shiju_stage3_test database")
    if urlparse(url).path.lstrip("/") != "shiju_stage3_test":
        pytest.fail("PostgreSQL integration tests are restricted to database shiju_stage3_test")
    database = Database(url)
    database.initialize()
    yield database
    database.close()


def test_postgres_agent_queue_idempotency_lease_and_restart_recovery(stage3_postgres):
    class Clock:
        value = 1_000.0

        def __call__(self):
            return self.value

    database = stage3_postgres
    clock = Clock()
    jobs = JobRepository(database, clock=clock)
    events = EventRepository(database, clock=clock)
    turn_id = events.start_turn(user_id=None, conversation_id=None, status="queued")
    worker_before = f"stage3-before-{turn_id}"
    worker_after = f"stage3-after-{turn_id}"
    payload = {"turn_id": turn_id, "message": "PostgreSQL recovery probe"}
    job = jobs.submit(
        "agent_turn",
        payload,
        idempotency_key=f"stage3-idem-{turn_id}",
        max_attempts=2,
        agent_turn_id=turn_id,
    )
    try:
        repeated = jobs.submit(
            "agent_turn",
            payload,
            idempotency_key=f"stage3-idem-{turn_id}",
            agent_turn_id=turn_id,
        )
        assert repeated.id == job.id
        with pytest.raises(IdempotencyConflict):
            jobs.submit(
                "agent_turn",
                {**payload, "message": "changed"},
                idempotency_key=f"stage3-idem-{turn_id}",
                agent_turn_id=turn_id,
            )

        # GPU workers use the repository's default job-kind filter.
        assert jobs.claim("stage3-gpu-worker", {}) is None
        claimed = jobs.claim(
            worker_before,
            {"service": "agent-executor"},
            lease_seconds=5,
            kinds=("agent_turn",),
        )
        assert claimed and claimed.id == job.id and claimed.attempts == 1
        assert jobs.heartbeat(job.id, worker_before, lease_seconds=5) is False
        clock.value += 6

        recovered = jobs.claim(
            worker_after,
            {"service": "agent-executor"},
            lease_seconds=5,
            kinds=("agent_turn",),
        )
        assert recovered and recovered.id == job.id and recovered.attempts == 2
        assert recovered.worker_id == worker_after
        jobs.complete(job.id, worker_after, {"turn_id": turn_id, "reply": "recovered"})
        assert jobs.get(job.id).status == "succeeded"
        assert jobs.get(job.id).result["reply"] == "recovered"
    finally:
        with database.connect() as connection:
            connection.execute("DELETE FROM job_events WHERE job_id=?", (job.id,))
            connection.execute("DELETE FROM agent_events WHERE turn_id=?", (turn_id,))
            connection.execute("DELETE FROM jobs WHERE id=?", (job.id,))
            connection.execute("DELETE FROM agent_turns WHERE id=?", (turn_id,))
            connection.execute("DELETE FROM workers WHERE id IN (?,?)", (worker_before, worker_after))


def test_postgres_agent_executor_cancel_and_timeout(stage3_postgres):
    database = stage3_postgres
    jobs = JobRepository(database)
    users = UserRepository(database)
    events = EventRepository(database)
    turn_ids = []
    job_ids = []

    def create_turn(key):
        turn_id = events.start_turn(user_id=None, conversation_id=None, status="queued")
        job = jobs.submit(
            "agent_turn",
            {"turn_id": turn_id, "message": key},
            idempotency_key=f"{key}:{turn_id}",
            max_attempts=2,
            agent_turn_id=turn_id,
        )
        turn_ids.append(turn_id)
        job_ids.append(job.id)
        return turn_id, job

    try:
        turn_id, job = create_turn("cancel")
        agent = _PostgresCooperativeAgent(wait_for_cancel=True)
        executor = AgentExecutor(jobs, users, agent, worker_id=f"stage3-cancel-{turn_id}", lease_seconds=1)
        thread = threading.Thread(target=executor.run_once)
        thread.start()
        assert agent.started.wait(3)
        assert jobs.cancel(job.id).status == "running"
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert jobs.get(job.id).status == "cancelled"
        assert events.get_turn(turn_id)["status"] == "cancelled"
        assert events.list_turn_events(turn_id)[-1]["event_type"] == "turn.cancelled"

        turn_id, job = create_turn("timeout")
        agent = _PostgresCooperativeAgent(wait_for_cancel=True)
        executor = AgentExecutor(
            jobs,
            users,
            agent,
            worker_id=f"stage3-timeout-{turn_id}",
            lease_seconds=1,
            turn_timeout_seconds=0.15,
        )
        thread = threading.Thread(target=executor.run_once)
        thread.start()
        assert agent.started.wait(3)
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert jobs.get(job.id).status == "failed"
        assert jobs.get(job.id).error_code == "AGENT_TIMEOUT"
        assert events.get_turn(turn_id)["status"] == "failed"
        assert events.list_turn_events(turn_id)[-1]["event_type"] == "turn.failed"
    finally:
        with database.connect() as connection:
            for job_id in job_ids:
                connection.execute("DELETE FROM job_events WHERE job_id=?", (job_id,))
                connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            for turn_id in turn_ids:
                connection.execute("DELETE FROM agent_events WHERE turn_id=?", (turn_id,))
                connection.execute("DELETE FROM agent_turns WHERE id=?", (turn_id,))


def test_postgres_rate_limits_are_shared_across_processes(stage3_postgres):
    database = stage3_postgres
    url = os.environ["SHIJU_STAGE3_DATABASE_URL"]
    ctx = multiprocessing.get_context("spawn")
    global_ids = [f"stage3-global-{uuid.uuid4()}" for _ in range(2)]
    daily_id = f"stage3-daily-{uuid.uuid4()}"
    try:
        # This database is disposable and dedicated to this integration suite.
        with database.connect() as connection:
            connection.execute("DELETE FROM agent_rate_limit_requests")
        barrier = ctx.Barrier(2)
        output = ctx.Queue()
        children = [
            ctx.Process(
                target=_postgres_limit_acquire,
                args=(url, identity, 1, 5, 100, barrier, output),
            )
            for identity in global_ids
        ]
        for child in children:
            child.start()
        global_results = [output.get(timeout=15) for _ in children]
        for child in children:
            child.join(timeout=5)
            assert child.exitcode == 0
        assert sorted(acquired for _, acquired in global_results) == [False, True]

        barrier = ctx.Barrier(2)
        output = ctx.Queue()
        children = [
            ctx.Process(
                target=_postgres_limit_acquire,
                args=(url, daily_id, 10, 2, 1, barrier, output),
            )
            for _ in range(2)
        ]
        for child in children:
            child.start()
        daily_results = [output.get(timeout=15) for _ in children]
        for child in children:
            child.join(timeout=5)
            assert child.exitcode == 0
        assert sorted(acquired for _, acquired in daily_results) == [False, True]
    finally:
        with database.connect() as connection:
            for identity in [*global_ids, daily_id]:
                digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                connection.execute(
                    "DELETE FROM agent_rate_limit_requests WHERE identity_hash=?", (digest,)
                )
