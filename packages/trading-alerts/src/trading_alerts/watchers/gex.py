"""GEX (dealer gamma exposure) regime watcher.

Fires daily on two distinct triggers from SqueezeMetrics' DIX/GEX history:

1. **Sign flip** — GEX changed sign vs the prior trading day. Pos -> neg
   means dealer hedging now amplifies flow (sell-offs and squeezes both
   become more violent). Neg -> pos means vol suppression returns.
2. **1m percentile extreme** — today's GEX sits at the top (>= 95) or
   bottom (<= 5) of the trailing 21 trading days. Top = extreme dealer
   suppression (cheap-hedge window). Bottom = extreme amplification
   (defined-risk preferred).

Cadence: daily after market close (SqueezeMetrics refreshes the CSV ~30 min
post-close). Dedup keys include the trade date so each fire path emits at
most once per day; the next day's data refreshes the dedup cohort.
"""

import logging
from typing import Any

from trading_clients.endpoints.squeeze_metrics import (
    DIX_HISTORY,
    DixHistoryResponse,
    DixRow,
    EmptyRequest,
)
from trading_clients.squeeze_metrics_client import SqueezeMetricsClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

PCT_HIGH = 95.0
PCT_LOW = 5.0
WINDOW_DAYS = 21


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # SqueezeMetrics has no auth and no config knobs

    client = SqueezeMetricsClient()
    try:
        history: DixHistoryResponse = await client.get(DIX_HISTORY, EmptyRequest())
    finally:
        await client.close()

    if len(history.rows) < 2:
        logger.warning("DIX history has fewer than 2 rows; skipping")
        return []

    today = history.rows[-1]
    prior = history.rows[-2]
    trade_date = today.date.isoformat()

    events: list[AlertEvent] = []

    flip_event = _flip_event(today, prior, trade_date)
    if flip_event is not None:
        events.append(flip_event)
    else:
        logger.info(
            "GEX no flip (today %s: %.0f, prior %s: %.0f)",
            trade_date,
            today.gex,
            prior.date.isoformat(),
            prior.gex,
        )

    pct_event = _percentile_event(history, trade_date)
    if pct_event is not None:
        events.append(pct_event)

    return events


def _flip_event(today: DixRow, prior: DixRow, trade_date: str) -> AlertEvent | None:
    """Detect GEX sign change vs the prior trading day."""
    today_pos = today.gex > 0
    prior_pos = prior.gex > 0
    if today_pos == prior_pos:
        return None

    if today_pos:
        # neg -> pos: vol suppression returns (good news, info-level)
        level = "info"
        title = "GEX flipped POSITIVE — dealer vol suppression returns"
        body = "Short-vol structures more attractive again; covered-call premium richer."
    else:
        # pos -> neg: amplification (bad news, warning-level)
        level = "warning"
        title = "GEX flipped NEGATIVE — dealer hedging now amplifies flow"
        body = (
            "Sell-offs and squeezes both more violent. Hedges become reactive, "
            "not preemptive. Avoid new long-delta until regime resets."
        )

    fields: list[dict[str, Any]] = [
        {"name": "Today GEX ($)", "value": f"{today.gex:,.0f}", "inline": True},
        {"name": "Prior GEX ($)", "value": f"{prior.gex:,.0f}", "inline": True},
        {"name": "Trade date", "value": trade_date, "inline": True},
        {"name": "SPX close", "value": f"{today.price:,.2f}", "inline": True},
        {"name": "DIX", "value": f"{today.dix:.4f}", "inline": True},
        {"name": "—", "value": body, "inline": False},
    ]

    return AlertEvent(
        dedup_key=f"gex-flip:{trade_date}",
        level=level,
        title=title,
        fields=fields,
        footer_text="SqueezeMetrics dealer net gamma — sign flip vs prior trading day",
    )


def _percentile_event(history: DixHistoryResponse, trade_date: str) -> AlertEvent | None:
    """Detect GEX in the top/bottom 1m percentile."""
    window = history.rows[-WINDOW_DAYS:] if len(history.rows) >= WINDOW_DAYS else history.rows
    if len(window) < 8:
        logger.info("Not enough rows to compute 1m GEX percentile")
        return None

    today = window[-1]
    values = [r.gex for r in window]
    below = sum(1 for v in values if v < today.gex)
    pct = below / len(values) * 100

    if PCT_LOW < pct < PCT_HIGH:
        logger.info("GEX 1m %ile %.0f within band — no alert", pct)
        return None

    if pct >= PCT_HIGH:
        # Extreme suppression — info, not warning (cheap hedges, low vol)
        level = "info"
        title = f"GEX 1m %ile {pct:.0f} — extreme dealer SUPPRESSION"
        body = "Cheap-hedge window if under-hedged; CC premium thin (low write attractiveness)."
    else:  # pct <= PCT_LOW
        # Extreme amplification — warning
        level = "warning"
        title = f"GEX 1m %ile {pct:.0f} — extreme dealer AMPLIFICATION"
        body = (
            "Avoid new long-delta; prefer defined-risk structures. "
            "Realized vol amplifies both directions."
        )

    fields: list[dict[str, Any]] = [
        {"name": "GEX ($)", "value": f"{today.gex:,.0f}", "inline": True},
        {"name": "1m %ile", "value": f"{pct:.0f}", "inline": True},
        {"name": "Trade date", "value": trade_date, "inline": True},
        {"name": "SPX close", "value": f"{today.price:,.2f}", "inline": True},
        {"name": "DIX", "value": f"{today.dix:.4f}", "inline": True},
        {"name": "—", "value": body, "inline": False},
    ]

    return AlertEvent(
        dedup_key=f"gex-pct-extreme:{trade_date}",
        level=level,
        title=title,
        fields=fields,
        footer_text="SqueezeMetrics dealer net gamma — 1m (21 trading day) percentile extreme",
    )
