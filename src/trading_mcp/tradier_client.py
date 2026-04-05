from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import TradierConfig
from trading_mcp.response_filters import process

SANDBOX_HOST = "https://sandbox.tradier.com"
PRODUCTION_HOST = "https://api.tradier.com"

CACHE_TTLS: dict[str, int] = {
    "expirations": 3600,
    "strikes": 3600,
    "chain": 30,
}


class TradierClient:
    def __init__(self, config: TradierConfig) -> None:
        self._base = SANDBOX_HOST if config.sandbox else PRODUCTION_HOST
        self._http = httpx.Client(timeout=15)
        self._headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
        }
        self._cache = TTLCache()

    def _get(
        self, path: str, params: dict[str, str] | None = None, cache_key: str | None = None
    ) -> Any:
        ttl = CACHE_TTLS.get(cache_key or "", 0)
        if ttl > 0 and cache_key:
            sorted_params = sorted((params or {}).items())
            full_key = cache_key + "&" + "&".join(f"{k}={v}" for k, v in sorted_params)
            cached = self._cache.get(full_key, ttl)
            if cached is not None:
                return cached

        resp = self._http.get(
            f"{self._base}{path}",
            headers=self._headers,
            params=params,
        )
        resp.raise_for_status()
        result = resp.json()

        if ttl > 0 and cache_key:
            self._cache.put(full_key, result)

        return result

    def get_option_expirations(self, symbol: str) -> Any:
        data = self._get(
            "/v1/markets/options/expirations",
            {"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
            cache_key="expirations",
        )
        dates = data.get("expirations", {}).get("date", [])
        return process("tradier:expirations", dates)

    def get_option_strikes(self, symbol: str, expiration: str) -> Any:
        data = self._get(
            "/v1/markets/options/strikes",
            {"symbol": symbol, "expiration": expiration},
            cache_key="strikes",
        )
        strikes = data.get("strikes", {}).get("strike", [])
        return process("tradier:strikes", strikes)

    def get_option_chain(self, symbol: str, expiration: str, greeks: bool = True) -> Any:
        data = self._get(
            "/v1/markets/options/chains",
            {
                "symbol": symbol,
                "expiration": expiration,
                "greeks": str(greeks).lower(),
            },
            cache_key="chain",
        )
        options = data.get("options", {}).get("option", [])
        return process("tradier:chain", options)
