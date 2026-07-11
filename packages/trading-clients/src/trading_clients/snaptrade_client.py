"""SnapTrade brokerage-data API transport with request-signature auth.

SnapTrade exposes read-only brokerage account data (positions, balances, option
holdings) across many brokers — including Fidelity/NetBenefits via Akoya — behind
a signed REST API. This is a thin transport in the house BaseClient style rather
than the official SDK, to keep trading-clients' dependency surface at httpx only
(the same reason there's no Webull SDK). Endpoints + typed request/response
models live in endpoints/snaptrade.py; callers use client.get(ENDPOINT, request).

This uses **Personal API key** authentication: the key identifies the account
owner, so requests carry only `clientId` + `timestamp` — no `userId`/`userSecret`,
and registerUser (the Commercial user-management endpoint) is not used. See
https://docs.snaptrade.com/docs/authentication.

Auth (signature mirrors the official SDK's request_after_hook exactly):
  - every request carries `clientId` + `timestamp` (unix seconds) query params.
  - Signature header = base64(HMAC_SHA256(consumer_key,
        json.dumps({"content": body_or_None, "path": <path>, "query": <query>},
                   separators=(",",":"), sort_keys=True)))
    where <path> is the request path (e.g. "/accounts") and <query> is the exact
    query string sent. We build the query string once and use the identical bytes
    for both signing and the wire, so they never diverge.

Base URL is https://api.snaptrade.com with NO /api/v1 prefix — the official
Python SDK signs the bare path.value and posts to host+path, so the signed path
must equal the wire path exactly (a /api/v1 in the URL but not the signature is a
401 "Unable to verify signature").
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import SnapTradeConfig
from trading_clients.endpoint import ApiError, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.snaptrade.com"
CONCURRENCY = 2

# SnapTrade allows ~250 req/min per clientId; stay well under with a burst cap.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (4, 2.0),  # 4 tokens / 2s ≈ 120 req/min
}


def compute_signature(path_with_query: str, consumer_key: str, body: Any = None) -> str:
    """Compute the SnapTrade `Signature` header for a signed request.

    path_with_query is "<path>?<query>" where path is below /api/v1. body is the
    JSON request body (POST) or None (GET / empty body).
    """
    subpath, _, query = path_with_query.partition("?")
    sig_object = {
        "content": None if body is None or body == {} else body,
        "path": subpath,
        "query": query,
    }
    sig_content = json.dumps(sig_object, separators=(",", ":"), sort_keys=True)
    digest = hmac.new(consumer_key.encode(), sig_content.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class SnapTradeClient(BaseClient):
    def __init__(self, config: SnapTradeConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(timeout=30, http2=True, base_url=BASE_URL)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        """Cache key over the resolved path + request params only — never the
        per-request clientId/timestamp added at sign time (those always change)."""
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Sign and send one request; return parsed JSON (list or dict / None).

        clientId leads and timestamp trails the query so the signed string is
        byte-identical to the wire query. The BaseClient get/post wrapper already
        holds the concurrency semaphore, so this hook doesn't re-acquire it.
        """
        resolved = path or endpoint.path

        # Cache check (GET only) — keyed before auth params are added.
        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire(endpoint.rate_key)

        merged: dict[str, str] = {"clientId": self._config.client_id}
        if params:
            merged.update(params)
        merged["timestamp"] = str(int(time.time()))
        url = f"{resolved}?{urlencode(merged)}"

        signature = compute_signature(url, self._config.consumer_key, body)
        headers = {"Signature": signature, "Accept": "application/json"}

        if method == "POST":
            headers["Content-Type"] = "application/json"
            resp = await self._http.post(url, headers=headers, json=body)
        else:
            resp = await self._http.request(method, url, headers=headers)

        if not resp.is_success:
            raise ApiError(resp.status_code, f"SnapTrade API {resp.status_code}: {resp.text}")
        data = resp.json() if resp.content else None

        # Cache store (GET only).
        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
