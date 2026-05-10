"""EIA Open Data API HTTP transport with API key authentication.

Mirrors FredClient: API key passed as a query parameter, conservative rate
limit, in-memory TTL cache. EIA's free tier allows ~5000 req/hour which is
generous enough that we can leave the limiter loose.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import EiaConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.eia.gov/v2"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 1.0),  # 300 req/min — well under 5000 req/hour cap
}

CONCURRENCY = 4


class EiaClient(BaseClient):
    def __init__(self, config: EiaConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.AsyncClient(timeout=20)
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

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        base = endpoint.base_url or BASE_URL
        resp = await self._http.get(f"{base}{resolved}", params=params)
        resp.raise_for_status()
        data = resp.json()

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
