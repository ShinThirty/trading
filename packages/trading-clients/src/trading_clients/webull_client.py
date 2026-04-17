"""Webull API v2 HTTP transport with HMAC-SHA1 authentication."""

import asyncio
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

from trading_clients.cache import TTLCache
from trading_clients.config import WebullConfig, save_webull_token
from trading_clients.endpoint import ApiError, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

API_HOST = "api.webull.com"

# ── Rate limits per endpoint category ────────────────────────
# (capacity, refill_rate_per_second)
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (10, 5.0),
    "account": (1, 1.0),  # 2 req/2s — no burst
    "order_read": (1, 1.0),  # 2 req/2s — no burst
    "order_write": (5, 10.0),  # 600 req/60s
    "instruments": (1, 1.0),  # 60 req/60s
}

CONCURRENCY = 1


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


class WebullClient(BaseClient):
    def __init__(self, config: WebullConfig) -> None:
        self._config = config
        self._token: str | None = config.token
        self._http = httpx.AsyncClient(timeout=15, http2=True)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def ensure_account_id(self, account_id: str) -> str:
        """Validate account_id. Always required to prevent wrong-account mistakes."""
        if not account_id:
            raise RuntimeError(
                "account_id is required. Use get_app_subscriptions() to list accounts."
            )
        return account_id

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

    async def _create_token(self) -> str:
        """Create a new access token and save it to ~/.tradingrc."""
        body: dict[str, Any] = {
            "account_id": self._config.account_id,
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
        resp = await self._http.post(f"https://{API_HOST}{path}", headers=headers, json=body)
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
        raise ApiError(resp.status_code, f"Webull API {resp.status_code}: {detail}")

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with HMAC auth, caching, rate limiting, and 401 handling."""
        path = path or endpoint.path

        # Cache check (GET only)
        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(path, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        # Rate limit
        await self._limiter.acquire(endpoint.rate_key)

        # Build auth headers
        headers = _build_signature(
            host=API_HOST,
            uri=path,
            app_key=self._config.app_key,
            app_secret=self._config.app_secret,
            query_params=params,
            body_params=body,
            token=self._token,
        )
        headers["Accept-Encoding"] = "gzip"

        url = f"https://{API_HOST}{path}"

        if method == "POST":
            headers["Content-Type"] = "application/json"
            resp = await self._http.post(url, headers=headers, params=params, json=body)
        else:
            resp = await self._http.get(url, headers=headers, params=params)

        self._raise_for_status(resp)
        data = resp.json()

        # Cache store (GET only)
        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
