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
from trading_mcp.config import WebullConfig, save_webull_token
from trading_mcp.rate_limit import RateLimiter
from trading_mcp.table_helpers import process

API_HOST = "api.webull.com"

# ── Cache TTLs (seconds) per endpoint path ──────────────────
# 0 or absent = no caching.
CACHE_TTLS: dict[str, int] = {
    # Static metadata
    "/openapi/instrument/stock/list": 3600,
    "/openapi/account/list": 31536000,  # effectively permanent (1 year)
    # Account state
    "/openapi/assets/balance": 60,
    "/openapi/assets/positions": 60,
    # Orders
    "/openapi/trade/order/open": 30,
    "/openapi/trade/order/history": 30,
    "/openapi/trade/order/detail": 30,
}

# ── Rate limits per endpoint category ────────────────────────
# (capacity, refill_rate_per_second)
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "account": (1, 1.0),  # balance, positions, account list: 2 req/2s — no burst
    "order_read": (1, 1.0),  # open orders, history, detail: 2 req/2s — no burst
    "order_write": (5, 10.0),  # place, replace, cancel: 600 req/60s
    "instruments": (1, 1.0),  # instrument lookups: 60 req/60s
    "market": (10, 5.0),  # quotes, bars, snapshot: 600 req/60s
}

