from apps.api.rate_limit import RequestRateLimiter


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

