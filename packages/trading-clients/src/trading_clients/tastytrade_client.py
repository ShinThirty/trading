"""TastyTrade API HTTP transport with OAuth2 refresh token authentication."""

import asyncio
import time
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import TastyTradeConfig
from trading_clients.endpoint import _DEFAULT_CONCURRENCY, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.tastyworks.com"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 1.0),
}


class TastyTradeClient(BaseClient):
    def __init__(self, config: TastyTradeConfig) -> None:
        self._client_secret = config.client_secret
        self._refresh_token = config.refresh_token
        self._http = httpx.AsyncClient(timeout=15)
        self._semaphore = asyncio.Semaphore(_DEFAULT_CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

        # Token state
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if expired or missing."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        async with self._token_lock:
            # Double-check after acquiring lock
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            return await self._do_refresh()

    async def _do_refresh(self) -> str:
        """Exchange refresh token for a new access token."""
        resp = await self._http.post(
            f"{BASE_URL}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.monotonic() + data.get("expires_in", 900) - 60
        return self._access_token

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
        """Execute HTTP request with OAuth2 bearer auth, caching, and rate limiting."""
        resolved = path or endpoint.path

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        token = await self._ensure_token()
        base = endpoint.base_url or BASE_URL
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        resp = await self._http.request(
            method, f"{base}{resolved}", params=params, json=body, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
