"""TWSE OpenAPI HTTP transport (no auth, JSON).

The openapi.twse.com.tw platform serves listed-company disclosures as JSON
without authentication or browser challenges. Used here for the monthly
revenue feed (t187ap05_L) that powers TSMC's semi-cycle signal — TSMC's
own IR site now sits behind a Cloudflare challenge that the simple httpx
client can't pass.
"""

import asyncio
import ssl
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://openapi.twse.com.tw"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 1.0),  # 3 burst, refill 1/sec
}

CONCURRENCY = 2


def _build_ssl_context() -> ssl.SSLContext:
    """openapi.twse.com.tw serves a certificate whose chain is missing the
    Subject Key Identifier extension on (likely) the intermediate CA. Python's
    ssl module enables VERIFY_X509_STRICT by default starting in 3.13, which
    rejects the chain even though curl/openssl accept it. We clear that flag
    specifically while keeping the rest of the default validation (CA bundle,
    hostname check, expiry) intact."""
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


class TwseClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=20,
            headers={
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
            verify=_build_ssl_context(),
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache: TTLCache = TTLCache()
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
        cache_key = resolved

        if method == "GET" and endpoint.cache_ttl > 0:
            cached = self._cache.get(cache_key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        resp = await self._http.get(f"{BASE_URL}{resolved}")
        resp.raise_for_status()
        data = resp.json()

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(cache_key, data)

        return data
