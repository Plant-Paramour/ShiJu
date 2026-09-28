from apps.api.rate_limit import RequestRateLimiter
from apps.api.database import Database


def test_rate_limiter_enforces_user_and_global_concurrency():
    limiter = RequestRateLimiter(global_concurrency=1, user_concurrency=1, daily_quota=2)
    assert limiter.acquire("u1") is True
    assert limiter.acquire("u1") is False
    assert limiter.acquire("u2") is False
    limiter.release("u1")
    assert limiter.acquire("u2") is True


def test_rate_limiter_enforces_daily_quota():
    limiter = RequestRateLimiter(global_concurrency=2, user_concurrency=2, daily_quota=1)
    assert limiter.acquire("u1") is True
    limiter.release("u1")
    assert limiter.acquire("u1") is False


def test_database_limiter_shares_concurrency_and_daily_quota(tmp_path):
    database = Database(tmp_path / "limits.db")
    database.initialize()
    now = [1000.0]
    options = {
        "global_concurrency": 2,
        "user_concurrency": 1,
        "daily_quota": 2,
        "clock": lambda: now[0],
        "database": database,
    }
    first_process = RequestRateLimiter(**options)
    second_process = RequestRateLimiter(**options)

    assert first_process.acquire("user-1") is True
    assert second_process.acquire("user-1") is False
    assert second_process.acquire("user-2") is True
    assert first_process.acquire("user-3") is False
    first_process.release("user-1")
    assert second_process.acquire("user-1") is True
    second_process.release("user-1")
    assert first_process.acquire("user-1") is False
    now[0] += 86401
    assert second_process.acquire("user-1") is True
