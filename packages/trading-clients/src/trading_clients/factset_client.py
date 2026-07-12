"""FactSet Earnings Insight client (httpx, no auth — polite User-Agent).

FactSet publishes the Earnings Insight PDF weekly — typically Friday
afternoon ET, but shifted one or two days earlier during US market holiday
weeks (e.g., Memorial Day 2026 → Thu May 21). The URL is:

  https://advantage.factset.com/hubfs/Website/Resources%20Section/
    Research%20Desk/Earnings%20Insight/EarningsInsight_<MMDDYY>.pdf

The MMDDYY token is the publish date, optionally with an ``A`` suffix on some
weeks (e.g. ``EarningsInsight_052926A.pdf``). We walk back day-by-day from the
request date (or today), skipping weekends, up to 4 weeks back, trying both the
plain and ``A``-suffixed filename per day. Brute force catches off-schedule
publications and suffix variants without needing a US holiday calendar.

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


def _filenames_for(d: date) -> tuple[str, ...]:
    """Candidate PDF filenames for a publish date, in fetch-preference order.

    FactSet usually publishes ``EarningsInsight_<MMDDYY>.pdf``, but some weeks
    carry an ``A`` suffix instead (e.g. the May 29 2026 report was only posted
    as ``EarningsInsight_052926A.pdf`` — the plain name 404s). The suffix is
    inconsistent week-to-week, so we try the plain name first (historical
    default) and fall back to the suffixed variant before walking back a day.
    """
    stem = d.strftime("%m%d%y")
    return (f"EarningsInsight_{stem}.pdf", f"EarningsInsight_{stem}A.pdf")


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
            found = await self._walk_back(anchor)
            if found is None:
                raise RuntimeError(
                    f"FactSet Earnings Insight not found in {MAX_DAYS_BACK} days "
                    f"back from {anchor.isoformat()}"
                )
            parsed, resolved = found

            # Abbreviated mid-cycle editions sometimes drop the Valuation section
            # (the forward 12M P/E), e.g. the early-publish 2026-06-18 report.
            # Backfill the P/E from the most recent prior edition that carries it
            # so ERP / bear-regime reads don't go blind for a week. The number
            # moves slowly week-to-week; forward_pe_as_of records the source date.
            if parsed.forward_pe is None:
                prior = await self._walk_back(resolved - timedelta(days=1), require_forward_pe=True)
                if prior is not None:
                    src, src_date = prior
                    parsed.forward_pe = src.forward_pe
                    parsed.forward_pe_5y_avg = src.forward_pe_5y_avg
                    parsed.forward_pe_10y_avg = src.forward_pe_10y_avg
                    parsed.forward_pe_quarter_end = src.forward_pe_quarter_end
                    parsed.forward_pe_as_of = src.publish_date or src_date.isoformat()
            return parsed

    async def _walk_back(
        self, anchor: date, require_forward_pe: bool = False
    ) -> tuple[FactsetEarningsInsightResponse, date] | None:
        """Walk back from `anchor` to the most-recent weekday with a live PDF.

        Returns the parsed response + its resolved date, or None if nothing is
        found within MAX_DAYS_BACK. When `require_forward_pe` is set, editions
        that omit the forward 12M P/E (abbreviated reports) are skipped so the
        caller gets a report that actually carries the valuation number.
        """
        current = anchor
        for _ in range(MAX_DAYS_BACK):
            # Skip Saturday (5) and Sunday (6) — FactSet never publishes on weekends.
            if current.weekday() >= 5:
                current -= timedelta(days=1)
                continue

            cache_key = f"factset:insight:{current.isoformat()}"
            parsed = self._cache.get(cache_key, INSIGHT_TTL_SECONDS)
            if parsed is None:
                pdf_bytes: bytes | None = None
                for filename in _filenames_for(current):
                    try:
                        pdf_bytes = await self._fetch_pdf(filename)
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code != 404:
                            raise
                if pdf_bytes is None:
                    current -= timedelta(days=1)
                    continue
                parsed = FactsetEarningsInsightResponse.from_response(_extract_pages(pdf_bytes))
                self._cache.put(cache_key, parsed)

            if not require_forward_pe or parsed.forward_pe is not None:
                return parsed, current
            current -= timedelta(days=1)
        return None

    async def _fetch_pdf(self, filename: str) -> bytes:
        await self._limiter.acquire()
        url = f"{BASE_URL}/{filename}"
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
