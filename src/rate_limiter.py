"""Sliding-window rate limiter enforcing request rate limits."""

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Enforces a hard ceiling on request rate using a sliding time window.
    
    Design rationale:
    - deque gives O(1) eviction of stale timestamps
    - lock is held only for brief window manipulation; sleep happens outside
      so future thread pools don't serialize on the limiter
    - jitter is not needed here (we sleep precisely until the window opens),
      but the caller adds jitter via retry logic in the downloader
    """

    def __init__(self, max_requests: int = 10, window_seconds: float = 1.0):
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, context: str = "") -> float:
        """
        Block until a request slot is available.
        Returns the timestamp at which the request was allowed.
        """
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - self.window

                # Evict timestamps that have fallen outside the window
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()

                # If under the limit, grant immediately
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    count = len(self._timestamps)
                    logger.info(
                        "Rate limit OK [%s]: %d/%d in %.1fs window",
                        context, count, self.max_requests, self.window
                    )
                    return now

                # Window is full; compute how long to sleep
                sleep_until = self._timestamps[0] + self.window
                sleep_time = max(0.0, sleep_until - now)
                logger.debug(
                    "Rate limit WAIT [%s]: window full (%d/%d), sleep %.3fs",
                    context, len(self._timestamps), self.max_requests, sleep_time
                )

            # Sleep OUTSIDE the lock so other threads can make progress
            time.sleep(sleep_time)

    def get_current_count(self) -> int:
        """Return the number of requests in the current window."""
        with self._lock:
            now = time.time()
            cutoff = now - self.window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)