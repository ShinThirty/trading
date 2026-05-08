"""Motley Fool HTTP transport (no auth, returns text).

Used to scrape earnings call transcripts. fool.com's robots.txt is broadly restrictive,
so keep request volume low and respect their bandwidth.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.fool.com"

# Conservative — we only fetch ~2 pages per analysis.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (2, 0.5),  # 2 burst, refill 0.5/sec ≈ 30 req/min
}

CONCURRENCY = 1


class FoolClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; trading-mcp/0.1)"},
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, path: str) -> str:
        return path

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
            key = self._cache_key(resolved)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        resp = await self._http.get(f"{BASE_URL}{resolved}")
        resp.raise_for_status()
        text = resp.text

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, text)  # type: ignore[possibly-unbound]

        return text
