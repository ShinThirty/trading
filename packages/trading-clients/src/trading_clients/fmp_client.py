"""FMP API HTTP transport with API key authentication."""

from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import FmpConfig
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://financialmodelingprep.com/stable"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 1.0),  # burst up to 5, then 1 req/s
}


class FmpClient(BaseClient):
    def __init__(self, config: FmpConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.Client(timeout=15)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")
        return "&".join(parts)

    def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with API key auth, caching, and rate limiting."""
        resolved = path or endpoint.path
        params = dict(params) if params else {}
        params["apikey"] = self._api_key

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        self._limiter.acquire()
        resp = self._http.get(f"{BASE_URL}{resolved}", params=params)
        resp.raise_for_status()
        data = resp.json()

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
