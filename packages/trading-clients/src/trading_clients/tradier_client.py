"""Tradier API HTTP transport with Bearer token authentication."""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import TradierConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

SANDBOX_HOST = "https://sandbox.tradier.com"
PRODUCTION_HOST = "https://api.tradier.com"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 2.0),  # 120 req/min — conservative burst
}

CONCURRENCY = 5


class TradierClient(BaseClient):
    def __init__(self, config: TradierConfig) -> None:
        self._base = SANDBOX_HOST if config.sandbox else PRODUCTION_HOST
        self._account_id = config.account_id
        self._http = httpx.AsyncClient(timeout=15)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
        }
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def resolve_account_id(self, account_id: str | None = None) -> str:
        """Resolve account_id from param, config default, or raise with instructions."""
        aid = account_id or self._account_id
        if not aid:
            raise RuntimeError(
                "No account_id provided. Either set account_id in ~/.tradingrc [tradier] "
                "or pass it as a parameter. Use get_tradier_profile() to list accounts."
            )
        return aid

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
        """Execute HTTP request with Bearer auth, caching, and rate limiting."""
        resolved = path or endpoint.path

        # Cache check (GET only)
        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        url = f"{self._base}{resolved}"

        if method == "GET":
            resp = await self._http.get(url, headers=self._headers, params=params)
        elif method == "POST":
            resp = await self._http.post(url, headers=self._headers, data=body)
        elif method == "PUT":
            resp = await self._http.put(url, headers=self._headers, data=body)
        elif method == "DELETE":
            resp = await self._http.delete(url, headers=self._headers)
        else:
            raise ValueError(f"Unsupported method: {method}")

        resp.raise_for_status()
        data = resp.json()

        # Cache store (GET only)
        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
