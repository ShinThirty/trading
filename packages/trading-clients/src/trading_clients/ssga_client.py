"""SSGA (SPDR) fund-data HTTP transport. No auth — public holdings files.

Unlike the JSON clients, `_request` returns raw **bytes**: the payload is an
XLSX workbook, parsed by openpyxl in `SsgaHoldingsResponse.from_response`. The
Endpoint/BaseClient plumbing is otherwise unchanged, so a holdings fetch reads
the same as any other typed call.

A missing fund ticker returns SSGA's HTML error page with a 200, not a 404, so
the client checks that the body actually looks like a workbook (`PK` zip magic)
before handing it to the parser — otherwise openpyxl raises something opaque
several frames away from the cause.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import ApiError, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.ssga.com"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (4, 1.0),
}

# The panel is fetched concurrently; 3 keeps six ~120KB downloads polite.
CONCURRENCY = 3

_ZIP_MAGIC = b"PK"


class SsgaClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
            headers={
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
                "Accept": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"),
                "Accept-Encoding": "gzip, deflate",
            },
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

        if endpoint.cache_ttl > 0:
            cached = self._cache.get(resolved, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        base = endpoint.base_url or BASE_URL
        resp = await self._http.request(method, f"{base}{resolved}", params=params)
        resp.raise_for_status()
        content = resp.content

        if not content.startswith(_ZIP_MAGIC):
            # SSGA serves its error page with a 200 for unknown fund tickers.
            raise ApiError(
                resp.status_code,
                f"SSGA returned {len(content)} bytes of non-XLSX content for {resolved} "
                "— the fund ticker is probably wrong or the file has moved.",
            )

        if endpoint.cache_ttl > 0:
            self._cache.put(resolved, content)
        return content
