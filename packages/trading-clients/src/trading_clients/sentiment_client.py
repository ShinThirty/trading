"""Sentiment client — Playwright-backed scraper for CBOE p/c and AAII.

Both sources require a real-browser context:
  - CBOE pages are Next.js client-rendered; static HTML carries no value.
  - AAII returns 403 Incapsula to non-browser User-Agents.

A single chromium browser is launched at MCP server startup and reused across
scrapes. We use one persistent context configured to look like real Chrome on
Linux (realistic UA, viewport, locale, NY timezone, accept headers) — without
this, AAII's WAF blocks. No stealth plugin needed.

NAAIM exposure used to live here but now lives in NaaimClient (httpx + XLSX);
that gives the latest reading plus full history at no extra cost.

The client is optional: if Playwright fails to start (browser binary missing,
sandbox issue), the MCP server skips it and the regime tool falls back to its
non-sentiment dimensions.

Playwright is an optional dep of trading-clients (the `sentiment` extra).
Importing this module without it raises a clear error so consumers like
option-monitor — which depend on plain `trading-clients` — never hit a
confusing `ModuleNotFoundError: playwright` at import time.
"""

import asyncio
from typing import Any

try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Playwright,
        async_playwright,
    )
except ImportError as e:  # pragma: no cover — exercised only without the extra
    raise ImportError(
        "sentiment_client requires Playwright. Install the optional extra: "
        "pip install 'trading-clients[sentiment]' (or `uv sync --all-packages` "
        "in this workspace, which installs it via trading-mcp)."
    ) from e

from trading_clients.cache import TTLCache
from trading_clients.endpoint import Endpoint, ParamsRequest

REAL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

REAL_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Upgrade-Insecure-Requests": "1",
}

NAV_TIMEOUT_MS = 30_000
HYDRATION_PAUSE_MS = 2000


class SentimentClient:
    _playwright: Playwright | None
    _browser: Browser | None
    _context: BrowserContext | None

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._cache = TTLCache()
        self._started = False

    async def startup(self) -> None:
        """Launch chromium and create the shared realistic-browser context.

        Idempotent: safe to call once at MCP lifespan startup.
        """
        if self._started:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            user_agent=REAL_UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers=REAL_HEADERS,
        )
        self._started = True

    async def close(self) -> None:
        """Shut down browser + Playwright. Called from MCP lifespan teardown."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._started = False

    async def get(self, endpoint: Endpoint, request: ParamsRequest) -> Any:
        """Fetch the endpoint's page through the shared browser context, return the
        decoded response model.

        Mirrors BaseClient.get() so callers can use the same pattern as other
        clients. ParamsRequest is accepted for protocol compatibility but ignored —
        these endpoints are static URLs.
        """
        del request  # static URLs; no params
        if not self._started or self._context is None:
            raise RuntimeError("SentimentClient not started — call startup() first")
        if endpoint.base_url is None:
            raise ValueError(f"Sentiment endpoint {endpoint.path!r} requires base_url")

        url = f"{endpoint.base_url}{endpoint.path}"

        if endpoint.cache_ttl > 0:
            cached = self._cache.get(url, endpoint.cache_ttl)
            if cached is not None:
                return self._decode(endpoint, cached)

        text = await self._fetch(url)

        if endpoint.cache_ttl > 0:
            self._cache.put(url, text)

        return self._decode(endpoint, text)

    async def _fetch(self, url: str) -> str:
        """Open a fresh page, navigate, return the body's visible text after JS
        renders. Retries once on transient navigation errors."""
        assert self._context is not None  # narrowed by startup() check in get()
        ctx = self._context
        last_exc: Exception | None = None
        for attempt in range(2):
            page = await ctx.new_page()
            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
                if resp is None:
                    raise RuntimeError(f"no response from {url}")
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} from {url}")
                # Let any late hydration settle (CBOE/AAII have post-load JS).
                await page.wait_for_timeout(HYDRATION_PAUSE_MS)
                return await page.locator("body").inner_text()
            except Exception as e:
                last_exc = e
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                raise
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
        # Unreachable — second loop iteration always raises or returns
        raise RuntimeError(f"sentiment fetch failed: {last_exc}")

    @staticmethod
    def _decode(endpoint: Endpoint, data: Any) -> Any:
        if endpoint.response_model:
            return endpoint.response_model.from_response(data)
        return data
