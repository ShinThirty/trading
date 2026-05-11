"""DIX (dark-pool dollar-weighted short ratio) single-day move watcher.

DIX is a 0-1 ratio of dark-pool short-volume to total dark-pool volume on the
S&P 500. Higher = more bullish accumulation (dark-pool prints get tagged
"short" by executing brokers regardless of the ultimate buyer's direction,
so persistent high readings imply institutional buying through opaque venues).

A typical daily DIX move is 0.005-0.015. A single-day move of |Δ| >= 0.03 is
roughly a 2-3 sigma event and tends to mark either a fresh wave of
institutional accumulation (DIX up) or a defensive deleveraging pulse (DIX
down) that the surface tape hasn't yet acknowledged.

Cadence: daily after market close, same window as gex (SqueezeMetrics
refreshes the CSV ~30 min post-close). Dedup on the trade date so each fire
emits at most once per day.
"""

import logging
from typing import Any

from trading_clients.endpoints.squeeze_metrics import (
    DIX_HISTORY,
    DixHistoryResponse,
    EmptyRequest,
)
from trading_clients.squeeze_metrics_client import SqueezeMetricsClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 0.03
CRIT_THRESHOLD = 0.05


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
    delta = today.dix - prior.dix
    trade_date = today.date.isoformat()

    if abs(delta) < WARN_THRESHOLD:
        logger.info(
            "DIX Δ %+.4f (today %.4f, prior %.4f) within band — no alert",
            delta,
            today.dix,
            prior.dix,
        )
        return []

    bullish = delta > 0
    if abs(delta) >= CRIT_THRESHOLD:
        level = "critical"
        regime = "extreme accumulation" if bullish else "extreme deleveraging"
    else:
        level = "warning"
        regime = "accumulation surge" if bullish else "defensive pulse"

    direction = "+" if bullish else ""
    title = f"DIX {direction}{delta:.3f} single-day move — {regime}"

    if bullish:
        body = (
            "Dark-pool dollar-weighted short ratio jumped — institutional "
            "accumulation through opaque venues. Surface tape may lag the bid."
        )
    else:
        body = (
            "Dark-pool ratio dropped sharply — deleveraging or hedged unwinds. "
            "Watch for follow-through weakness if surface tape confirms."
        )

    fields: list[dict[str, Any]] = [
        {"name": "Today DIX", "value": f"{today.dix:.4f}", "inline": True},
        {"name": "Prior DIX", "value": f"{prior.dix:.4f}", "inline": True},
        {"name": "Δ", "value": f"{delta:+.4f}", "inline": True},
        {"name": "Trade date", "value": trade_date, "inline": True},
        {"name": "SPX close", "value": f"{today.price:,.2f}", "inline": True},
        {"name": "GEX ($)", "value": f"{today.gex:,.0f}", "inline": True},
        {"name": "—", "value": body, "inline": False},
    ]

    event = AlertEvent(
        dedup_key=f"dix-move:{trade_date}",
        level=level,
        title=title,
        fields=fields,
        footer_text="SqueezeMetrics DIX — single-day move ≥ 0.03 (2-3 sigma)",
    )
    return [event]
