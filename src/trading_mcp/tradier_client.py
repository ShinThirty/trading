from typing import Any

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import TradierConfig
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.response_filters import process

SANDBOX_HOST = "https://sandbox.tradier.com"
PRODUCTION_HOST = "https://api.tradier.com"

CACHE_TTLS: dict[str, int] = {
    "expirations": 3600,
    "strikes": 3600,
    "chain": 30,
    "lookup": 3600,
    "history": 300,
    "search": 3600,
    "clock": 30,
    "timesales": 60,
}


RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (5, 2.0),  # 120 req/min — conservative burst
}


class TradierClient:
    def __init__(self, config: TradierConfig) -> None:
        self._base = SANDBOX_HOST if config.sandbox else PRODUCTION_HOST
        self._account_id = config.account_id
        self._http = httpx.Client(timeout=15)
        self._headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
        }
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _resolve_account_id(self, account_id: str | None) -> str:
        aid = account_id or self._account_id
        if not aid:
            raise RuntimeError(
                "No account_id provided. Either set account_id in ~/.tradingrc [tradier] "
                "or pass it as a parameter. Use get_tradier_profile() to list accounts."
            )
        return aid

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

        self._limiter.acquire()
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

    def get_option_lookup(self, underlying: str) -> Any:
        data = self._get(
            "/v1/markets/options/lookup",
            {"underlying": underlying},
            cache_key="lookup",
        )
        symbols = data.get("symbols", [])
        if isinstance(symbols, list):
            options = symbols[0].get("options", []) if symbols else []
        else:
            options = symbols.get("options", []) if symbols else []
        return process("tradier:option-lookup", options)

    def get_history(
        self,
        symbol: str,
        interval: str = "daily",
        start: str | None = None,
        end: str | None = None,
    ) -> Any:
        params: dict[str, str] = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = self._get("/v1/markets/history", params, cache_key="history")
        history = data.get("history", {})
        days = history.get("day", []) if history else []
        if isinstance(days, dict):
            days = [days]
        return process("tradier:history", days)

    def search_symbols(self, query: str, indexes: bool = False) -> Any:
        params: dict[str, str] = {"q": query, "indexes": str(indexes).lower()}
        data = self._get("/v1/markets/search", params, cache_key="search")
        securities = data.get("securities", {})
        results = securities.get("security", []) if securities else []
        if isinstance(results, dict):
            results = [results]
        return process("tradier:search", results)

    def get_quotes(self, symbols: str, greeks: bool = False) -> Any:
        data = self._get(
            "/v1/markets/quotes",
            {"symbols": symbols, "greeks": str(greeks).lower()},
        )
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        return process("tradier:quotes", quotes)

    def get_timesales(
        self,
        symbol: str,
        interval: str = "5min",
        start: str | None = None,
        end: str | None = None,
    ) -> Any:
        params: dict[str, str] = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = self._get("/v1/markets/timesales", params, cache_key="timesales")
        series = data.get("series", {})
        ticks = series.get("data", []) if series else []
        if isinstance(ticks, dict):
            ticks = [ticks]
        return process("tradier:timesales", ticks)

    def get_clock(self) -> dict:
        """Return raw market clock data (state, description, next change, etc.)."""
        data = self._get("/v1/markets/clock", cache_key="clock")
        return data.get("clock", {})

    # ── HTTP helpers for brokerage endpoints ────────────────────

    def _post(self, path: str, data: dict[str, str] | None = None) -> Any:
        self._limiter.acquire()
        resp = self._http.post(
            f"{self._base}{path}",
            headers=self._headers,
            data=data,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, data: dict[str, str] | None = None) -> Any:
        self._limiter.acquire()
        resp = self._http.put(
            f"{self._base}{path}",
            headers=self._headers,
            data=data,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> Any:
        self._limiter.acquire()
        resp = self._http.delete(
            f"{self._base}{path}",
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Account ─────────────────────────────────────────────────

    def get_user_profile(self) -> Any:
        data = self._get("/v1/user/profile")
        profile = data.get("profile", {})
        account = profile.get("account", [])
        if isinstance(account, dict):
            account = [account]
        return process("tradier:profile", account)

    def get_tradier_balances(self, account_id: str | None = None) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._get(f"/v1/accounts/{aid}/balances")
        return process("tradier:balances", data.get("balances", {}))

    def get_tradier_positions(self, account_id: str | None = None) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._get(f"/v1/accounts/{aid}/positions")
        positions = data.get("positions", {})
        if positions == "null" or not positions:
            return process("tradier:positions", [])
        items = positions.get("position", [])
        if isinstance(items, dict):
            items = [items]
        return process("tradier:positions", items)

    def get_tradier_orders(
        self,
        status: str | None = None,
        page: int | None = None,
        limit: int | None = None,
        account_id: str | None = None,
    ) -> Any:
        aid = self._resolve_account_id(account_id)
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if page:
            params["page"] = str(page)
        if limit:
            params["limit"] = str(limit)
        data = self._get(f"/v1/accounts/{aid}/orders", params)
        orders = data.get("orders", {})
        if orders == "null" or not orders:
            return process("tradier:orders", [])
        items = orders.get("order", [])
        if isinstance(items, dict):
            items = [items]
        return process("tradier:orders", items)

    def get_tradier_order_detail(self, order_id: str, account_id: str | None = None) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._get(f"/v1/accounts/{aid}/orders/{order_id}")
        return process("tradier:order-detail", data.get("order", {}))

    def get_tradier_gainloss(
        self,
        page: int | None = None,
        limit: int | None = None,
        sort_by: str | None = None,
        sort: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        aid = self._resolve_account_id(account_id)
        params: dict[str, str] = {}
        if page:
            params["page"] = str(page)
        if limit:
            params["limit"] = str(limit)
        if sort_by:
            params["sortBy"] = sort_by
        if sort:
            params["sort"] = sort
        data = self._get(f"/v1/accounts/{aid}/gainloss", params)
        gainloss = data.get("gainloss", {})
        if gainloss == "null" or not gainloss:
            return process("tradier:gainloss", [])
        items = gainloss.get("closed_position", [])
        if isinstance(items, dict):
            items = [items]
        return process("tradier:gainloss", items)

    def get_tradier_history(
        self,
        page: int | None = None,
        limit: int | None = None,
        activity_type: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        aid = self._resolve_account_id(account_id)
        params: dict[str, str] = {}
        if page:
            params["page"] = str(page)
        if limit:
            params["limit"] = str(limit)
        if activity_type:
            params["type"] = activity_type
        data = self._get(f"/v1/accounts/{aid}/history", params)
        history = data.get("history", {})
        if history == "null" or not history:
            return process("tradier:account-history", [])
        events = history.get("event", [])
        if isinstance(events, dict):
            events = [events]
        return process("tradier:account-history", events)

    # ── Order Management ────────────────────────────────────────

    def place_tradier_order(
        self, order_params: dict[str, str], account_id: str | None = None
    ) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._post(f"/v1/accounts/{aid}/orders", order_params)
        if "errors" in data:
            return process("tradier:place-order", data["errors"])
        return process("tradier:place-order", data.get("order", data))

    def modify_tradier_order(
        self,
        order_id: str,
        modifications: dict[str, str],
        account_id: str | None = None,
    ) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._put(f"/v1/accounts/{aid}/orders/{order_id}", modifications)
        return process("tradier:modify-order", data.get("order", {}))

    def cancel_tradier_order(self, order_id: str, account_id: str | None = None) -> Any:
        aid = self._resolve_account_id(account_id)
        data = self._delete(f"/v1/accounts/{aid}/orders/{order_id}")
        return process("tradier:cancel-order", data.get("order", {}))
