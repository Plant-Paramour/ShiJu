from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RequestRateLimiter:
    """单进程第一阶段限流器；多实例共享状态留给 Redis 阶段。"""

    def __init__(self, *, global_concurrency: int, user_concurrency: int, daily_quota: int, clock=time.time):
        self.global_concurrency = max(1, global_concurrency)
        self.user_concurrency = max(1, user_concurrency)
        self.daily_quota = max(1, daily_quota)
        self._clock = clock
        self._active = 0
        self._active_users: defaultdict[str, int] = defaultdict(int)
        self._daily: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def acquire(self, identity: str) -> bool:
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
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active_users[identity] > 1:
                self._active_users[identity] -= 1
            else:
                self._active_users.pop(identity, None)

