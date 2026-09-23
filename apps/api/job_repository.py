from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from shiju.contracts import JobStatus

from .database import Database
from .event_repository import EventRepository


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
    user_id: str | None = None
    conversation_id: str | None = None

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
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
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
        user_id: str | None = None,
        conversation_id: str | None = None,
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
                    attempts, max_attempts, created_at, updated_at, user_id, conversation_id
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
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
                    user_id,
                    conversation_id,
                ),
            )
            candidate_count = int(request.get("candidate_count", 0) or 0)
            if candidate_count > 0:
                for ordinal in range(1, candidate_count + 1):
                    connection.execute(
                        "INSERT INTO job_candidates(id,job_id,ordinal,updated_at) VALUES (?,?,?,?)",
                        (str(uuid.uuid4()), job_id, ordinal, now),
                    )
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            record = self._record(row)
        EventRepository(self.database, clock=self._clock).append_job_event(
            job_id, "job.submitted", {"kind": kind, "total": candidate_count}
        )
        return record

    def get(self, job_id: str) -> JobRecord:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return self._record(row)

    def assign_user(self, job_id: str, user_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE jobs SET user_id = ? WHERE id = ? AND user_id IS NULL", (user_id, job_id))

    def assign_context(self, job_id: str, user_id: str, conversation_id: str | None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET user_id = ?, conversation_id = ? WHERE id = ?",
                (user_id, conversation_id, job_id),
            )

    def list_for_user(
        self,
        user_id: str,
        conversation_id: str | None = None,
        *,
        active_only: bool = False,
    ) -> list[JobRecord]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if active_only:
            clauses.append("status IN ('queued', 'running')")
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY created_at",
                params,
            ).fetchall()
        return [self._record(row) for row in rows]

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
        row = self.get(job_id)
        if row.user_id:
            from .user_repository import UserRepository

            UserRepository(self.database).save_poem(row.user_id, job_id, row.request, dict(result))
        EventRepository(self.database, clock=self._clock).append_job_event(job_id, "job.completed", {"result": dict(result)})

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
        EventRepository(self.database, clock=self._clock).append_job_event(job_id, "job.failed", {"code": code, "message": message, "retrying": should_retry})

    def update_candidate(self, job_id: str, ordinal: int, *, status: str | None = None,
                         attempt: int | None = None, partial_text: str | None = None,
                         raw_text: str | None = None, title: str | None = None,
                         content: str | None = None, error: str | None = None,
                         started_at: float | None = None, finished_at: float | None = None) -> dict[str, Any]:
        fields = {"status": status, "attempt": attempt, "partial_text": partial_text, "raw_text": raw_text,
                  "title": title, "content": content, "error": error, "started_at": started_at, "finished_at": finished_at}
        fields = {key: value for key, value in fields.items() if value is not None}
        fields["updated_at"] = self._clock()
        with self.database.connect() as connection:
            existing = connection.execute("SELECT id FROM job_candidates WHERE job_id=? AND ordinal=?", (job_id, ordinal)).fetchone()
            if existing is None:
                connection.execute("INSERT INTO job_candidates(id,job_id,ordinal,updated_at) VALUES (?,?,?,?)", (str(uuid.uuid4()), job_id, ordinal, fields["updated_at"]))
            assignments = ", ".join(f"{key}=?" for key in fields)
            connection.execute(f"UPDATE job_candidates SET {assignments} WHERE job_id=? AND ordinal=?", (*fields.values(), job_id, ordinal))
            row = connection.execute("SELECT * FROM job_candidates WHERE job_id=? AND ordinal=?", (job_id, ordinal)).fetchone()
        value = dict(row)
        evaluation_json = value.pop("evaluation_json", None)
        value["evaluation"] = json.loads(evaluation_json) if evaluation_json else None
        job = self.get(job_id)
        if status == "succeeded" and job.user_id and content:
            from .user_repository import UserRepository

            UserRepository(self.database).save_candidate_poem(
                job.user_id,
                job_id,
                ordinal,
                job.request,
                {
                    "title": title,
                    "content": content,
                    "text": content,
                },
                value.get("evaluation"),
            )
        EventRepository(self.database, clock=self._clock).append_job_event(job_id, "candidate.updated", value)
        return value

    def save_candidate_evaluation(
        self,
        job_id: str,
        ordinal: int,
        evaluation: Mapping[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        job = self.get(job_id)
        if job.user_id != user_id:
            raise JobNotFound(job_id)
        payload = json.dumps(dict(evaluation), ensure_ascii=False, separators=(",", ":"))
        now = self._clock()
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE job_candidates SET evaluation_json=?,updated_at=? "
                "WHERE job_id=? AND ordinal=? AND status='succeeded'",
                (payload, now, job_id, ordinal),
            )
            archived = connection.execute(
                "UPDATE poems SET evaluation_json=? "
                "WHERE job_id=? AND candidate_ordinal=? AND user_id=?",
                (payload, job_id, ordinal, user_id),
            )
            if updated.rowcount != 1 and archived.rowcount != 1:
                raise ValueError("候选尚未生成完成")
        EventRepository(self.database, clock=self._clock).append_job_event(
            job_id,
            "candidate.evaluated",
            {"ordinal": ordinal, "evaluation": dict(evaluation)},
        )
        return dict(evaluation)

    def candidates(self, job_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT ordinal,status,attempt,partial_text,raw_text,title,content,error,started_at,finished_at,updated_at,evaluation_json FROM job_candidates WHERE job_id=? ORDER BY ordinal", (job_id,)).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            evaluation_json = value.pop("evaluation_json", None)
            value["evaluation"] = json.loads(evaluation_json) if evaluation_json else None
            values.append(value)
        return values

    def snapshot(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        candidates = self.candidates(job_id)
        total = len(candidates) or int(job.request.get("candidate_count", 0) or 0)
        completed = sum(1 for item in candidates if item["status"] == "succeeded")
        return {"job_id": job_id, "kind": job.kind, "status": job.status, "created_at": job.created_at, "total": total, "completed": completed,
                "request": job.request, "candidates": candidates, "result": job.result, "error": job.to_dict()["error"]}

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
            user_id=row["user_id"] if "user_id" in row.keys() else None,
            conversation_id=row["conversation_id"] if "conversation_id" in row.keys() else None,
        )
