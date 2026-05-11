"""EIA Weekly Petroleum Status Report (WPSR) watcher.

Three independent fire paths from a single Wednesday-morning fetch:

1. **Retail gasoline YoY** — pump price up >= 25% vs the same week last
   year. Marks a sustained inflation pass-through that hits CPI energy
   and consumer discretionary demand simultaneously.
2. **Retail gasoline WoW** — pump price up >= $0.20 in a single week.
   A fast pump shock that the consumer notices immediately.
3. **SPR move** — Strategic Petroleum Reserve change >= 5 mbbl WoW
   (warning) or >= 10 mbbl WoW (critical). SPR draws confirm a supply
   shortfall the administration is trying to bridge; SPR refills point
   to a perceived all-clear and absorb spot demand.

Cadence: weekly Wednesday 16:00 UTC (~12:00 ET — 90 min after the WPSR
publishes at 10:30 ET, leaving slack for slow refreshes). Dedup keys
include the WPSR week-ending date so each fire path emits at most once
per WPSR print.
"""

import logging
from typing import Any

from trading_clients.eia_client import EiaClient
from trading_clients.endpoints.eia import (
    SERIES,
    EiaSeriesRequest,
    EiaSeriesResponse,
)

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

GAS_YOY_THRESHOLD = 25.0  # %
GAS_WOW_THRESHOLD = 0.20  # $/gal
SPR_WARN_THRESHOLD_KBBL = 5_000.0  # 5 mbbl
SPR_CRIT_THRESHOLD_KBBL = 10_000.0  # 10 mbbl

# Series IDs (EIA v2 /seriesid/ format)
RETAIL_GAS_SERIES = "PET.EMM_EPMR_PTE_NUS_DPG.W"
SPR_SERIES = "PET.WCSSTUS1.W"
CRUDE_SERIES = "PET.WCESTUS1.W"  # for headline period anchor + context


async def run(config: AlertsConfig) -> list[AlertEvent]:
    if config.eia is None:
        logger.warning("EIA api_key not configured; wpsr skipped")
        return []

    client = EiaClient(config.eia)
    try:
        # Length 60 on retail covers >= 52w lookback for YoY math.
        retail = await client.get(SERIES, EiaSeriesRequest(RETAIL_GAS_SERIES, length=60))
        spr = await client.get(SERIES, EiaSeriesRequest(SPR_SERIES, length=4))
        crude = await client.get(SERIES, EiaSeriesRequest(CRUDE_SERIES, length=2))
    finally:
        await client.close()

    # Anchor the dedup period off the crude series (canonical WPSR Friday).
    # If crude is unavailable, fall back to SPR.
    period = _latest_period(crude) or _latest_period(spr)
    if period is None:
        logger.warning("WPSR: no crude/SPR period available; skipping")
        return []

    events: list[AlertEvent] = []

    gas_yoy_event = _gas_yoy_event(retail, period)
    if gas_yoy_event is not None:
        events.append(gas_yoy_event)

    gas_wow_event = _gas_wow_event(retail, period)
    if gas_wow_event is not None:
        events.append(gas_wow_event)

    spr_event = _spr_event(spr, period)
    if spr_event is not None:
        events.append(spr_event)

    if not events:
        logger.info("WPSR week ending %s — no thresholds breached", period)

    return events


def _latest_period(resp: EiaSeriesResponse) -> str | None:
    return resp.data[0].period if resp.data else None


