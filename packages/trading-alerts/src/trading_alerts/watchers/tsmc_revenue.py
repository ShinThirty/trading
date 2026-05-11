"""TSMC monthly consolidated revenue watcher.

TSMC publishes monthly revenue (in NT$ millions) around the 10th of each
month at https://investor.tsmc.com/english/monthly-revenue/{year}. This is
one of the cleanest leading indicators for the global semi cycle: TSMC is
the foundry layer underneath every advanced AI accelerator, so a positive
YoY surprise often pre-prints upside in the broader semi tape (NVDA, AMD,
AVGO, MRVL, ASML, AMAT) before any of those names report.

The watcher dedupes on `tsmc:{YYYY-MM}` of the *reported* month — the first
time a new month's revenue lands, we fire once. Re-runs on the same print
short-circuit at the dispatcher.

Cadence: daily 5-15 of each month (covers the typical ~10th publish date
plus a few days of slack for holidays / late posts).
"""

import datetime as dt
import logging
from typing import Any

from trading_clients.endpoints.tsmc import (
    MONTHLY_REVENUE,
    GetMonthlyRevenueRequest,
    MonthlyRevenue,
    MonthlyRevenueResponse,
)
from trading_clients.tsmc_client import TsmcClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # TSMC has no auth and no config knobs

    today = dt.date.today()
    client = TsmcClient()
    try:
        latest = await _latest_reported(client, today.year)
        # Year-rollover edge: if running in early Jan and the new year's
        # table is empty, fall back to last year (December's print lands ~Jan 10).
        if latest is None and today.month == 1:
            latest = await _latest_reported(client, today.year - 1)
    finally:
        await client.close()

    if latest is None or latest.revenue_ntd_m is None:
        logger.info("TSMC: no reported month found; skipping")
        return []

    period = f"{latest.year}-{latest.month:02d}"
    yoy = latest.yoy_pct

    if yoy is None:
        level = "info"
        headline = f"TSMC {period} revenue posted"
    elif yoy >= 25:
        level = "critical"
        headline = f"TSMC {period} revenue +{yoy:.1f}% YoY — semi cycle accelerating"
    elif yoy >= 15:
        level = "warning"
        headline = f"TSMC {period} revenue +{yoy:.1f}% YoY — strong upside"
    elif yoy <= -25:
        level = "critical"
        headline = f"TSMC {period} revenue {yoy:.1f}% YoY — semi cycle breakdown"
    elif yoy <= -15:
        level = "warning"
        headline = f"TSMC {period} revenue {yoy:.1f}% YoY — material weakness"
    else:
        level = "info"
        headline = f"TSMC {period} revenue {yoy:+.1f}% YoY"

    fields: list[dict[str, Any]] = [
        {"name": "Month", "value": period, "inline": True},
        {"name": "Revenue (NT$M)", "value": f"{latest.revenue_ntd_m:,.0f}", "inline": True},
    ]
    if yoy is not None:
        fields.append({"name": "YoY", "value": f"{yoy:+.1f}%", "inline": True})

    event = AlertEvent(
        dedup_key=f"tsmc:{period}",
        level=level,
        title=headline,
        fields=fields,
        footer_text="TSMC consolidated monthly revenue — leading indicator for global semi cycle",
        ttl_days=45,  # next month's print arrives ~30 days later; comfortable margin
    )
    return [event]


async def _latest_reported(client: TsmcClient, year: int) -> MonthlyRevenue | None:
    """Fetch a year's table and return the most recent month with reported revenue."""
    resp: MonthlyRevenueResponse = await client.get(
        MONTHLY_REVENUE, GetMonthlyRevenueRequest(year=year)
    )
    reported = [r for r in resp.rows if r.revenue_ntd_m is not None]
    if not reported:
        return None
    return max(reported, key=lambda r: r.month)
