"""Stress tests for rate limiter and retry backoff logic."""

import random
import time
from pathlib import Path

import requests

from config import CACHE_DIR, CIK
from rate_limiter import RateLimiter


class FailingSession:
    """
    Fake requests session that fails the first N calls with 429/503,
    then succeeds. Proves backoff logic recovers.
    """
    def __init__(self, fail_count=3):
        self.fail_count = fail_count
        self.calls = 0
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_count:
            code = 429 if self.calls % 2 == 1 else 503
            resp = requests.Response()
            resp.status_code = code
            resp._content = b"fake error"
            resp.url = url
            return resp
        
        # Success
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"OK"
        return resp


def test_backoff_recovery():
    """
    Prove that after 3 transient failures, the system succeeds
    via exponential backoff + jitter.
    """
    from downloader import SECDownloader
    
    limiter = RateLimiter(max_requests=100, window_seconds=1.0)  # Very permissive
    fake_session = FailingSession(fail_count=3)
    
    # Monkey-patch the session
    downloader = SECDownloader(
        cik="0001144879",
        cache_dir=Path("cache"),
        user_agent="test",
        rate_limiter=limiter,
    )
    downloader.session = fake_session
    
    start = time.time()
    try:
        # This should retry 3 times, then succeed
        resp = downloader._request("http://fake.url", context="stress-test")
        elapsed = time.time() - start
        
        print(f"Success after {fake_session.calls} attempts")
        print(f"Elapsed: {elapsed:.2f}s (should be >2s due to backoff sleeps)")
        assert elapsed > 1.5, "Backoff should have added delay"
        print("PASS: Backoff recovery works")
        
    except Exception as e:
        print(f"FAIL: {e}")
        raise


def test_rate_limit_burst_protection():
    """
    Fire 50 requests with a limit of 5/sec.
    Prove no 1-second window exceeds 5.
    """
    limiter = RateLimiter(max_requests=5, window_seconds=1.0)
    
    timestamps = []
    for i in range(50):
        ts = limiter.acquire(context=f"burst-{i}")
        timestamps.append(ts)
    
    # Check every window
    violations = 0
    for i, start in enumerate(timestamps):
        window_end = start + 1.0
        count = sum(1 for t in timestamps if start <= t < window_end)
        if count > 5:
            violations += 1
    
    print(f"50 requests, limit=5/sec, violations={violations}")
    assert violations == 0, f"Found {violations} violating windows"
    print("PASS: Burst protection works at 5 req/sec")


if __name__ == "__main__":
    test_backoff_recovery()
    test_rate_limit_burst_protection()
    print("\nRate limiter stress tests passed.")
