from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import FmpConfig
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.response_filters import process

BASE_URL = "https://financialmodelingprep.com/stable"

CACHE_TTLS: dict[str, int] = {
    "profile": 3600,
    "income": 3600,
    "balance": 3600,
    "cashflow": 3600,
    "metrics": 3600,
    "earnings": 3600,
    "dividend-history": 3600,
}


RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 0.003),  # 250 req/day ≈ 0.003 req/s, burst up to 5
}


class FmpClient:
    def __init__(self, config: FmpConfig) -> None:
        self._api_key = config.api_key
        self._http = httpx.Client(timeout=15)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _get(
        self, path: str, params: dict[str, str] | None = None, cache_key: str | None = None
    ) -> Any:
        params = dict(params) if params else {}
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
        resp = self._http.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        result = resp.json()

        if ttl > 0 and cache_key:
            self._cache.put(full_key, result)

        return result

    def get_company_profile(self, symbol: str) -> Any:
        data = self._get("/profile", {"symbol": symbol}, cache_key="profile")
        profile = data[0] if isinstance(data, list) and data else data
        return process("fmp:profile", profile if isinstance(profile, dict) else {})

    def get_income_statement(self, symbol: str, period: str = "annual", limit: int = 4) -> Any:
        data = self._get(
            "/income-statement",
            {"symbol": symbol, "period": period, "limit": str(limit)},
            cache_key="income",
        )
        return process("fmp:income-statement", data)

    def get_balance_sheet(self, symbol: str, period: str = "annual", limit: int = 4) -> Any:
        data = self._get(
            "/balance-sheet-statement",
            {"symbol": symbol, "period": period, "limit": str(limit)},
            cache_key="balance",
        )
        return process("fmp:balance-sheet", data)

    def get_cash_flow(self, symbol: str, period: str = "annual", limit: int = 4) -> Any:
        data = self._get(
            "/cash-flow-statement",
            {"symbol": symbol, "period": period, "limit": str(limit)},
            cache_key="cashflow",
        )
        return process("fmp:cash-flow", data)

    def get_key_metrics(self, symbol: str, period: str = "annual", limit: int = 4) -> Any:
        data = self._get(
            "/key-metrics",
            {"symbol": symbol, "period": period, "limit": str(limit)},
            cache_key="metrics",
        )
        return process("fmp:key-metrics", data)

    def get_earnings_calendar(self, symbol: str, limit: int = 5) -> Any:
        data = self._get(
            "/earnings",
            {"symbol": symbol, "limit": str(limit)},
            cache_key="earnings",
        )
        return process("fmp:earnings-calendar", data)

    def get_dividend_history(self, symbol: str) -> Any:
        data = self._get(
            "/dividends",
            {"symbol": symbol},
            cache_key="dividend-history",
        )
        return process("fmp:dividend-history", data)
