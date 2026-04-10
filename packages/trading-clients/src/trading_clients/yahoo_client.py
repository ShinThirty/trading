"""Yahoo Finance API HTTP transport with cookie/crumb authentication."""

import time
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://query1.finance.yahoo.com"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 0.5),
}

MAX_CRUMB_RETRIES = 3
CRUMB_RETRY_DELAY = 2.0


class YahooClient(BaseClient):
    def __init__(self) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=15,
        )
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)
        self._crumb: str | None = None

    def _ensure_crumb(self) -> None:
        """Fetch cookie + crumb if not already set. Retries on 429."""
        if self._crumb is not None:
            return
        # Step 1: hit fc.yahoo.com to get cookies (404 expected)
        self._http.get(COOKIE_URL)
        # Step 2: get crumb using those cookies, with retry on 429
        for attempt in range(MAX_CRUMB_RETRIES):
            resp = self._http.get(CRUMB_URL)
            if resp.status_code == 429:
                if attempt < MAX_CRUMB_RETRIES - 1:
                    time.sleep(CRUMB_RETRY_DELAY * (attempt + 1))
                    continue
                raise RuntimeError(
                    "Yahoo Finance rate limited (429). Try again in a few minutes."
                )
            resp.raise_for_status()
            self._crumb = resp.text.strip()
            return

    def _cache_key(self, params: dict[str, str] | None) -> str:
        if not params:
            return ""
        return "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "crumb")

    def _do_request(
        self,
        method: str,
        url: str,
        params: dict[str, str],
        body: dict[str, Any] | None,
    ) -> httpx.Response:
        if method == "POST":
            return self._http.post(url, params=params, json=body)
        return self._http.get(url, params=params)

    def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with cookie/crumb auth, caching, and rate limiting."""
        self._ensure_crumb()
        params = dict(params) if params else {}
        assert self._crumb is not None
        params["crumb"] = self._crumb

        url = f"{BASE_URL}{path}"

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        self._limiter.acquire()
        resp = self._do_request(method, url, params, body)

        # Handle crumb expiration — refresh and retry once
        if resp.status_code == 401:
            self._crumb = None
            self._ensure_crumb()
            assert self._crumb is not None
            params["crumb"] = self._crumb
            resp = self._do_request(method, url, params, body)

        resp.raise_for_status()
        data = resp.json()

        # Check for Yahoo Finance API-level errors
        error = data.get("finance", {}).get("error")
        if error:
            raise RuntimeError(f"Yahoo Finance API error: {error.get('description', error)}")

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
