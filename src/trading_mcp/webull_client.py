import base64
import hashlib
import hmac
import json
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from trading_mcp.config import WebullConfig
from trading_mcp.response_filters import process

API_HOST = "api.webull.com"
QUOTES_HOST = "usquotes-api.webullfintech.com"

# ── Cache TTLs (seconds) per endpoint path ──────────────────
# 0 or absent = no caching.
CACHE_TTLS: dict[str, int] = {
    # Static metadata
    "/account/profile": 3600,
    "/trade/instrument": 3600,
    "/trade/security": 3600,
    "/instrument/list": 3600,
    "/trade/calendar": 3600,
    "/trade/instrument/tradable/list": 3600,
    "/app/subscriptions/list": 3600,
    "/instrument/corp-action": 3600,
    # Historical data (latest bar may still be open)
    "/market-data/bars": 300,
    "/market-data/eod-bars": 3600,
    # Account state
    "/account/balance": 60,
    "/account/positions": 60,
    "/account/position/details": 60,
    # Orders
    "/trade/orders/list-open": 30,
    "/trade/orders/list-today": 30,
    "/trade/order/detail": 30,
    "/openapi/account/orders/history": 30,
}


class _TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: int) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def invalidate(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._store.clear()
        else:
            for k in [k for k in self._store if k.startswith(prefix)]:
                del self._store[k]


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
        "x-api-key": app_key,
        "x-api-timestamp": _iso8601_now(),
        "x-api-sign-version": "1.0",
        "x-api-sign-algorithm": "HMAC-SHA1",
        "x-api-nonce": _nonce(),
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

    headers["x-api-signature"] = _sign(string_to_sign, app_secret)
    return headers


class WebullClient:
    def __init__(self, config: WebullConfig) -> None:
        self._config = config
        self._http = httpx.Client(timeout=15)
        self._cache = _TTLCache()

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

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

    def get_account_profile(self) -> dict:
        return self._get(API_HOST, "/account/profile", {"account_id": self._config.account_id})

    def get_account_balance(self, currency: str = "USD") -> dict:
        return self._get(
            API_HOST,
            "/account/balance",
            {"account_id": self._config.account_id, "total_asset_currency": currency},
        )

    def get_account_positions(self) -> list[dict]:
        positions: list[dict] = []
        last_id: str | None = None
        while True:
            params: dict[str, str] = {
                "account_id": self._config.account_id,
                "page_size": "100",
            }
            if last_id:
                params["last_instrument_id"] = last_id
            data = self._get(API_HOST, "/account/positions", params)
            holdings = data.get("positions", [])
            positions.extend(holdings)
            if not data.get("has_next", False):
                break
            if holdings:
                last_id = holdings[-1].get("instrument_id")
            else:
                break
        return positions

    def get_account_position_details(
        self, instrument_id: str, size: int = 20, last_instrument_id: str | None = None
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._config.account_id,
            "instrument_id": instrument_id,
            "size": str(size),
        }
        if last_instrument_id:
            params["last_instrument_id"] = last_instrument_id
        return self._get(API_HOST, "/account/position/details", params)

    # ── Orders ───────────────────────────────────────────────

    def get_open_orders(self, page_size: int = 100, last_client_order_id: str | None = None) -> Any:
        params: dict[str, str] = {
            "account_id": self._config.account_id,
            "page_size": str(page_size),
        }
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/trade/orders/list-open", params)

    def get_today_orders(
        self, page_size: int = 100, last_client_order_id: str | None = None
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._config.account_id,
            "page_size": str(page_size),
        }
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/trade/orders/list-today", params)

    def get_order_detail(self, client_order_id: str) -> dict:
        return self._get(
            API_HOST,
            "/trade/order/detail",
            {"account_id": self._config.account_id, "client_order_id": client_order_id},
        )

    def get_order_history(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 100,
        last_client_order_id: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._config.account_id,
            "page_size": str(page_size),
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/openapi/account/orders/history", params)

    # ── Stock Order Management ───────────────────────────────

    def preview_order(self, new_orders: list[dict[str, Any]]) -> dict:
        return self._post(
            API_HOST,
            "/openapi/account/orders/preview",
            {"new_orders": new_orders},
            params={"account_id": self._config.account_id},
        )

    def place_order(self, stock_order: dict[str, Any]) -> dict:
        body: dict[str, Any] = {
            "account_id": self._config.account_id,
            "stock_order": {k: v for k, v in stock_order.items() if v is not None},
        }
        return self._post(API_HOST, "/trade/order/place", body)

    def replace_order(self, stock_order: dict[str, Any]) -> dict:
        body: dict[str, Any] = {
            "account_id": self._config.account_id,
            "stock_order": {k: v for k, v in stock_order.items() if v is not None},
        }
        return self._post(API_HOST, "/trade/order/replace", body)

    def cancel_order(self, client_order_id: str) -> dict:
        return self._post(
            API_HOST,
            "/trade/order/cancel",
            {"account_id": self._config.account_id, "client_order_id": client_order_id},
        )

    # ── Option Order Management ──────────────────────────────

    def preview_option(self, new_orders: list[dict[str, Any]]) -> dict:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/preview",
            {"new_orders": new_orders},
            params={"account_id": self._config.account_id},
        )

    def place_option(self, new_orders: list[dict[str, Any]]) -> dict:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/place",
            {"new_orders": new_orders},
            params={"account_id": self._config.account_id},
        )

    def replace_option(self, modify_orders: list[dict[str, Any]]) -> dict:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/replace",
            {"modify_orders": modify_orders},
            params={"account_id": self._config.account_id},
        )

    def cancel_option(self, client_order_id: str) -> dict:
        return self._post(
            API_HOST,
            "/openapi/account/orders/option/cancel",
            {"client_order_id": client_order_id},
            params={"account_id": self._config.account_id},
        )

    # ── Trade Info ───────────────────────────────────────────

    def get_trade_calendar(self, market: str, start: str, end: str) -> Any:
        return self._get(
            API_HOST,
            "/trade/calendar",
            {"market": market, "start": start, "end": end},
        )

    def get_trade_instrument_detail(self, instrument_id: str) -> dict:
        return self._get(API_HOST, "/trade/instrument", {"instrument_id": instrument_id})

    def get_security_detail(
        self,
        symbol: str,
        market: str = "US",
        instrument_super_type: str | None = None,
        instrument_type: str | None = None,
        strike_price: str | None = None,
        init_exp_date: str | None = None,
    ) -> dict:
        params: dict[str, str] = {
            "account_id": self._config.account_id,
            "symbol": symbol,
            "market": market,
        }
        if instrument_super_type:
            params["instrument_super_type"] = instrument_super_type
        if instrument_type:
            params["instrument_type"] = instrument_type
        if strike_price:
            params["strike_price"] = strike_price
        if init_exp_date:
            params["init_exp_date"] = init_exp_date
        return self._get(API_HOST, "/trade/security", params)

    def get_tradeable_instruments(
        self, page_size: int = 100, last_security_id: str | None = None
    ) -> Any:
        params: dict[str, str] = {"page_size": str(page_size)}
        if last_security_id:
            params["last_security_id"] = last_security_id
        return self._get(API_HOST, "/trade/instrument/tradable/list", params)

    def get_app_subscriptions(self, subscription_id: str | None = None) -> Any:
        params: dict[str, str] = {}
        if subscription_id:
            params["subscription_id"] = subscription_id
        return self._get(API_HOST, "/app/subscriptions/list", params)

    # ── Market Data ──────────────────────────────────────────

    def get_quote(self, symbols: str, category: str = "US_STOCK") -> list[dict]:
        return self._get(
            QUOTES_HOST,
            "/market-data/snapshot",
            {"symbols": symbols, "category": category},
        )

    def get_instruments(self, symbols: str, category: str = "US_STOCK") -> list[dict]:
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

    def get_batch_historical_bars(
        self,
        symbols: str,
        timespan: str,
        count: int = 200,
        category: str = "US_STOCK",
        trading_sessions: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "symbols": symbols,
            "category": category,
            "timespan": timespan,
            "count": str(count),
        }
        if trading_sessions:
            body["trading_sessions"] = trading_sessions
        return self._post(QUOTES_HOST, "/market-data/batch-bars", body)

    def get_eod_bars(self, instrument_ids: str, date: str, count: int = 1) -> Any:
        return self._get(
            QUOTES_HOST,
            "/market-data/eod-bars",
            {"instrument_ids": instrument_ids, "date": date, "count": str(count)},
        )

    def get_corp_actions(
        self,
        instrument_ids: str,
        event_types: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page_number: int = 1,
        page_size: int = 50,
    ) -> Any:
        params: dict[str, str] = {
            "instrument_ids": instrument_ids,
            "page_number": str(page_number),
            "page_size": str(page_size),
        }
        if event_types:
            params["event_types"] = event_types
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._get(QUOTES_HOST, "/instrument/corp-action", params)
