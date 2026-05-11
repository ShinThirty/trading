"""NAAIM Exposure Index crowding watcher.

Fires when the latest weekly NAAIM print sits at |z-score| >= 1.5 over the
trailing 52 weeks. Crowded long (positive z) is a contrarian bearish setup;
extreme defensive (negative z) is a squeeze setup.

NAAIM publishes Wednesday afternoon ET; the EventBridge rule fires Thursday
morning to ensure the print has settled. Dedup key includes the print's
week-ending date, so once we alert on a given week the watcher stays quiet
until the next week's print arrives.
"""

import logging
from typing import Any

from trading_clients.naaim_client import NaaimClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # NAAIM has no auth and no config knobs

    client = NaaimClient()
    try:
        history = await client.get_history()
    finally:
        await client.close()

    if not history.entries:
        logger.warning("NAAIM history returned no entries; skipping")
        return []

    z = history.z_score
    exposure = history.latest_exposure
    if z is None or exposure is None:
        logger.info("NAAIM z-score not yet computable (need >= 8 weeks of data)")
        return []

    if abs(z) < 1.5:
        logger.info(
            "NAAIM z-score %+.2f within band — no alert (latest %s, exposure %.1f)",
            z,
            history.latest_date,
            exposure,
        )
        return []

    if z >= 2.0:
        level, headline = (
            "critical",
            "NAAIM GREEDY — crowded long, contrarian bearish",
        )
    elif z >= 1.5:
        level, headline = (
            "warning",
            "NAAIM stretched long — crowding building",
        )
    elif z <= -2.0:
        level, headline = (
            "critical",
            "NAAIM CAPITULATION — max defensive, contrarian bullish / squeeze setup",
        )
    else:  # -2.0 < z <= -1.5
        level, headline = (
            "warning",
            "NAAIM stretched defensive — positioning capitulating",
        )

    fields: list[dict[str, Any]] = [
        {"name": "Week ending", "value": history.latest_date, "inline": True},
        {"name": "Exposure", "value": f"{exposure:.1f}", "inline": True},
        {"name": "52w z-score", "value": f"{z:+.2f}", "inline": True},
    ]
    if history.percentile is not None:
        fields.append(
            {"name": "52w percentile", "value": f"{history.percentile:.0f}%", "inline": True}
        )
    if history.wow_change is not None:
        fields.append({"name": "WoW Δ", "value": f"{history.wow_change:+.1f}", "inline": True})
    if history.trailing_mean is not None:
        fields.append({"name": "52w mean", "value": f"{history.trailing_mean:.1f}", "inline": True})

    event = AlertEvent(
        dedup_key=f"naaim:{history.latest_date}",
        level=level,
        title=headline,
        fields=fields,
        footer_text="NAAIM Exposure Index — weekly active-manager equity exposure",
        ttl_days=21,
    )
    return [event]
