from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import AlphaVantageConfig
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.response_filters import process

BASE_URL = "https://www.alphavantage.co/query"

CACHE_TTLS: dict[str, int] = {
    "sentiment": 3600,
    "movers": 900,
}


RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 1.0),  # burst up to 5, then 1 req/s to prevent rapid-fire
}


class AlphaVantageClient:
    def __init__(self, config: AlphaVantageConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.Client(timeout=15)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _get(self, params: dict[str, str], cache_key: str | None = None) -> Any:
        params["apikey"] = self._api_key

        ttl = CACHE_TTLS.get(cache_key or "", 0)
        if ttl > 0 and cache_key:
            full_key = (
                cache_key
                + "&"
                + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")
            )
            cached = self._cache.get(full_key, ttl)
            if cached is not None:
                return cached

        self._limiter.acquire()
        resp = self._http.get(BASE_URL, params=params)
        resp.raise_for_status()
        result = resp.json()

        # Alpha Vantage returns 200 with error message on rate limit (25/day free tier)
        if isinstance(result, dict) and ("Note" in result or "Information" in result):
            msg = result.get("Note") or result.get("Information", "")
            raise RuntimeError(f"Alpha Vantage API limit reached: {msg}")

        if ttl > 0 and cache_key:
            self._cache.put(full_key, result)

        return result

    def get_news_sentiment(
        self,
        tickers: str | None = None,
        topics: str | None = None,
        sort: str = "LATEST",
        limit: int = 10,
    ) -> Any:
        params: dict[str, str] = {
            "function": "NEWS_SENTIMENT",
            "sort": sort,
            "limit": str(limit),
        }
        if tickers:
            params["tickers"] = tickers
        if topics:
            params["topics"] = topics
        data = self._get(params, cache_key="sentiment")
        feed = data.get("feed", [])
        return process("alphavantage:sentiment", feed)

    def get_top_gainers_losers(self) -> Any:
        data = self._get({"function": "TOP_GAINERS_LOSERS"}, cache_key="movers")
        return process("alphavantage:movers", data)
