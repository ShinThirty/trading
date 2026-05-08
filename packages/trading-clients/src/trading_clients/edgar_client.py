"""SEC EDGAR HTTP transport (no auth, identifies via User-Agent).

EDGAR's fair-use policy requires a User-Agent that identifies the requester. The
default below works for low-volume personal use; if you hit blocks, override via
[edgar] user_agent = "Your Name your@email.com" in ~/.tradingrc.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import EdgarConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.endpoints import edgar as e
from trading_clients.rate_limit import RateLimiter

DEFAULT_USER_AGENT = "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)"

# EDGAR's published rate limit is 10 req/sec. We stay well under.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 5.0),  # 5 burst, refill 5/sec
}

CONCURRENCY = 3


class EdgarClient(BaseClient):
    def __init__(self, config: EdgarConfig | None = None) -> None:
        ua = (config.user_agent if config else None) or DEFAULT_USER_AGENT
        self._http = httpx.AsyncClient(
            timeout=20,
            headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)
        self._cik_map: dict[str, int] | None = None
        self._cik_lock = asyncio.Lock()

    def _cache_key(self, base: str, path: str) -> str:
        return f"{base}{path}"

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        resolved = path or endpoint.path
        base = endpoint.base_url or e.WWW_HOST

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(base, resolved)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        resp = await self._http.get(f"{base}{resolved}")
        resp.raise_for_status()
        text = resp.text

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, text)  # type: ignore[possibly-unbound]

        return text

    async def lookup_cik(self, ticker: str) -> int:
        """Resolve ticker to CIK using the cached company_tickers.json map.

        Loads the map on first call (under a lock so concurrent callers share one fetch).
        """
        if self._cik_map is None:
            async with self._cik_lock:
                if self._cik_map is None:
                    resp = await self.get(e.COMPANY_TICKERS, e.EmptyRequest())
                    self._cik_map = resp.by_ticker
        cik = self._cik_map.get(ticker.upper())
        if cik is None:
            raise ValueError(f"Ticker {ticker!r} not found in EDGAR company_tickers.json")
        return cik
