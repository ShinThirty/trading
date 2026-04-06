from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import FinnhubConfig
from trading_mcp.response_filters import process

BASE_URL = "https://finnhub.io/api/v1"

CACHE_TTLS: dict[str, int] = {
    "company-news": 300,
    "market-news": 300,
    "economic-calendar": 3600,
    "earnings-calendar": 3600,
    "basic-financials": 3600,
    "eps-estimates": 3600,
    "recommendations": 3600,
    "price-target": 3600,
    "insider-transactions": 3600,
    "peers": 3600,
}


class FinnhubClient:
    def __init__(self, config: FinnhubConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.Client(timeout=15)
        self._cache = TTLCache()

    def _get(
        self, path: str, params: dict[str, str] | None = None, cache_key: str | None = None
    ) -> Any:
        params = dict(params) if params else {}
        params["token"] = self._api_key

        ttl = CACHE_TTLS.get(cache_key or "", 0)
        if ttl > 0 and cache_key:
            full_key = (
                cache_key
                + "&"
                + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "token")
            )
            cached = self._cache.get(full_key, ttl)
            if cached is not None:
                return cached

        resp = self._http.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        result = resp.json()

        if ttl > 0 and cache_key:
            self._cache.put(full_key, result)

        return result

    def get_company_news(self, symbol: str, from_date: str, to_date: str, limit: int = 20) -> Any:
        data = self._get(
            "/company-news",
            {"symbol": symbol, "from": from_date, "to": to_date},
            cache_key="company-news",
        )
        if isinstance(data, list):
            data = data[:limit]
        return process("finnhub:company-news", data)

    def get_market_news(self, category: str = "general", limit: int = 20) -> Any:
        data = self._get("/news", {"category": category}, cache_key="market-news")
        if isinstance(data, list):
            data = data[:limit]
        return process("finnhub:market-news", data)

    def get_economic_calendar(self, from_date: str, to_date: str) -> Any:
        data = self._get(
            "/calendar/economic",
            {"from": from_date, "to": to_date},
            cache_key="economic-calendar",
        )
        events = data.get("economicCalendar", [])
        return process("finnhub:economic-calendar", events)

    def get_earnings_calendar(self, from_date: str, to_date: str, limit: int = 50) -> Any:
        data = self._get(
            "/calendar/earnings",
            {"from": from_date, "to": to_date},
            cache_key="earnings-calendar",
        )
        earnings = data.get("earningsCalendar", [])
        # Filter out micro-caps: drop entries with no analyst coverage
        earnings = [
            e for e in earnings if e.get("epsEstimate") is not None or e.get("revenueEstimate")
        ]
        return process("finnhub:earnings-calendar", earnings[:limit])

    def get_basic_financials(self, symbol: str) -> Any:
        data = self._get(
            "/stock/metric",
            {"symbol": symbol, "metric": "all"},
            cache_key="basic-financials",
        )
        return process("finnhub:basic-financials", data)

    def get_eps_estimates(self, symbol: str) -> Any:
        data = self._get("/stock/eps-estimate", {"symbol": symbol}, cache_key="eps-estimates")
        return process("finnhub:eps-estimates", data)

    def get_recommendation_trends(self, symbol: str) -> Any:
        data = self._get("/stock/recommendation", {"symbol": symbol}, cache_key="recommendations")
        return process("finnhub:recommendations", data)

    def get_price_target(self, symbol: str) -> Any:
        data = self._get("/stock/price-target", {"symbol": symbol}, cache_key="price-target")
        return process("finnhub:price-target", data)

    def get_insider_transactions(self, symbol: str, limit: int = 20) -> Any:
        data = self._get(
            "/stock/insider-transactions", {"symbol": symbol}, cache_key="insider-transactions"
        )
        txns = data.get("data", [])[:limit]
        return process("finnhub:insider-transactions", txns)

    def get_company_peers(self, symbol: str) -> Any:
        data = self._get("/stock/peers", {"symbol": symbol}, cache_key="peers")
        return process("finnhub:peers", data)
