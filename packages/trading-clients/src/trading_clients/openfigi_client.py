"""OpenFIGI API HTTP transport. No auth — anonymous access is enough.

An API key would raise the search quota from 5/min to 20 per 6s, but the credit
tools make one search per issuer behind a day-long cache, so the free tier is
not the binding constraint. If that changes, add an optional `[openfigi] api_key`
and send it as `X-OPENFIGI-APIKEY`.

Caches POST responses, unlike the JSON-over-GET clients: OpenFIGI's only useful
verb is POST, and a search for an issuer's bond universe is a pure read.
"""

import asyncio
import json
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import ApiError, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.openfigi.com"

# Anonymous quota is 5 search requests per minute. The limiter is set at the
# quota rather than under it because the day-long endpoint cache means we
# rarely queue more than one call per session.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 60.0),
}

CONCURRENCY = 2


class OpenFigiClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
            },
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    @staticmethod
    def _cache_key(path: str, body: dict[str, Any] | None) -> str:
        return f"{path}|{json.dumps(body or {}, sort_keys=True)}"

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        resolved = path or endpoint.path
        key = self._cache_key(resolved, body)

        if endpoint.cache_ttl > 0:
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        base = endpoint.base_url or BASE_URL
        resp = await self._http.request(method, f"{base}{resolved}", params=params, json=body)
        if resp.status_code == 429:
            raise ApiError(
                429,
                "OpenFIGI rate limit hit (5 searches/minute anonymous). "
                "Retry in a minute, or add an API key.",
            )
        resp.raise_for_status()
        data = resp.json()

        if endpoint.cache_ttl > 0:
            self._cache.put(key, data)
        return data
