"""FINRA Query API HTTP transport with OAuth2 client-credentials auth.

Three things about this API cost real time to discover, so they are enforced
here rather than left to callers:

1. **The default response is CSV.** Without an explicit
   `Accept: application/json` the body comes back as quoted CSV text and every
   JSON parse fails at column 18.
2. **204 means "no data", not "error".** Weekends, holidays, and dates before a
   dataset's history all return an empty 204. Decoded as an empty list.
3. **Entitlements are baked into the token at mint time.** Accepting a new data
   agreement in the FINRA portal does nothing for a token already in hand, so
   `reset_token()` exists to force a re-mint without restarting the process.

Tokens live ~12h; we refresh a minute early. Auth is HTTP Basic over the
client-id/secret pair against a *different* host (`ews.fip.finra.org`) than the
data API (`api.finra.org`).
"""

import asyncio
import base64
import json
import time
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.config import FinraConfig
from trading_clients.endpoint import ApiError, BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://api.finra.org"
TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token"

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (4, 1.0),
}

CONCURRENCY = 3

# Tokens come back with expires_in ~43200 (12h); refresh a minute early.
_TOKEN_SKEW_SECONDS = 60


class FinraClient(BaseClient):
    def __init__(self, config: FinraConfig) -> None:
        self._basic = base64.b64encode(
            f"{config.api_client_id.strip()}:{config.api_secret.strip()}".encode()
        ).decode()
        self._http = httpx.AsyncClient(timeout=60)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    def reset_token(self) -> None:
        """Drop the cached token so the next call mints a fresh one.

        Needed after accepting a data agreement in the FINRA portal: the
        entitlement set is fixed when the token is issued, so an in-flight token
        keeps 404ing on newly-granted datasets until it expires on its own.
        """
        self._access_token = None
        self._token_expires_at = 0.0

    async def _ensure_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            return await self._do_refresh()

    async def _do_refresh(self) -> str:
        resp = await self._http.post(
            TOKEN_URL,
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {self._basic}"},
        )
        if resp.status_code in (400, 401, 403):
            raise ApiError(
                resp.status_code,
                "FINRA rejected the client credentials — check [finra] api_client_id "
                "and api_secret in ~/.tradingrc.",
            )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        # FINRA returns expires_in as a *string* ("43199"), unlike every other
        # OAuth provider here — coerce before doing arithmetic on it.
        try:
            ttl = float(data.get("expires_in", 43200))
        except (TypeError, ValueError):
            ttl = 43200.0
        self._token_expires_at = time.monotonic() + ttl - _TOKEN_SKEW_SECONDS
        return self._access_token

    @staticmethod
    def _cache_key(path: str, body: dict[str, Any] | None) -> str:
        return f"{path}|{json.dumps(body or {}, sort_keys=True)}"

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        resolved = path or endpoint.path
        key = self._cache_key(resolved, body)

        if endpoint.cache_ttl > 0:
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        token = await self._ensure_token()
        base = endpoint.base_url or BASE_URL
        resp = await self._http.request(
            method,
            f"{base}{resolved}",
            params=params,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                # Without this the API answers in CSV.
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code == 204:
            # No rows for this partition — a weekend, a holiday, or a date
            # outside the dataset's history. Cache it: it won't fill in later.
            data: Any = []
        elif resp.status_code == 404:
            raise ApiError(
                404,
                f"FINRA dataset not found or not entitled: {resolved}. Corporate and "
                "agency datasets 404 (not 403) until the Fixed Income Data user "
                "agreement is accepted at developer.finra.org, and the token must be "
                "minted after accepting.",
            )
        elif resp.status_code == 403:
            raise ApiError(
                403,
                f"FINRA dataset {resolved} requires a paid Firm/Org tier.",
            )
        else:
            resp.raise_for_status()
            data = resp.json() if resp.content else []

        if endpoint.cache_ttl > 0:
            self._cache.put(key, data)
        return data
