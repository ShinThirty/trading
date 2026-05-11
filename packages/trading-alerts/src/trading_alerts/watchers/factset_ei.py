"""FactSet Earnings Insight weekly PDF release watcher.

FactSet Earnings Insight is the institutional benchmark for earnings season
tone — S&P 500 beat rates, blended growth, forward EPS, P/E vs 5y/10y, and
sector revisions, published as a PDF every Friday afternoon ET.

URL pattern (no auth):
    https://advantage.factset.com/hubfs/Website/Resources%20Section/
      Research%20Desk/Earnings%20Insight/EarningsInsight_<MMDDYY>.pdf

Watcher walks back from today's Friday (or most-recent Friday if midweek)
up to 4 weeks, doing HEAD requests to find the latest live PDF, and
dedupes on the publish date. We deliberately don't pdf-parse here —
that pulls pdfplumber + pdfminer.six into the Lambda bundle (~15 MB)
for no operational benefit. The alert just announces "new EI is out" and
links the URL; the user opens it in a browser for the analysis.

Cadence: weekly Friday 23:00 UTC = 7 PM ET, after the typical Friday
afternoon publish window.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://advantage.factset.com/hubfs/Website/Resources%20Section/"
    "Research%20Desk/Earnings%20Insight"
)
MAX_FRIDAYS_BACK = 4
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # FactSet is no-auth and no config knobs

    publish_date, url = await _find_latest_pdf()
    if publish_date is None or url is None:
        logger.warning(
            "FactSet EI: no PDF found within %d Fridays back; skipping",
            MAX_FRIDAYS_BACK,
        )
        return []

    fields: list[dict[str, Any]] = [
        {"name": "Publish date", "value": publish_date.isoformat(), "inline": True},
        {"name": "Day", "value": publish_date.strftime("%A"), "inline": True},
        {"name": "PDF", "value": url, "inline": False},
    ]

    event = AlertEvent(
        dedup_key=f"factset-ei:{publish_date.isoformat()}",
        level="info",
        title=f"FactSet Earnings Insight {publish_date.isoformat()} released",
        fields=fields,
        footer_text=(
            "FactSet Earnings Insight — weekly S&P 500 earnings season pulse "
            "(beat rates, blended growth, forward EPS, P/E, sector revisions)"
        ),
        ttl_days=14,
    )
    return [event]


async def _find_latest_pdf() -> tuple[date | None, str | None]:
    """Walk back from today's most-recent Friday up to MAX_FRIDAYS_BACK Fridays,
    returning (date, URL) of the first live PDF. None on exhaustion."""
    anchor = _most_recent_friday(date.today())

    async with httpx.AsyncClient(
        timeout=20,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.8"},
        follow_redirects=True,
    ) as http:
        for i in range(MAX_FRIDAYS_BACK):
            candidate = anchor - timedelta(days=7 * i)
            url = f"{BASE_URL}/EarningsInsight_{candidate.strftime('%m%d%y')}.pdf"
            try:
                resp = await http.head(url)
            except httpx.HTTPError:
                # Network hiccup — try the next Friday rather than abort.
                continue
            if resp.status_code == 200:
                return candidate, url
            if resp.status_code != 404:
                logger.info("FactSet EI HEAD %s -> %d", url, resp.status_code)
            # Be polite between candidates.
            await asyncio.sleep(0.2)
    return None, None


def _most_recent_friday(today: date) -> date:
    """Return the most-recent Friday on or before `today`. weekday(): Mon=0, Fri=4."""
    days_since_friday = (today.weekday() - 4) % 7
    return today - timedelta(days=days_since_friday)
