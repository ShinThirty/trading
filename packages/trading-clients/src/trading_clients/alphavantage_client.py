"""Alpha Vantage API HTTP transport with API key authentication."""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import AlphaVantageConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.alphavantage.co/query"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 1.0),  # burst up to 5, then 1 req/s
}

CONCURRENCY = 1


class AlphaVantageClient(BaseClient):
    def __init__(self, config: AlphaVantageConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.AsyncClient(timeout=15)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, params: dict[str, str] | None) -> str:
        if not params:
            return ""
        return "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with API key auth, caching, and rate limiting."""
        params = dict(params) if params else {}
        params["apikey"] = self._api_key

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        resp = await self._http.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        # Alpha Vantage returns 200 with error message on rate limit
        if isinstance(data, dict) and ("Note" in data or "Information" in data):
            msg = data.get("Note") or data.get("Information", "")
            raise RuntimeError(f"Alpha Vantage API limit reached: {msg}")

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
