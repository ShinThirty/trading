import base64
import hashlib
import hmac
import json
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from trading_mcp.cache import TTLCache
from trading_mcp.config import WebullConfig
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.response_filters import process

API_HOST = "api.webull.com"
QUOTES_HOST = "usquotes-api.webullfintech.com"

# ── Cache TTLs (seconds) per endpoint path ──────────────────
# 0 or absent = no caching.
CACHE_TTLS: dict[str, int] = {
    # Static metadata
    "/account/profile": 3600,
    "/trade/instrument": 3600,
    "/instrument/list": 3600,
    "/trade/calendar": 3600,
    "/app/subscriptions/list": 31536000,  # effectively permanent (1 year)
    # Historical data (latest bar may still be open)
    "/market-data/bars": 300,
    # Account state
    "/account/balance": 60,
    "/account/positions": 60,
    # Orders
    "/trade/orders/list-open": 30,
    "/trade/orders/list-today": 30,
    "/trade/order/detail": 30,
}

# ── Rate limits per endpoint category ────────────────────────
# (capacity, refill_rate_per_second)
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "account": (1, 1.0),  # balance, positions, profile: 2 req/2s — no burst
    "order_read": (1, 1.0),  # open orders, today orders, order detail: 2 req/2s — no burst
    "order_write": (5, 10.0),  # place, replace, cancel: 600 req/60s
    "instruments": (3, 0.33),  # instrument lookups: 10 req/30s
    "market": (10, 5.0),  # quotes, bars: 300 req/60s
}

_RATE_KEY_MAP: dict[str, str] = {
    "/account/profile": "account",
    "/account/balance": "account",
    "/account/positions": "account",
    "/app/subscriptions/list": "account",
    "/trade/orders/list-open": "order_read",
    "/trade/orders/list-today": "order_read",
    "/trade/order/detail": "order_read",
    "/trade/order/place": "order_write",
    "/trade/order/replace": "order_write",
    "/trade/order/cancel": "order_write",
    "/trade/calendar": "instruments",
    "/trade/instrument": "instruments",
    "/instrument/list": "instruments",
    "/market-data/bars": "market",
}


def _rate_key(path: str) -> str:
    return _RATE_KEY_MAP.get(path, "market")


