from __future__ import annotations

import threading
import time
import hashlib
import uuid
from collections import defaultdict, deque


class RequestRateLimiter:
    """限流状态可选持久化到共享数据库，供多个 API 进程共同执行。"""

    def __init__(self, *, global_concurrency: int, user_concurrency: int, daily_quota: int, clock=time.time, database=None):
        self.global_concurrency = max(1, global_concurrency)
        self.user_concurrency = max(1, user_concurrency)
        self.daily_quota = max(1, daily_quota)
        self._clock = clock
        self._database = database
        self._active = 0
        self._active_users: defaultdict[str, int] = defaultdict(int)
        self._daily: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def acquire(self, identity: str) -> bool:
        if self._database is not None:
            return self._acquire_shared(identity)
        now = self._clock()
        cutoff = now - 86400
        with self._lock:
            history = self._daily[identity]
            while history and history[0] <= cutoff:
                history.popleft()
            if self._active >= self.global_concurrency:
                return False
            if self._active_users[identity] >= self.user_concurrency:
                return False
            if len(history) >= self.daily_quota:
                return False
            self._active += 1
            self._active_users[identity] += 1
            history.append(now)
            return True

    def release(self, identity: str) -> None:
        if self._database is not None:
            self._release_shared(identity)
            return
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active_users[identity] > 1:
                self._active_users[identity] -= 1
            else:
                self._active_users.pop(identity, None)

    def _acquire_shared(self, identity: str) -> bool:
        now = self._clock()
        cutoff = now - 86400
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._database.is_postgres:
                connection.execute("LOCK TABLE agent_rate_limit_requests IN EXCLUSIVE MODE")
            connection.execute(
                "DELETE FROM agent_rate_limit_requests WHERE active=0 AND created_at<=?",
                (cutoff,),
            )
            active_global = connection.execute(
                "SELECT COUNT(*) FROM agent_rate_limit_requests WHERE active=1"
            ).fetchone()[0]
            active_user = connection.execute(
                "SELECT COUNT(*) FROM agent_rate_limit_requests WHERE active=1 AND identity_hash=?",
                (identity_hash,),
            ).fetchone()[0]
            daily_user = connection.execute(
                "SELECT COUNT(*) FROM agent_rate_limit_requests WHERE identity_hash=? AND created_at>?",
                (identity_hash, cutoff),
            ).fetchone()[0]
            if active_global >= self.global_concurrency:
                return False
            if active_user >= self.user_concurrency or daily_user >= self.daily_quota:
                return False
            connection.execute(
                "INSERT INTO agent_rate_limit_requests(id,identity_hash,created_at,active) VALUES (?,?,?,1)",
                (str(uuid.uuid4()), identity_hash, now),
            )
        return True

    def _release_shared(self, identity: str) -> None:
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._database.is_postgres:
                connection.execute("LOCK TABLE agent_rate_limit_requests IN EXCLUSIVE MODE")
            row = connection.execute(
                "SELECT id FROM agent_rate_limit_requests WHERE identity_hash=? AND active=1 ORDER BY created_at DESC,id DESC LIMIT 1",
                (identity_hash,),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE agent_rate_limit_requests SET active=0 WHERE id=?",
                    (row[0],),
                )
