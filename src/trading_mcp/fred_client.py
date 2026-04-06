from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import FredConfig
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.response_filters import process

BASE_URL = "https://api.stlouisfed.org/fred"

CACHE_TTLS: dict[str, int] = {
    "observations": 3600,
    "series-info": 3600,
    "releases": 3600,
    "search": 3600,
}


RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 2.0),  # 120 req/min — conservative burst
}


class FredClient:
    def __init__(self, config: FredConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.Client(timeout=15)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _get(
        self, path: str, params: dict[str, str] | None = None, cache_key: str | None = None
    ) -> Any:
        params = dict(params) if params else {}
        params["api_key"] = self._api_key
        params["file_type"] = "json"

        ttl = CACHE_TTLS.get(cache_key or "", 0)
        if ttl > 0 and cache_key:
            full_key = (
                cache_key
                + "&"
                + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "api_key")
            )
            cached = self._cache.get(full_key, ttl)
            if cached is not None:
                return cached

        self._limiter.acquire()
        resp = self._http.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        result = resp.json()

        if ttl > 0 and cache_key:
            self._cache.put(full_key, result)

        return result

    def get_series_observations(
        self,
        series_id: str,
        limit: int = 12,
        sort_order: str = "desc",
    ) -> Any:
        data = self._get(
            "/series/observations",
            {
                "series_id": series_id,
                "limit": str(limit),
                "sort_order": sort_order,
            },
            cache_key="observations",
        )
        observations = data.get("observations", [])
        return process("fred:observations", observations)

    def get_series_info(self, series_id: str) -> Any:
        data = self._get("/series", {"series_id": series_id}, cache_key="series-info")
        seriess = data.get("seriess", [])
        info = seriess[0] if seriess else {}
        return process("fred:series-info", info)

    def get_upcoming_releases(self, limit: int = 20) -> Any:
        data = self._get(
            "/releases/dates",
            {
                "limit": str(limit),
                "include_release_dates_with_no_data": "true",
                "sort_order": "asc",
            },
            cache_key="releases",
        )
        releases = data.get("release_dates", [])
        return process("fred:releases", releases)

    def search_series(self, query: str, limit: int = 10) -> Any:
        data = self._get(
            "/series/search",
            {"search_text": query, "limit": str(limit)},
            cache_key="search",
        )
        series = data.get("seriess", [])
        return process("fred:search", series)
