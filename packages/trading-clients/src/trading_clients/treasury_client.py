"""Treasury home.treasury.gov HTTP transport (no auth, identifies via User-Agent).

Used to scrape the Quarterly Refunding Announcement (QRA) Policy Statement,
the most-recent-documents landing page, and the official-remarks archive.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://home.treasury.gov"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 1.0),
}

CONCURRENCY = 2


class TreasuryClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20,
            headers={
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

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
            key = resolved
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
