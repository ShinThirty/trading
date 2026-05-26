"""FactSet Earnings Insight client (httpx, no auth — polite User-Agent).

FactSet publishes the Earnings Insight PDF weekly — typically Friday
afternoon ET, but shifted one or two days earlier during US market holiday
weeks (e.g., Memorial Day 2026 → Thu May 21). The URL is:

  https://advantage.factset.com/hubfs/Website/Resources%20Section/
    Research%20Desk/Earnings%20Insight/EarningsInsight_<MMDDYY>.pdf

The MMDDYY token is the publish date. We walk back day-by-day from the
request date (or today), skipping weekends, up to 4 weeks back. Brute force
catches off-schedule publications without needing a US holiday calendar.

This client deliberately doesn't extend BaseClient — the date-walk + binary
PDF + pdfplumber extraction doesn't fit the single-Endpoint shape, mirroring
how NaaimClient handles its discover-then-fetch flow.
"""

from __future__ import annotations

import asyncio
import io
from datetime import date, timedelta

import httpx
import pdfplumber

from trading_clients.cache import TTLCache
from trading_clients.endpoints.factset import (
    FactsetEarningsInsightResponse,
)
from trading_clients.rate_limit import RateLimiter

BASE_URL = (
    "https://advantage.factset.com/hubfs/Website/Resources%20Section/"
    "Research%20Desk/Earnings%20Insight"
)

# Pages we extract text from. Pages 16+ are chart images and not useful.
NARRATIVE_PAGES: tuple[int, ...] = (1, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)

# 6h cache: PDF refreshes once weekly; long TTL avoids re-fetching across a
# back-to-back briefing → review session.
INSIGHT_TTL_SECONDS = 21600

# Walk back at most 4 weeks of weekdays (~20 probes). Beyond that, the data
# is too stale to be useful for a "current earnings season" read; surface the
# failure instead.
MAX_DAYS_BACK = 28

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "default": (3, 1.0),
}


def _filename_for(d: date) -> str:
    return f"EarningsInsight_{d.strftime('%m%d%y')}.pdf"


class FactsetClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=60,  # 1MB PDF download
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(2)
        self._cache: TTLCache = TTLCache()
        self._limiter = RateLimiter(RATE_LIMITS)

    async def close(self) -> None:
        await self._http.aclose()

    async def get_earnings_insight(
        self, as_of_date: date | None = None
    ) -> FactsetEarningsInsightResponse:
        """Fetch + parse the latest available FactSet Earnings Insight PDF.

        If `as_of_date` is None, walks back day-by-day from today (skipping
        weekends) to find the most-recent weekday with a live PDF. Result is
        cached 6h keyed on the resolved publish date so repeated calls during
        a session don't re-fetch.
        """
        anchor = as_of_date or date.today()
        async with self._semaphore:
            current = anchor
            last_exc: Exception | None = None
            for _ in range(MAX_DAYS_BACK):
                # Skip Saturday (5) and Sunday (6) — FactSet never publishes on weekends.
                if current.weekday() >= 5:
                    current -= timedelta(days=1)
                    continue

                cache_key = f"factset:insight:{current.isoformat()}"
                cached = self._cache.get(cache_key, INSIGHT_TTL_SECONDS)
                if cached is not None:
                    return cached  # type: ignore[no-any-return]

                try:
                    pdf_bytes = await self._fetch_pdf(current)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        last_exc = e
                        current -= timedelta(days=1)
                        continue
                    raise
                pages_text = _extract_pages(pdf_bytes)
                parsed = FactsetEarningsInsightResponse.from_response(pages_text)
                self._cache.put(cache_key, parsed)
                return parsed
            raise RuntimeError(
                f"FactSet Earnings Insight not found in {MAX_DAYS_BACK} days "
                f"back from {anchor.isoformat()}: {last_exc}"
            )

    async def _fetch_pdf(self, publish_date: date) -> bytes:
        await self._limiter.acquire()
        url = f"{BASE_URL}/{_filename_for(publish_date)}"
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.content


def _extract_pages(pdf_bytes: bytes) -> dict[int, str]:
    """Pull text from NARRATIVE_PAGES of the PDF. Pages are 1-indexed."""
    out: dict[int, str] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n = len(pdf.pages)
        for p in NARRATIVE_PAGES:
            if p - 1 >= n:
                continue
            out[p] = pdf.pages[p - 1].extract_text() or ""
    return out
