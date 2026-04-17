"""FRED API HTTP transport with API key authentication."""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import FredConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.stlouisfed.org/fred"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 2.0),  # 120 req/min — conservative burst
}

CONCURRENCY = 3


class FredClient(BaseClient):
    def __init__(self, config: FredConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.AsyncClient(timeout=15)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()) if k != "api_key")
        return "&".join(parts)

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with API key auth, caching, and rate limiting."""
        resolved = path or endpoint.path
        params = dict(params) if params else {}
        params["api_key"] = self._api_key
        params["file_type"] = "json"

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        resp = await self._http.get(f"{BASE_URL}{resolved}", params=params)
        resp.raise_for_status()
        data = resp.json()

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
