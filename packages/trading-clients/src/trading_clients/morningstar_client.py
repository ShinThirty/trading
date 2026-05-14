"""Morningstar client — Playwright-backed scraper for earnings call transcripts.

Why Playwright (not httpx):
  - The transcript page (kessler-prod.reta52d8.eas.morningstar.com) is gated
    by an AWS WAF JavaScript challenge. Scripted user-agents get a holding
    HTML page that auto-reloads to the real page only after the challenge JS
    runs successfully.
  - The transcript content is rendered by a `<sal-components>` web component
    that fetches the body via an authenticated MaaS-token API after the WAF
    token is obtained. Static HTML is just an empty container.

Detection bypass for headless Chromium:
  - `--disable-blink-features=AutomationControlled` is set on the shared
    `PlaywrightHost` browser launch — removes the Chrome automation banner
    that AWS WAF fingerprints as a bot.
  - `navigator.webdriver = undefined` mask is added per-context here so it
    only applies to this client's pages.

Browser is owned by the shared `PlaywrightHost` (see playwright_host.py); this
client only owns its BrowserContext.
"""

import asyncio
from typing import Any

from trading_clients.cache import TTLCache
from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest
from trading_clients.playwright_host import BrowserContext, PlaywrightHost

REAL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

NAV_TIMEOUT_MS = 45_000
WAF_WAIT_MS = 30_000  # max wait for AWS WAF challenge → real page reload
HYDRATION_PAUSE_MS = 5_000  # let the SAL web component fetch + render the body

TRANSCRIPT_SELECTOR = ".stock-earnings-transcripts__sal-container__mdc"


class MorningstarClient:
    _context: BrowserContext | None

    def __init__(self, host: PlaywrightHost) -> None:
        self._host = host
        self._context = None
        self._cache = TTLCache()
        self._started = False

    async def startup(self) -> None:
        """Create the realistic-browser context on the shared host with a
        per-context webdriver mask that AWS WAF needs to clear.

        Idempotent: safe to call once at MCP lifespan startup.
        """
        if self._started:
            return
        self._context = await self._host.new_context(
            user_agent=REAL_UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        await self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        self._started = True

    async def close(self) -> None:
        """Close this client's context. The shared host stays up — its own
        teardown shuts down the browser."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        self._started = False

    async def get(self, endpoint: Endpoint, request: ParamsRequest | PathRequest) -> Any:
        """Fetch the endpoint's page through the shared browser context, return
        the decoded response model.

        Mirrors BaseClient.get() shape so callers use the same pattern as other
        clients. Path templates are substituted from PathRequest.to_path_params();
        ParamsRequest.to_params() is accepted for protocol parity but ignored
        (the transcript URL has no query params).
        """
        if not self._started or self._context is None:
            raise RuntimeError("MorningstarClient not started — call startup() first")
        if endpoint.base_url is None:
            raise ValueError(f"Morningstar endpoint {endpoint.path!r} requires base_url")

        path = endpoint.path
        if isinstance(request, PathRequest) and "{" in path:
            path = path.format_map(request.to_path_params())
        url = f"{endpoint.base_url}{path}"

        if endpoint.cache_ttl > 0:
            cached = self._cache.get(url, endpoint.cache_ttl)
            if cached is not None:
                return self._decode(endpoint, cached)

        text = await self._fetch(url)

        if endpoint.cache_ttl > 0:
            self._cache.put(url, text)

        return self._decode(endpoint, text)

    async def _fetch(self, url: str) -> str:
        """Open a fresh page, navigate, wait for the WAF challenge to clear and
        the SAL transcript component to hydrate, return the container's
        inner_text. Retries once on transient navigation errors."""
        assert self._context is not None  # narrowed by startup() check in get()
        ctx = self._context
        last_exc: Exception | None = None
        for attempt in range(2):
            page = await ctx.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                if resp is None:
                    raise RuntimeError(f"no response from {url}")
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} from {url}")
                # The container only exists on the real content page — its
                # appearance is the signal that the WAF reload completed.
                await page.wait_for_selector(TRANSCRIPT_SELECTOR, timeout=WAF_WAIT_MS)
                # Container appears as soon as the SAL web component mounts;
                # the actual transcript text fetches asynchronously after.
                await page.wait_for_timeout(HYDRATION_PAUSE_MS)
                return await page.locator(TRANSCRIPT_SELECTOR).first.inner_text()
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
        raise RuntimeError(f"morningstar fetch failed: {last_exc}")

    @staticmethod
    def _decode(endpoint: Endpoint, data: Any) -> Any:
        if endpoint.response_model:
            return endpoint.response_model.from_response(data)
        return data