def _iso8601_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nonce() -> str:
    name = socket.gethostname() + str(uuid.uuid1())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def _md5_hex(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest().upper()


def _sign(string_to_sign: str, secret: str) -> str:
    sig = hmac.new(
        (secret + "&").encode(),
        string_to_sign.encode(),
        hashlib.sha1,
    )
    return base64.b64encode(sig.digest()).decode().strip()


def _build_signature(
    host: str,
    uri: str,
    app_key: str,
    app_secret: str,
    query_params: dict[str, str] | None = None,
    body_params: dict[str, Any] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "x-app-key": app_key,
        "x-timestamp": _iso8601_now(),
        "x-signature-version": "1.0",
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-nonce": _nonce(),
    }
    sign_params: dict[str, str] = {k.lower(): v for k, v in headers.items()}
    sign_params["host"] = host

    if query_params:
        for k, v in query_params.items():
            existing = sign_params.get(k)
            sign_params[k] = f"{existing}&{v}" if existing else str(v)

    body_string = None
    if body_params:
        raw = json.dumps(body_params, ensure_ascii=False, separators=(",", ":"))
        body_string = _md5_hex(raw)

    sorted_pairs = sorted(sign_params.items())
    string_to_sign = uri + "&" + "&".join(f"{k}={v}" for k, v in sorted_pairs)
    if body_string:
        string_to_sign += "&" + body_string
    string_to_sign = quote(string_to_sign, safe="")

    headers["x-signature"] = _sign(string_to_sign, app_secret)
    return headers


class WebullClient:
    def __init__(self, config: WebullConfig) -> None:
        self._config = config
        self._http = httpx.Client(timeout=15, http2=True)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _resolve_account_id(self, account_id: str | None) -> str:
        aid = account_id or self._config.account_id
        if not aid:
            raise RuntimeError(
                "No account_id provided. Either set account_id in ~/.tradingrc [webull] "
                "or pass it as a parameter. Use get_app_subscriptions() to list accounts."
            )
        return aid

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

    def _get_raw(
        self,
        host: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """GET without process() — for paginated endpoints that need post-aggregation."""
        self._limiter.acquire(_rate_key(path))
        headers = _build_signature(
            host=host,
            uri=path,
            app_key=self._config.app_key,
            app_secret=self._config.app_secret,
            query_params=params,
        )
        headers["Accept-Encoding"] = "gzip"
        url = f"https://{host}{path}"
        resp = self._http.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get(
        self,
        host: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        ttl = CACHE_TTLS.get(path, 0)
        if ttl > 0:
            key = self._cache_key(path, params)
            cached = self._cache.get(key, ttl)
            if cached is not None:
                return cached

        self._limiter.acquire(_rate_key(path))
        headers = _build_signature(
            host=host,
            uri=path,
            app_key=self._config.app_key,
            app_secret=self._config.app_secret,
            query_params=params,
        )
        headers["Accept-Encoding"] = "gzip"
        url = f"https://{host}{path}"
        resp = self._http.get(url, headers=headers, params=params)
        resp.raise_for_status()
        result = process(path, resp.json())

        if ttl > 0:
            self._cache.put(key, result)

        return result

    def _post(
        self,
        host: str,
        path: str,
        body: dict[str, Any],
        params: dict[str, str] | None = None,
    ) -> Any:
        self._limiter.acquire(_rate_key(path))
        headers = _build_signature(
            host=host,
            uri=path,
            app_key=self._config.app_key,
            app_secret=self._config.app_secret,
            query_params=params,
            body_params=body,
        )
        headers["Accept-Encoding"] = "gzip"
        headers["Content-Type"] = "application/json"
        url = f"https://{host}{path}"
        resp = self._http.post(url, headers=headers, params=params, json=body)
        resp.raise_for_status()
        return process(path, resp.json())

    # ── Account ──────────────────────────────────────────────

    def get_account_profile(self, account_id: str | None = None) -> Any:
        return self._get(
            API_HOST, "/account/profile", {"account_id": self._resolve_account_id(account_id)}
        )

    def get_account_balance(self, currency: str = "USD", account_id: str | None = None) -> Any:
        return self._get(
            API_HOST,
            "/account/balance",
            {"account_id": self._resolve_account_id(account_id), "total_asset_currency": currency},
        )

    def get_account_positions(self, account_id: str | None = None) -> Any:
        aid = self._resolve_account_id(account_id)
        positions: list[dict] = []
        last_id: str | None = None
        while True:
            params: dict[str, str] = {
                "account_id": aid,
                "page_size": "100",
            }
            if last_id:
                params["last_instrument_id"] = last_id
            # Skip process() for pagination — apply after aggregation
            data = self._get_raw(API_HOST, "/account/positions", params)
            holdings = data.get("holdings", [])
            positions.extend(holdings)
            if not data.get("has_next", False):
                break
            if holdings:
                last_id = holdings[-1].get("instrument_id")
            else:
                break
        return process("/account/positions", positions)

    # ── Orders ───────────────────────────────────────────────

    def get_open_orders(
        self,
        page_size: int = 100,
        last_client_order_id: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._resolve_account_id(account_id),
            "page_size": str(page_size),
        }
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/trade/orders/list-open", params)

    def get_today_orders(
        self,
        page_size: int = 100,
        last_client_order_id: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._resolve_account_id(account_id),
            "page_size": str(page_size),
        }
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/trade/orders/list-today", params)

    def get_order_detail(self, client_order_id: str, account_id: str | None = None) -> Any:
        return self._get(
            API_HOST,
            "/trade/order/detail",
            {
                "account_id": self._resolve_account_id(account_id),
                "client_order_id": client_order_id,
            },
        )

    # ── Stock Order Management ───────────────────────────────

    def preview_order(self, new_orders: list[dict[str, Any]], account_id: str | None = None) -> Any:
        return self._post(
            API_HOST,
            "/openapi/account/orders/preview",
            {"new_orders": new_orders},
            params={"account_id": self._resolve_account_id(account_id)},
        )

    def place_order(self, stock_order: dict[str, Any], account_id: str | None = None) -> Any:
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(account_id),
            "stock_order": {k: v for k, v in stock_order.items() if v is not None},
        }
        return self._post(API_HOST, "/trade/order/place", body)

    def replace_order(self, stock_order: dict[str, Any], account_id: str | None = None) -> Any:
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(account_id),
            "stock_order": {k: v for k, v in stock_order.items() if v is not None},
        }
        return self._post(API_HOST, "/trade/order/replace", body)

    def cancel_order(self, client_order_id: str, account_id: str | None = None) -> Any:
        return self._post(
            API_HOST,
            "/trade/order/cancel",
            {
                "account_id": self._resolve_account_id(account_id),
                "client_order_id": client_order_id,
            },
        )

    # ── Option Order Management ──────────────────────────────

    def preview_option(
        self, new_orders: list[dict[str, Any]], account_id: str | None = None
    ) -> Any:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/preview",
            {"new_orders": new_orders},
            params={"account_id": self._resolve_account_id(account_id)},
        )

    def place_option(self, new_orders: list[dict[str, Any]], account_id: str | None = None) -> Any:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/place",
            {"new_orders": new_orders},
            params={"account_id": self._resolve_account_id(account_id)},
        )

    def replace_option(
        self, modify_orders: list[dict[str, Any]], account_id: str | None = None
    ) -> Any:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/replace",
            {"modify_orders": modify_orders},
            params={"account_id": self._resolve_account_id(account_id)},
        )

    def cancel_option(self, client_order_id: str, account_id: str | None = None) -> Any:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/cancel",
            {"client_order_id": client_order_id},
            params={"account_id": self._resolve_account_id(account_id)},
        )

    # ── Trade Info ───────────────────────────────────────────

    def get_trade_calendar(self, market: str, start: str, end: str) -> Any:
        return self._get(
            API_HOST,
            "/trade/calendar",
            {"market": market, "start": start, "end": end},
        )

    def get_trade_instrument_detail(self, instrument_id: str) -> Any:
        return self._get(API_HOST, "/trade/instrument", {"instrument_id": instrument_id})

    def get_app_subscriptions(self, subscription_id: str | None = None) -> Any:
        params: dict[str, str] = {}
        if subscription_id:
            params["subscription_id"] = subscription_id
        return self._get(API_HOST, "/app/subscriptions/list", params)

    # ── Market Data ──────────────────────────────────────────

    def get_instruments(self, symbols: str, category: str = "US_STOCK") -> Any:
        return self._get(
            QUOTES_HOST,
            "/instrument/list",
            {"symbols": symbols, "category": category},
        )

    def get_historical_bars(
        self,
        symbol: str,
        timespan: str,
        count: int = 200,
        category: str = "US_STOCK",
        trading_sessions: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "symbol": symbol,
            "category": category,
            "timespan": timespan,
            "count": str(count),
        }
        if trading_sessions:
            params["trading_sessions"] = trading_sessions
        return self._get(QUOTES_HOST, "/market-data/bars", params)
