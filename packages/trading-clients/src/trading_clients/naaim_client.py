"""NAAIM Exposure Index history client.

NAAIM publishes weekly active-manager equity exposure as a single
since-inception XLSX, republished every Wednesday/Thursday under a
date-stamped filename:

  https://www.naaim.org/wp-content/uploads/<YYYY>/<MM>/USE_Data-since-Inception_<YYYY>-<MM>-<DD>.xlsx

Discovery: the program page (Bricks-theme migration, 2026-06) no longer emits a
static link, but the weekly XLSX is indexed in the WordPress media library
(`/wp-json/wp/v2/media`). We query that newest-first, then download the binary.

Transport: as of 2026-06 naaim.org sits behind Cloudflare Bot Management, which
403s every httpx request — it fingerprints the TLS/JA3 handshake, not the
User-Agent, so even a real Chrome UA is blocked. When a shared `PlaywrightHost`
is available we therefore route both the discovery JSON and the XLSX download
through a real-browser context (`context.request`), whose browser fingerprint
clears Cloudflare. The client tolerates a `None` host (Lambda has no Playwright)
and falls back to httpx — degraded, since Cloudflare will block it — preserving
the prior zero-arg construction contract.

This class deliberately doesn't extend BaseClient — the two-step flow doesn't
fit the single-Endpoint shape, and the response is binary XLSX bytes parsed by
openpyxl in NaaimHistoryResponse.from_response.
"""

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoints.naaim import NaaimHistoryResponse
from trading_clients.playwright_host import BrowserContext, PlaywrightHost
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.naaim.org"
# The WordPress media library indexes the weekly XLSX even though the program
# page (Bricks-theme migration, 2026-06) no longer emits a static link.
MEDIA_PATH = "/wp-json/wp/v2/media"

# Real-browser fingerprint for the Playwright context. Cloudflare Bot Management
# on naaim.org keys on the TLS fingerprint, so a genuine Chromium context clears
# where httpx (any User-Agent) gets a 403.
REAL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# 6h cache: NAAIM is weekly, but a long TTL avoids re-downloading the 86KB
# XLSX during a back-to-back briefing → review session.
HISTORY_TTL_SECONDS = 21600

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 1.0),
}

# Match e.g. .../uploads/2026/05/USE_Data-since-Inception_2026-05-06.xlsx
_XLSX_RE = re.compile(
    r"https?://[^\s\"'<>]*?USE_Data[-_]since[-_]Inception[^\s\"'<>]*?\.xlsx",
    re.IGNORECASE,
)


class NaaimClient:
    _context: BrowserContext | None

    def __init__(self, host: PlaywrightHost | None = None) -> None:
        self._host = host
        self._context = None
        self._ctx_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": "trading-mcp/0.1 (Lingnan Liu; xmxu00@gmail.com)",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(2)
        self._cache: TTLCache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        await self._http.aclose()

    async def get_history(self) -> NaaimHistoryResponse:
        """Fetch + parse the NAAIM exposure history XLSX (2006 → present, weekly).

        Result is cached for 6h keyed on a stable identifier — the XLSX URL
        changes weekly but the parsed payload doesn't, so we cache the parsed
        response, not the bytes.
        """
        cache_key = "naaim:history"
        async with self._semaphore:
            cached = self._cache.get(cache_key, HISTORY_TTL_SECONDS)
            if cached is not None:
                return cached  # type: ignore[no-any-return]

            xlsx_url = await self._discover_xlsx_url()
            data: bytes = await self._fetch_bytes(xlsx_url)
            parsed = NaaimHistoryResponse.from_response(data)
            self._cache.put(cache_key, parsed)
            return parsed

    async def _ensure_context(self) -> BrowserContext | None:
        """Lazily create the shared-host browser context used to clear
        Cloudflare. Returns None when no host is configured (Lambda), in which
        case callers fall back to httpx."""
        if self._host is None:
            return None
        if self._context is not None:
            return self._context
        async with self._ctx_lock:
            if self._context is None:
                self._context = await self._host.new_context(
                    user_agent=REAL_UA,
                    locale="en-US",
                    timezone_id="America/New_York",
                )
        return self._context

    async def _discover_xlsx_url(self) -> str:
        """Return the newest USE_Data XLSX URL.

        Primary discovery is the WordPress REST media endpoint (newest-first);
        if that's unavailable we walk back recent Wednesdays against the stable
        upload-path convention.
        """
        status, body = await self._get(
            f"{BASE_URL}{MEDIA_PATH}",
            params={
                "search": "USE_Data-since-Inception",
                "per_page": 10,
                "orderby": "date",
                "order": "desc",
            },
        )
        if status == 200:
            try:
                items = json.loads(body)
            except ValueError:
                items = []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                # Prefer the public source_url; fall back to the guid the media
                # API also carries (the program-page link is gone post-Bricks).
                candidate = item.get("source_url") or ""
                if not candidate:
                    guid = item.get("guid")
                    if isinstance(guid, dict):
                        candidate = guid.get("rendered") or ""
                match = _XLSX_RE.search(candidate)
                if match:
                    return match.group(0)

        fallback = await self._discover_via_upload_path()
        if fallback:
            return fallback

        raise RuntimeError(
            "NAAIM USE_Data XLSX not found via REST media API or upload-path probe "
            "— site layout may have changed, or Cloudflare is blocking (no browser context)"
        )

    async def _discover_via_upload_path(self) -> str | None:
        """Probe the predictable uploads path for recent Wednesday publishes."""
        today = date.today()
        # NAAIM publishes Wednesday for the prior week; start at the most recent.
        most_recent_wed = today - timedelta(days=(today.weekday() - 2) % 7)
        for weeks_back in range(8):
            d = most_recent_wed - timedelta(weeks=weeks_back)
            url = (
                f"{BASE_URL}/wp-content/uploads/{d:%Y}/{d:%m}/"
                f"USE_Data-since-Inception_{d:%Y-%m-%d}.xlsx"
            )
            if await self._head_status(url) == 200:
                return url
        return None

    async def _fetch_bytes(self, url: str) -> bytes:
        status, body = await self._get(url)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} fetching NAAIM XLSX from {url}")
        return body

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> tuple[int, bytes]:
        """GET returning (status, body bytes). Routes through the browser
        context when available (clears Cloudflare), else httpx."""
        ctx = await self._ensure_context()
        await self._limiter.acquire()
        if ctx is not None:
            resp = await ctx.request.get(url, params=params or {})
            return resp.status, await resp.body()
        resp = await self._http.get(url, params=params)
        return resp.status_code, resp.content

    async def _head_status(self, url: str) -> int:
        """HEAD status code via the browser context when available, else httpx."""
        ctx = await self._ensure_context()
        await self._limiter.acquire()
        if ctx is not None:
            resp = await ctx.request.head(url)
            return resp.status
        resp = await self._http.head(url)
        return resp.status_code

    # Provided for protocol symmetry with other clients; not used.
    async def _request(self, *_: Any, **__: Any) -> Any:
        raise NotImplementedError("NaaimClient uses get_history() directly")