def _gas_yoy_event(retail: EiaSeriesResponse, period: str) -> AlertEvent | None:
    """Retail gas YoY >= 25% — sustained inflation pass-through."""
    if len(retail.data) <= 52:
        return None
    cur = retail.data[0].value
    prior = retail.data[52].value
    if cur is None or prior is None or prior == 0:
        return None
    yoy_pct = (cur - prior) / prior * 100
    if yoy_pct < GAS_YOY_THRESHOLD:
        return None

    fields: list[dict[str, Any]] = [
        {"name": "Pump ($/gal)", "value": f"${cur:.3f}", "inline": True},
        {"name": "1y prior", "value": f"${prior:.3f}", "inline": True},
        {"name": "YoY", "value": f"+{yoy_pct:.1f}%", "inline": True},
        {"name": "Print week", "value": retail.data[0].period, "inline": True},
        {
            "name": "—",
            "value": (
                "Sustained pump-price pass-through. Hits CPI energy directly "
                "and pressures consumer discretionary demand. Watch for "
                "earnings commentary on demand destruction."
            ),
            "inline": False,
        },
    ]
    return AlertEvent(
        dedup_key=f"wpsr-gas-yoy:{period}",
        level="warning",
        title=f"Retail gas +{yoy_pct:.1f}% YoY — inflation pass-through",
        fields=fields,
        footer_text="EIA WPSR — US regular retail gasoline 1y change",
        ttl_days=10,
    )


def _gas_wow_event(retail: EiaSeriesResponse, period: str) -> AlertEvent | None:
    """Retail gas WoW >= $0.20 — fast pump shock."""
    if len(retail.data) < 2:
        return None
    cur = retail.data[0].value
    prior = retail.data[1].value
    if cur is None or prior is None:
        return None
    wow = cur - prior
    if wow < GAS_WOW_THRESHOLD:
        return None

    fields: list[dict[str, Any]] = [
        {"name": "Pump ($/gal)", "value": f"${cur:.3f}", "inline": True},
        {"name": "Prior week", "value": f"${prior:.3f}", "inline": True},
        {"name": "WoW Δ", "value": f"+${wow:.3f}", "inline": True},
        {"name": "Print week", "value": retail.data[0].period, "inline": True},
        {
            "name": "—",
            "value": (
                "Fast pump shock — consumer notices immediately. Refining "
                "crack-spread move or supply disruption likely upstream."
            ),
            "inline": False,
        },
    ]
    return AlertEvent(
        dedup_key=f"wpsr-gas-wow:{period}",
        level="warning",
        title=f"Retail gas +${wow:.3f} WoW — fast pump shock",
        fields=fields,
        footer_text="EIA WPSR — US regular retail gasoline 1w change",
        ttl_days=10,
    )


def _spr_event(spr: EiaSeriesResponse, period: str) -> AlertEvent | None:
    """SPR change >= 5 mbbl WoW (warning) or >= 10 mbbl (critical)."""
    if len(spr.data) < 2:
        return None
    cur = spr.data[0].value
    prior = spr.data[1].value
    if cur is None or prior is None:
        return None
    delta_kbbl = cur - prior
    if abs(delta_kbbl) < SPR_WARN_THRESHOLD_KBBL:
        return None

    drawing = delta_kbbl < 0
    delta_mbbl = delta_kbbl / 1000.0
    cur_mbbl = cur / 1000.0

    if abs(delta_kbbl) >= SPR_CRIT_THRESHOLD_KBBL:
        level = "critical"
        size = "major"
    else:
        level = "warning"
        size = "material"

    if drawing:
        title = f"SPR drew {abs(delta_mbbl):.1f} mbbl WoW — {size} draw"
        body = (
            "Administration tapping the reserve to bridge a supply shortfall. "
            "Bearish for crude (more spot supply); confirms ongoing disruption."
        )
    else:
        title = f"SPR refilled {delta_mbbl:.1f} mbbl WoW — {size} refill"
        body = (
            "Administration refilling — perceived all-clear. Absorbs spot "
            "demand; supportive of crude near-term."
        )

    fields: list[dict[str, Any]] = [
        {"name": "SPR (mbbl)", "value": f"{cur_mbbl:.1f}", "inline": True},
        {"name": "Prior week", "value": f"{(prior / 1000.0):.1f}", "inline": True},
        {"name": "WoW Δ", "value": f"{delta_mbbl:+.2f} mbbl", "inline": True},
        {"name": "Print week", "value": spr.data[0].period, "inline": True},
        {"name": "—", "value": body, "inline": False},
    ]
    return AlertEvent(
        dedup_key=f"wpsr-spr:{period}",
        level=level,
        title=title,
        fields=fields,
        footer_text="EIA WPSR — Strategic Petroleum Reserve weekly change",
        ttl_days=10,
    )
