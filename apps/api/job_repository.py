from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from shiju.contracts import JobStatus

from .database import Database


class JobNotFound(KeyError):
    pass


class IdempotencyConflict(ValueError):
    pass


class JobOwnershipError(ValueError):
    pass


@dataclass(frozen=True)
class JobRecord:
    id: str
    kind: str
    status: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    attempts: int
    max_attempts: int
    worker_id: str | None
    lease_expires_at: float | None
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None

    def to_dict(self, *, include_request: bool = False) -> dict[str, Any]:
        value = {
            "job_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "result": self.result,
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code
                else None
            ),
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if include_request:
            value["request"] = self.request
        return value


class JobRepository:
    def __init__(self, database: Database, *, clock=time.time):
        self.database = database
        self._clock = clock

    def submit(
        self,
        kind: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 2,
    ) -> JobRecord:
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash or existing["kind"] != kind:
                        raise IdempotencyConflict("同一 Idempotency-Key 对应了不同请求")
                    return self._record(existing)
            job_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO jobs(
                    id, kind, status, request_json, request_hash, idempotency_key,
                    attempts, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    JobStatus.QUEUED.value,
                    canonical,
                    request_hash,
                    idempotency_key,
                    max_attempts,
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._record(row)

    def get(self, job_id: str) -> JobRecord:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return self._record(row)

    def claim(
        self,
        worker_id: str,
        capabilities: Mapping[str, Any],
        *,
        lease_seconds: int = 300,
    ) -> JobRecord | None:
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._touch_worker(connection, worker_id, capabilities, now)
            self._recover_expired(connection, now)
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at LIMIT 1",
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, worker_id = ?, attempts = attempts + 1,
                    lease_expires_at = ?, started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.RUNNING.value,
                    worker_id,
                    now + lease_seconds,
                    now,
                    now,
                    row["id"],
                    JobStatus.QUEUED.value,
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            return self._record(claimed)

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: int = 300) -> None:
        now = self._clock()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND worker_id = ? AND status = ?
                """,
                (now + lease_seconds, now, job_id, worker_id, JobStatus.RUNNING.value),
            )
        if result.rowcount != 1:
            raise JobOwnershipError(job_id)

    def complete(self, job_id: str, worker_id: str, result: Mapping[str, Any]) -> None:
        now = self._clock()
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE jobs
                SET status = ?, result_json = ?, error_code = NULL, error_message = NULL,
                    lease_expires_at = NULL, updated_at = ?, finished_at = ?
                WHERE id = ? AND worker_id = ? AND status = ?
                """,
                (
                    JobStatus.SUCCEEDED.value,
                    payload,
                    now,
                    now,
                    job_id,
                    worker_id,
                    JobStatus.RUNNING.value,
                ),
            )
        if updated.rowcount != 1:
            raise JobOwnershipError(job_id)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ? AND worker_id = ? AND status = ?",
                (job_id, worker_id, JobStatus.RUNNING.value),
            ).fetchone()
            if row is None:
                raise JobOwnershipError(job_id)
            should_retry = retryable and row["attempts"] < row["max_attempts"]
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, worker_id = NULL, lease_expires_at = NULL,
                    error_code = ?, error_message = ?, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.QUEUED.value if should_retry else JobStatus.FAILED.value,
                    code,
                    message,
                    now,
                    None if should_retry else now,
                    job_id,
                ),
            )

    def has_live_worker(self, *, max_age_seconds: int = 45) -> bool:
        threshold = self._clock() - max_age_seconds
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM workers WHERE last_seen_at >= ? LIMIT 1", (threshold,)
            ).fetchone()
        return row is not None

    @staticmethod
    def _touch_worker(connection, worker_id, capabilities, now) -> None:
        payload = json.dumps(capabilities, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO workers(id, capabilities_json, last_seen_at) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                capabilities_json = excluded.capabilities_json,
                last_seen_at = excluded.last_seen_at
            """,
            (worker_id, payload, now),
        )

    @staticmethod
    def _recover_expired(connection, now: float) -> None:
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, worker_id = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE status = ? AND lease_expires_at < ? AND attempts < max_attempts
            """,
            (JobStatus.QUEUED.value, now, JobStatus.RUNNING.value, now),
        )
        connection.execute(
            """
            UPDATE jobs
            SET status = ?, error_code = 'WORKER_LEASE_EXPIRED',
                error_message = 'Worker lease expired after maximum attempts',
                worker_id = NULL, lease_expires_at = NULL, updated_at = ?, finished_at = ?
            WHERE status = ? AND lease_expires_at < ? AND attempts >= max_attempts
            """,
            (JobStatus.FAILED.value, now, now, JobStatus.RUNNING.value, now),
        )

    @staticmethod
    def _record(row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            request=json.loads(row["request_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            worker_id=row["worker_id"],
            lease_expires_at=row["lease_expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

