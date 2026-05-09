"""CFTC publicreporting.cftc.gov HTTP transport (Socrata JSON, no auth).

Anonymous access works for our query volume; an app token bumps the rate
ceiling but isn't currently configured. Polite User-Agent only.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://publicreporting.cftc.gov"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 1.0),
}

CONCURRENCY = 3


class CftcClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20,
            headers={
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        resolved = path or endpoint.path

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
