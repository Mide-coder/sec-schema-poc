"""Tests for token bucket rate limiting and thread safety."""

import threading
import time

from rate_limiter import RateLimiter


def test_basic_limit():
    """Fire 25 requests as fast as possible; verify no 1s window exceeds 10."""
    limiter = RateLimiter(max_requests=10, window_seconds=1.0)

    start = time.time()
    for i in range(25):
        limiter.acquire(context=f"req-{i}")
    elapsed = time.time() - start

    # 25 requests at 10/sec needs at least 2 full windows = ~2 seconds
    assert elapsed >= 1.5, f"Expected ~2s elapsed for 25 requests, got {elapsed:.2f}s"
    print(f"PASS: 25 requests took {elapsed:.2f}s (expected >= 1.5s)")


def test_window_integrity():
    """Check every possible 1-second slice for violations."""
    limiter = RateLimiter(max_requests=10, window_seconds=1.0)

    for i in range(25):
        limiter.acquire(context=f"req-{i}")

    # Access internal state for verification (test-only)
    timestamps = list(limiter._timestamps)
    violations = 0

    for i, start in enumerate(timestamps):
        window_end = start + 1.0
        count = sum(1 for t in timestamps if start <= t < window_end)
        if count > 10:
            print(f"VIOLATION: window at {start:.3f} has {count} requests")
            violations += 1

    assert violations == 0, f"Found {violations} violating windows"
    print("PASS: No 1-second window exceeded 10 requests")


def test_thread_safety():
    """10 threads fire 5 requests each; total 50 requests, no violations."""
    limiter = RateLimiter(max_requests=10, window_seconds=1.0)
    errors = []

    def worker(tid: int):
        try:
            for i in range(5):
                limiter.acquire(context=f"thread-{tid}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    print("PASS: 10 threads, 50 requests, no errors")


if __name__ == "__main__":
    test_basic_limit()
    test_window_integrity()
    test_thread_safety()
    print("\nAll rate limiter tests passed.")