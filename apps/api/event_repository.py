from __future__ import annotations

import json
import time
import uuid
from typing import Any, Mapping

from .database import Database


class EventRepository:
    """持久化 Agent turn、对话事件和任务进度事件。"""

    def __init__(self, database: Database, *, clock=time.time):
        self.database = database
        self._clock = clock

    def start_turn(self, *, user_id: str | None, conversation_id: str | None,
                   user_message_id: str | None = None,
                   assistant_message_id: str | None = None) -> str:
        turn_id = str(uuid.uuid4())
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO agent_turns(id,user_id,conversation_id,user_message_id,assistant_message_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (turn_id, user_id, conversation_id, user_message_id, assistant_message_id, now, now),
            )
        return turn_id

    def append_agent_event(self, turn_id: str, event_type: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT conversation_id,last_event_seq FROM agent_turns WHERE id = ?", (turn_id,)).fetchone()
            if row is None:
                raise KeyError(turn_id)
            if row[0]:
                latest = connection.execute("SELECT COALESCE(MAX(e.seq),0) FROM agent_events e JOIN agent_turns t ON t.id=e.turn_id WHERE t.conversation_id=?", (row[0],)).fetchone()
                seq = int(latest[0]) + 1
            else:
                seq = int(row[1]) + 1
            event_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO agent_events(id,turn_id,seq,event_type,payload_json,created_at) VALUES (?,?,?,?,?,?)",
                (event_id, turn_id, seq, event_type, json.dumps(payload, ensure_ascii=False), now),
            )
            connection.execute("UPDATE agent_turns SET last_event_seq=?,updated_at=? WHERE id=?", (seq, now, turn_id))
        return {"id": event_id, "turn_id": turn_id, "seq": seq, "event_type": event_type, "payload": payload, "created_at": now}

    def finish_turn(self, turn_id: str, status: str = "completed") -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE agent_turns SET status=?,updated_at=? WHERE id=?", (status, self._clock(), turn_id))

    def list_agent_events(self, conversation_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT e.*, t.conversation_id FROM agent_events e JOIN agent_turns t ON t.id=e.turn_id WHERE t.conversation_id=? AND e.seq>? ORDER BY e.created_at,e.id LIMIT ?",
                (conversation_id, after, limit),
            ).fetchall()
        return [self._event(row) for row in rows]

    def append_job_event(self, job_id: str, event_type: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        now = self._clock()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT COALESCE(MAX(seq),0) FROM job_events WHERE job_id=?", (job_id,)).fetchone()
            seq = int(row[0]) + 1
            event_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO job_events(id,job_id,seq,event_type,payload_json,created_at) VALUES (?,?,?,?,?,?)",
                (event_id, job_id, seq, event_type, json.dumps(payload, ensure_ascii=False), now),
            )
        return {"id": event_id, "job_id": job_id, "seq": seq, "event_type": event_type, "payload": payload, "created_at": now}

    def list_job_events(self, job_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM job_events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (job_id, after, limit)).fetchall()
        return [self._event(row) for row in rows]

    @staticmethod
    def _event(row) -> dict[str, Any]:
        return {
            "id": row["id"], "turn_id": row["turn_id"] if "turn_id" in row.keys() else None,
            "job_id": row["job_id"] if "job_id" in row.keys() else None,
            "seq": row["seq"], "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]), "created_at": row["created_at"],
        }
