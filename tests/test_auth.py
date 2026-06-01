from cs2webui.core.auth import LoginRateLimiter


def test_login_rate_limiter_bounds_tracked_failure_keys() -> None:
    limiter = LoginRateLimiter(limit=2, window_seconds=60, max_keys=2)

    assert limiter.allows("new-key") is True
    assert limiter._failures == {}

    limiter.record_failure("first")
    limiter.record_failure("second")
    limiter.record_failure("third")

    assert set(limiter._failures) == {"second", "third"}
