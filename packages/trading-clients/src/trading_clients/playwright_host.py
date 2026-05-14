"""Shared Playwright host — owns one Chromium process for all scrapers.

Each Playwright-backed client (SentimentClient, MorningstarClient, …) takes
this host and creates its own BrowserContext from `host.new_context(...)`.
Contexts are isolated sessions: each gets its own UA, cookies, viewport, and
init scripts (e.g. `navigator.webdriver` mask), but they share the underlying
Chromium process — saving ~150MB and one launch per additional scraper.

Browser-level launch args are necessarily shared:
  - `--disable-blink-features=AutomationControlled` removes the Chrome
    automation banner that AWS WAF (Morningstar) fingerprints. Benign for
    SentimentClient's targets (CBOE, AAII).

Per-context anti-detection (init scripts, custom headers) stays in each
client — that's where it isolates correctly.

Lifecycle: the host MUST outlive every client that uses it. The MCP server
lifespan starts the host first and closes it last; client `close()` only
closes the client's own context.

Playwright is the optional `sentiment` extra of trading-clients (the name
predates this refactor; effectively it's the "playwright" extra).
"""

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
        "playwright_host requires Playwright. Install: "
        "pip install 'trading-clients[sentiment]' (or `uv sync --all-packages` "
        "in this workspace, which installs it via trading-mcp)."
    ) from e

# Re-export the context type so client modules don't need their own Playwright
# import guard.
__all__ = ["BrowserContext", "PlaywrightHost"]

LAUNCH_ARGS = [
    # Required for AWS-WAF-protected sites (Morningstar). Benign elsewhere.
    "--disable-blink-features=AutomationControlled",
]


class PlaywrightHost:
    _playwright: Playwright | None
    _browser: Browser | None

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._started = False

    async def startup(self) -> None:
        """Launch Playwright + a single headless Chromium process.

        Idempotent: safe to call once at MCP lifespan startup.
        """
        if self._started:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
        )
        self._started = True

    async def new_context(self, **context_options: Any) -> BrowserContext:
        """Create a fresh isolated context. Caller owns its lifetime — must
        call `await context.close()` during their own teardown."""
        if not self._started or self._browser is None:
            raise RuntimeError("PlaywrightHost not started — call startup() first")
        return await self._browser.new_context(**context_options)

    async def close(self) -> None:
        """Shut down browser + Playwright. Must be called AFTER every client
        using this host has closed its own context."""
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
