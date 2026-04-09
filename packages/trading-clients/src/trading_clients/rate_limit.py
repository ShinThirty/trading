import threading
import time


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Tokens refill at a constant rate up to a maximum capacity.
    acquire() blocks until a token is available, then consumes it.

    Inspired by Apache Kafka's TokenBucket: tokens can go negative,
    and the deficit deterministically computes the wait time. This
    avoids retry loops and naturally staggers concurrent threads.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._tokens = float(capacity)
        self._refill_rate = refill_rate  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        with self._lock:
            self._refill()
            self._tokens -= 1.0
            if self._tokens >= 0.0:
                return
            wait = -self._tokens / self._refill_rate
        time.sleep(wait)


class RateLimiter:
    """Multi-bucket rate limiter keyed by category.

    Each category has its own TokenBucket with independent capacity and refill rate.
    Usage: call acquire(key) before making an HTTP request.

    limits: dict mapping category name to (capacity, refill_rate) tuples.
        capacity: maximum burst size (number of tokens).
        refill_rate: tokens added per second (e.g., 60 req/min = 1.0 token/sec).

    If acquire() is called with an unknown key, no throttling is applied.
    """

    def __init__(self, limits: dict[str, tuple[int, float]]) -> None:
        self._buckets = {key: TokenBucket(cap, rate) for key, (cap, rate) in limits.items()}

    def acquire(self, key: str = "default") -> None:
        bucket = self._buckets.get(key)
        if bucket is not None:
            bucket.acquire()
