import threading
import time
from typing import Any


class TTLCache:
    """In-memory cache with per-key TTL expiration.

    Safe in async contexts without locks: all operations are synchronous dict
    mutations with no await points, so no coroutine can interleave mid-operation.

    NOT thread-safe — use ThreadSafeTTLCache for multi-thread access.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: int) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def invalidate(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._store.clear()
        else:
            for k in [k for k in self._store if k.startswith(prefix)]:
                del self._store[k]


class ThreadSafeTTLCache(TTLCache):
    """TTLCache with a lock for safe access from multiple threads (e.g. asyncio.to_thread)."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def get(self, key: str, ttl: int) -> Any | None:
        with self._lock:
            return super().get(key, ttl)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            super().put(key, value)

    def invalidate(self, prefix: str | None = None) -> None:
        with self._lock:
            super().invalidate(prefix)
