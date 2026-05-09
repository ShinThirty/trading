"""NAAIM Exposure Index history client (httpx, no auth — polite User-Agent).

NAAIM publishes weekly active-manager equity exposure as a single
since-inception XLSX, republished every Wednesday/Thursday under a
date-stamped filename:

  https://www.naaim.org/wp-content/uploads/<YYYY>/<MM>/USE_Data-since-Inception_<YYYY>-<MM>-<DD>.xlsx

The filename moves each week, so we discover the current URL by scraping the
program page (HTML, no JS rendering required — verified to return a parseable
link with httpx alone) and then download the XLSX in a second request.

This class deliberately doesn't extend BaseClient — the two-step flow doesn't
fit the single-Endpoint shape, and the response is binary XLSX bytes parsed
by openpyxl in NaaimHistoryResponse.from_response.
"""

import asyncio
import re
from typing import Any

import httpx

from trading_clients.cache import TTLCache
from trading_clients.endpoints.naaim import NaaimHistoryResponse
from trading_clients.rate_limit import RateLimiter

BASE_URL = "https://www.naaim.org"
INDEX_PATH = "/programs/naaim-exposure-index/"

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
    def __init__(self) -> None:
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

    async def _discover_xlsx_url(self) -> str:
        """GET the program page and return the latest USE_Data XLSX URL."""
        await self._limiter.acquire()
        resp = await self._http.get(f"{BASE_URL}{INDEX_PATH}")
        resp.raise_for_status()
        match = _XLSX_RE.search(resp.text)
        if not match:
            raise RuntimeError(
                "NAAIM page did not contain a USE_Data XLSX link — page layout may have changed"
            )
        return match.group(0)

    async def _fetch_bytes(self, url: str) -> bytes:
        await self._limiter.acquire()
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.content

    # Provided for protocol symmetry with other clients; not used.
    async def _request(self, *_: Any, **__: Any) -> Any:
        raise NotImplementedError("NaaimClient uses get_history() directly")
