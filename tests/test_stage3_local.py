from __future__ import annotations

import threading
import time

from apps.agent.executor import AgentExecutor
from apps.agent.framework import AgentTurnPaused
from apps.api.database import Database
from apps.api.event_repository import EventRepository
from apps.api.job_repository import IdempotencyConflict, JobRepository
from apps.api.user_repository import UserRepository


class CooperativeAgent:
    def __init__(self, *, wait_for_cancel=False):
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()

    def respond_stream(self, message, session_id=None, cancellation_event=None, **kwargs):
        self.started.set()
        yield {"event_type": "assistant.delta", "payload": {"text": "开篇"}}
        if self.wait_for_cancel:
            while cancellation_event is None or not cancellation_event.wait(0.01):
                pass
            raise AgentTurnPaused("cancelled")
        yield {
            "event_type": "turn.completed",
            "payload": {"reply": "开篇完成", "jobs": [], "session_id": session_id},
        }


def _create_turn(database, *, key="agent-idem-1", max_attempts=2):
    jobs = JobRepository(database)
    events = EventRepository(database)
    turn_id = events.start_turn(
        user_id=None,
        conversation_id=None,
        status="queued",
    )
    payload = {"turn_id": turn_id, "message": "写一句山水", "session_id": "session-1"}
    job = jobs.submit(
        "agent_turn",
        payload,
        idempotency_key=key,
        max_attempts=max_attempts,
        agent_turn_id=turn_id,
    )
    events.append_agent_event(turn_id, "turn.queued", {"turn_id": turn_id})
    return jobs, events, turn_id, payload, job


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_agent_turn_idempotency_and_worker_kind_isolation(tmp_path):
    database = Database(tmp_path / "agent-idempotency.db")
    database.initialize()
    jobs, _, _, payload, first = _create_turn(database)

    assert jobs.submit(
        "agent_turn", payload, idempotency_key="agent-idem-1", agent_turn_id=payload["turn_id"]
    ).id == first.id
    try:
        jobs.submit(
            "agent_turn",
            {**payload, "message": "不同内容"},
            idempotency_key="agent-idem-1",
            agent_turn_id=payload["turn_id"],
        )
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError("changed request with same idempotency key must conflict")

    assert jobs.claim("gpu-worker", {}) is None
    agent = CooperativeAgent()
    executor = AgentExecutor(jobs, UserRepository(database), agent, worker_id="agent-worker")
    assert executor.run_once() is True
    assert jobs.get(first.id).status == "succeeded"
    assert EventRepository(database).get_turn(payload["turn_id"])["status"] == "completed"


def test_agent_cancel_handshake_persists_matching_job_and_turn_events(tmp_path):
    database = Database(tmp_path / "agent-cancel.db")
    database.initialize()
    jobs, events, turn_id, _, job = _create_turn(database)
    agent = CooperativeAgent(wait_for_cancel=True)
    executor = AgentExecutor(
        jobs,
        UserRepository(database),
        agent,
        worker_id="agent-cancel-worker",
        lease_seconds=1,
    )
    thread = threading.Thread(target=executor.run_once)
    thread.start()
    try:
        assert agent.started.wait(2)
        assert _wait_for(lambda: any(e["event_type"] == "assistant.delta" for e in events.list_turn_events(turn_id)))
        assert jobs.cancel(job.id).status == "running"
        thread.join(timeout=3)
        assert not thread.is_alive()

        assert jobs.get(job.id).status == "cancelled"
        assert events.get_turn(turn_id)["status"] == "cancelled"
        assert [e["event_type"] for e in events.list_turn_events(turn_id)][-1] == "turn.cancelled"
        assert any(e["event_type"] == "job.cancelled" for e in events.list_job_events(job.id))
    finally:
        if thread.is_alive():
            executor.stop()
            thread.join(timeout=2)


def test_agent_timeout_finishes_job_turn_and_error_events(tmp_path):
    database = Database(tmp_path / "agent-timeout.db")
    database.initialize()
    jobs, events, turn_id, _, job = _create_turn(database)
    agent = CooperativeAgent(wait_for_cancel=True)
    executor = AgentExecutor(
        jobs,
        UserRepository(database),
        agent,
        worker_id="agent-timeout-worker",
        lease_seconds=1,
        turn_timeout_seconds=0.15,
    )
    thread = threading.Thread(target=executor.run_once)
    thread.start()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert jobs.get(job.id).status == "failed"
    assert jobs.get(job.id).error_code == "AGENT_TIMEOUT"
    assert events.get_turn(turn_id)["status"] == "failed"
    assert any(e["event_type"] == "turn.failed" for e in events.list_turn_events(turn_id))
    assert any(e["event_type"] == "job.failed" for e in events.list_job_events(job.id))
    assert jobs.claim("agent-worker-after-timeout", {}, kinds=("agent_turn",)) is None


def test_expired_agent_executor_lease_is_reclaimed_after_restart(tmp_path):
    class Clock:
        value = 1000.0

        def __call__(self):
            return self.value

    database = Database(tmp_path / "agent-recovery.db")
    database.initialize()
    clock = Clock()
    jobs = JobRepository(database, clock=clock)
    events = EventRepository(database, clock=clock)
    turn_id = events.start_turn(user_id=None, conversation_id=None, status="queued")
    payload = {"turn_id": turn_id, "message": "恢复", "session_id": "session-1"}
    submitted = jobs.submit(
        "agent_turn",
        payload,
        idempotency_key="agent-recovery",
        max_attempts=2,
        agent_turn_id=turn_id,
    )
    first = jobs.claim("executor-before-restart", {}, lease_seconds=5, kinds=("agent_turn",))
    assert first.id == submitted.id
    clock.value += 6

    service = CooperativeAgent()
    restarted = AgentExecutor(
        jobs,
        UserRepository(database),
        service,
        worker_id="executor-after-restart",
    )
    assert restarted.run_once() is True
    recovered = jobs.get(submitted.id)
    assert recovered.status == "succeeded"
    assert recovered.attempts == 2
    assert events.get_turn(turn_id)["status"] == "completed"
    assert [e["event_type"] for e in events.list_turn_events(turn_id)][-1] == "turn.completed"
