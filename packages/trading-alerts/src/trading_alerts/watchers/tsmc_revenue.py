"""TSMC monthly consolidated revenue watcher.

TSMC publishes monthly revenue (in NT$ thousands) on the 10th of each month.
This is one of the cleanest leading indicators for the global semi cycle:
TSMC is the foundry layer underneath every advanced AI accelerator, so a
positive YoY surprise often pre-prints upside in the broader semi tape
(NVDA, AMD, AVGO, MRVL, ASML, AMAT) before any of those names report.

Source: TWSE OpenAPI t187ap05_L feed (listed-company monthly revenue, JSON,
no auth, no browser challenge). TSMC's own IR page now sits behind a
Cloudflare browser challenge and is not scrapable from a vanilla HTTP client.

The watcher dedupes on `tsmc:{YYYY-MM}` of the reported month — the first
time a new month's revenue lands we fire once. Re-runs short-circuit at
the dispatcher.

Cadence: daily 5-20 of each month. TSMC files monthly revenue with the
exchange ~the 10th, but the TWSE open-data feed (t187ap05_L) is a separate
aggregation that only regenerates around the 17th — so the window runs
through the 20th to catch the feed refresh, then dedup short-circuits the
rest of the days.
"""

import logging
from typing import Any

from trading_clients.endpoints.twse import (
    LISTED_MONTHLY_REVENUE,
    ListedMonthlyRevenueRequest,
    ListedMonthlyRevenueResponse,
)
from trading_clients.twse_client import TwseClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

TSMC_COMPANY_CODE = "2330"


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # TWSE OpenAPI has no auth and no config knobs

    client = TwseClient()
    try:
        feed: ListedMonthlyRevenueResponse = await client.get(
            LISTED_MONTHLY_REVENUE, ListedMonthlyRevenueRequest()
        )
    finally:
        await client.close()

    row = feed.by_code(TSMC_COMPANY_CODE)
    if row is None:
        logger.info(
            "TSMC: %s not present in TWSE OpenAPI feed (%d companies); skipping",
            TSMC_COMPANY_CODE,
            len(feed.rows),
        )
        return []

    period = f"{row.year}-{row.month:02d}"
    yoy = row.yoy_pct
    revenue_millions = row.revenue_curr_thousands / 1000

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
        {"name": "Revenue (NT$M)", "value": f"{revenue_millions:,.0f}", "inline": True},
    ]
    if yoy is not None:
        fields.append({"name": "YoY", "value": f"{yoy:+.1f}%", "inline": True})
    if row.mom_pct is not None:
        fields.append({"name": "MoM", "value": f"{row.mom_pct:+.1f}%", "inline": True})

    event = AlertEvent(
        dedup_key=f"tsmc:{period}",
        level=level,
        title=headline,
        fields=fields,
        footer_text="TSMC consolidated monthly revenue — leading indicator for global semi cycle",
        ttl_days=45,  # next month's print arrives ~30 days later; comfortable margin
    )
    return [event]
