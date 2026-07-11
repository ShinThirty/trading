"""SnapTrade brokerage-data API transport with request-signature auth.

SnapTrade exposes read-only brokerage account data (positions, balances, option
holdings) across many brokers — including Fidelity/NetBenefits via Akoya — behind
a signed REST API. This is a thin transport in the house BaseClient style rather
than the official SDK, to keep trading-clients' dependency surface at httpx only
(the same reason there's no Webull SDK).

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

from trading_clients.config import SnapTradeConfig
from trading_clients.endpoint import ApiError, BaseClient, Endpoint

BASE_URL = "https://api.snaptrade.com"
CONCURRENCY = 2


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

    # ── signed transport ─────────────────────────────────────

    async def _signed(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Sign and send one request; return parsed JSON (list or dict)."""
        # clientId first, timestamp last, user params in between — a fixed order so
        # the signed string is byte-identical to what we put on the wire.
        merged: dict[str, str] = {"clientId": self._config.client_id}
        if query:
            merged.update(query)
        merged["timestamp"] = str(int(time.time()))
        query_string = urlencode(merged)

        signature = compute_signature(f"{path}?{query_string}", self._config.consumer_key, body)
        headers = {"Signature": signature, "Accept": "application/json"}

        async with self._semaphore:
            if method == "POST":
                headers["Content-Type"] = "application/json"
                resp = await self._http.post(f"{path}?{query_string}", headers=headers, json=body)
            else:
                resp = await self._http.request(method, f"{path}?{query_string}", headers=headers)

        if not resp.is_success:
            raise ApiError(resp.status_code, f"SnapTrade API {resp.status_code}: {resp.text}")
        if not resp.content:
            return None
        return resp.json()

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """BaseClient hook — delegate to the signed transport."""
        return await self._signed(method, path or endpoint.path, params, body)

    # ── read endpoints ───────────────────────────────────────
    # Brokerages are connected in the SnapTrade dashboard (app.snaptrade.com);
    # this client only reads what's already connected.

    async def list_accounts(self) -> list[dict[str, Any]]:
        """All brokerage accounts connected to this Personal SnapTrade account."""
        return await self._signed("GET", "/accounts")

    async def get_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Stock/ETF/mutual-fund positions for one account."""
        return await self._signed("GET", f"/accounts/{account_id}/positions")

    async def get_option_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Option positions for one account."""
        return await self._signed("GET", f"/accounts/{account_id}/options")
