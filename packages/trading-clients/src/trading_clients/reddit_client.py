"""Reddit JSON API HTTP transport.

Reddit blocks the anonymous ``.json`` API (403 from its Fastly edge) regardless
of User-Agent or TLS fingerprint. The block is bypassed by sending a single
valid ``loid`` cookie (Reddit's logged-out id) — a Fernet-signed token that
can't be forged and is only minted by JavaScript on a real page load. So we
mint one through the shared Playwright Chromium once, cache it, and ride it on
fast plain-httpx ``.json`` calls. On a 403 (loid expired/revoked) we re-mint
once and retry. See reference_reddit_loid_bypass memory for the full diagnosis.

Without a PlaywrightHost (browser binary missing, sandbox issue) the client
still issues requests but cannot mint a loid, so Reddit returns 403 — the same
degraded state as before this fix. The MCP server keeps running regardless.
"""

import asyncio
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoint import BaseClient, Endpoint
from trading_clients.playwright_host import PlaywrightHost
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.reddit.com"

# Realistic Chrome-on-Linux UA, used for BOTH the loid-minting browser context
# and the httpx fetches so the session looks consistent.
REAL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (2, 0.15),  # ~9 req/min — stay under unauthenticated 10/min limit
}

CONCURRENCY = 1

# How long to wait for JS to mint the loid cookie after page load.
_MINT_NAV_TIMEOUT_MS = 30_000
_MINT_POLL_TRIES = 20
_MINT_POLL_INTERVAL_MS = 500


class RedditClient(BaseClient):
    def __init__(self, host: PlaywrightHost | None = None) -> None:
        self._http = httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": REAL_UA},
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(CONCURRENCY)
        self._cache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)
        self._host = host
        self._loid: str | None = None
        self._loid_lock = asyncio.Lock()

    def _cache_key(self, path: str, params: dict[str, str] | None) -> str:
        parts = [path]
        if params:
            parts.extend(f"{k}={v}" for k, v in sorted(params.items()))
        return "&".join(parts)

    async def _mint_loid(self) -> str | None:
        """Load reddit.com in a fresh browser context and read the loid cookie
        that its JS mints. Returns None if no host or anything goes wrong —
        callers degrade to an unauthenticated (403-prone) request."""
        if self._host is None:
            return None
        context = None
        try:
            context = await self._host.new_context(user_agent=REAL_UA, locale="en-US")
            page = await context.new_page()
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=_MINT_NAV_TIMEOUT_MS)
            for _ in range(_MINT_POLL_TRIES):
                for cookie in await context.cookies():
                    if cookie["name"] == "loid" and cookie["value"]:
                        return str(cookie["value"])
                await page.wait_for_timeout(_MINT_POLL_INTERVAL_MS)
            return None
        except Exception:
            return None
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass

    async def _ensure_loid(self) -> str | None:
        """Return the cached loid, minting one on first use. Single-flight: only
        one context is spawned even under concurrent first requests."""
        if self._loid:
            return self._loid
        async with self._loid_lock:
            if self._loid:
                return self._loid
            self._loid = await self._mint_loid()
            return self._loid

    async def _refresh_loid(self, stale: str | None) -> str | None:
        """Re-mint after a 403. Single-flight against the stale value so a burst
        of 403s triggers only one re-mint."""
        async with self._loid_lock:
            if self._loid != stale:
                return self._loid  # another coroutine already refreshed
            self._loid = await self._mint_loid()
            return self._loid

    async def _get_json(self, url: str, params: dict[str, str] | None) -> Any:
        """GET the .json endpoint with the loid cookie; on 403 re-mint once and
        retry."""
        loid = await self._ensure_loid()
        resp = await self._http.get(url, params=params, cookies={"loid": loid} if loid else None)
        if resp.status_code == 403 and self._host is not None:
            loid = await self._refresh_loid(loid)
            resp = await self._http.get(
                url, params=params, cookies={"loid": loid} if loid else None
            )
        resp.raise_for_status()
        return resp.json()

    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        resolved = path or endpoint.path

        if method == "GET" and endpoint.cache_ttl > 0:
            key = self._cache_key(resolved, params)
            cached = self._cache.get(key, endpoint.cache_ttl)
            if cached is not None:
                return cached

        await self._limiter.acquire()
        data = await self._get_json(f"{BASE_URL}{resolved}", params)

        if method == "GET" and endpoint.cache_ttl > 0:
            self._cache.put(key, data)  # type: ignore[possibly-unbound]

        return data
