import time
from typing import Any


class TTLCache:
    """Simple in-memory cache with per-key TTL expiration."""

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