_RATE_KEY_MAP: dict[str, str] = {
    "/openapi/assets/balance": "account",
    "/openapi/assets/positions": "account",
    "/openapi/account/list": "account",
    "/openapi/trade/order/open": "order_read",
    "/openapi/trade/order/history": "order_read",
    "/openapi/trade/order/detail": "order_read",
    "/openapi/trade/order/place": "order_write",
    "/openapi/trade/order/preview": "order_write",
    "/openapi/trade/order/replace": "order_write",
    "/openapi/trade/order/cancel": "order_write",
    "/openapi/instrument/stock/list": "instruments",
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
    token: str | None = None,
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
    # v2 headers — NOT included in signing
    headers["x-version"] = "v2"
    if token:
        headers["x-access-token"] = token
    return headers


class WebullClient:
    def __init__(self, config: WebullConfig) -> None:
        self._config = config
        self._token: str | None = config.token
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

    def _create_token(self) -> str:
        """Create a new access token and save it to ~/.tradingrc."""
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(None),
        }
        path = "/openapi/auth/token/create"
        headers = _build_signature(
            host=API_HOST,
            uri=path,
            app_key=self._config.app_key,
            app_secret=self._config.app_secret,
            body_params=body,
        )
        headers["Content-Type"] = "application/json"
        resp = self._http.post(f"https://{API_HOST}{path}", headers=headers, json=body)
        if not resp.is_success:
            try:
                err = resp.json()
                msg = err.get("message", resp.text)
            except Exception:
                msg = resp.text
            raise RuntimeError(f"Failed to create Webull token: {resp.status_code} — {msg}")
        data = resp.json()
        token = data["token"]
        save_webull_token(token)
        self._token = token
        return token

    def _check_token_error(self, resp: httpx.Response) -> None:
        """On 401, create a new token and raise with verification instructions."""
        if resp.status_code == 401:
            # Extract the actual error before attempting token refresh
            try:
                err = resp.json()
                error_code = err.get("error_code", "")
            except Exception:
                error_code = ""
            # Only refresh token for auth-related 401s
            if error_code in ("", "INVALID_TOKEN", "TOKEN_EXPIRED"):
                self._create_token()
                raise RuntimeError(
                    "Webull token was expired or invalid. A new token has been created and "
                    "saved to ~/.tradingrc. Please verify it in your Webull App "
                    "(Menu > Messages > OpenAPI Notifications), then retry."
                )
            # For other 401s (permission issues), just surface the error
            raise RuntimeError(f"Webull API 401: {error_code} — {err.get('message', '')}")

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Like resp.raise_for_status() but includes Webull error body."""
        if resp.is_success:
            return
        try:
            err = resp.json()
            detail = f"{err.get('error_code', '')} — {err.get('message', resp.text)}"
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Webull API {resp.status_code}: {detail}")

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
            token=self._token,
        )
        headers["Accept-Encoding"] = "gzip"
        url = f"https://{host}{path}"
        resp = self._http.get(url, headers=headers, params=params)
        self._check_token_error(resp)
        self._raise_for_status(resp)
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
            token=self._token,
        )
        headers["Accept-Encoding"] = "gzip"
        url = f"https://{host}{path}"
        resp = self._http.get(url, headers=headers, params=params)
        self._check_token_error(resp)
        self._raise_for_status(resp)
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
            token=self._token,
        )
        headers["Accept-Encoding"] = "gzip"
        headers["Content-Type"] = "application/json"
        url = f"https://{host}{path}"
        resp = self._http.post(url, headers=headers, params=params, json=body)
        self._check_token_error(resp)
        self._raise_for_status(resp)
        return process(path, resp.json())

    # ── Account ──────────────────────────────────────────────

    def get_account_list(self) -> Any:
        return self._get(API_HOST, "/openapi/account/list")

    def get_account_balance(self, account_id: str | None = None) -> Any:
        return self._get(
            API_HOST,
            "/openapi/assets/balance",
            {"account_id": self._resolve_account_id(account_id)},
        )

    def get_account_positions(self, account_id: str | None = None) -> Any:
        return self._get(
            API_HOST,
            "/openapi/assets/positions",
            {"account_id": self._resolve_account_id(account_id)},
        )

    # ── Orders ───────────────────────────────────────────────

    def get_open_orders(
        self,
        page_size: int = 50,
        last_client_order_id: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._resolve_account_id(account_id),
            "page_size": str(page_size),
        }
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/openapi/trade/order/open", params)

    def get_order_history(
        self,
        page_size: int = 50,
        start_date: str | None = None,
        end_date: str | None = None,
        last_client_order_id: str | None = None,
        account_id: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "account_id": self._resolve_account_id(account_id),
            "page_size": str(page_size),
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if last_client_order_id:
            params["last_client_order_id"] = last_client_order_id
        return self._get(API_HOST, "/openapi/trade/order/history", params)

    def get_order_detail(self, client_order_id: str, account_id: str | None = None) -> Any:
        return self._get(
            API_HOST,
            "/openapi/trade/order/detail",
            {
                "account_id": self._resolve_account_id(account_id),
                "client_order_id": client_order_id,
            },
        )

    # ── Order Management (unified for stocks + options) ──────

    def preview_order(self, new_orders: list[dict[str, Any]], account_id: str | None = None) -> Any:
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(account_id),
            "new_orders": [{k: v for k, v in o.items() if v is not None} for o in new_orders],
        }
        return self._post(API_HOST, "/openapi/trade/order/preview", body)

    def place_order(self, new_orders: list[dict[str, Any]], account_id: str | None = None) -> Any:
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(account_id),
            "new_orders": [{k: v for k, v in o.items() if v is not None} for o in new_orders],
        }
        return self._post(API_HOST, "/openapi/trade/order/place", body)

    def replace_order(
        self, modify_orders: list[dict[str, Any]], account_id: str | None = None
    ) -> Any:
        body: dict[str, Any] = {
            "account_id": self._resolve_account_id(account_id),
            "modify_orders": [
                {k: v for k, v in o.items() if v is not None} for o in modify_orders
            ],
        }
        return self._post(API_HOST, "/openapi/trade/order/replace", body)

    def cancel_order(self, client_order_id: str, account_id: str | None = None) -> Any:
        return self._post(
            API_HOST,
            "/openapi/trade/order/cancel",
            {
                "account_id": self._resolve_account_id(account_id),
                "client_order_id": client_order_id,
            },
        )

    # ── Market Data ──────────────────────────────────────────

    def get_instruments(self, symbols: str, category: str = "US_STOCK") -> Any:
        return self._get(
            API_HOST,
            "/openapi/instrument/stock/list",
            {"symbols": symbols, "category": category},
        )

