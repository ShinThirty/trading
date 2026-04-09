"""Discord webhook notifications with rich embeds."""

import logging
from typing import Any

import httpx

from option_monitor.monitor.positions import ShortOptionLeg

logger = logging.getLogger(__name__)

COLOR_WARNING = 0xFFAA00  # amber
COLOR_CRITICAL = 0xFF0000  # red
COLOR_ERROR = 0x8B0000  # dark red for system errors


def _strategy_label(leg: ShortOptionLeg) -> str:
    if leg.option_type == "CALL" and leg.strategy == "COVERED_STOCK":
        return "Covered Call"
    if leg.option_type == "PUT":
        return "Cash-Secured Put"
    return leg.strategy


def send_alert(
    webhook_url: str,
    leg: ShortOptionLeg,
    level: str,
    underlying_price: float,
    proximity_pct: float,
) -> None:
    """Send a warning or critical alert to Discord."""
    if not webhook_url:
        logger.warning("No Discord webhook URL configured, skipping notification")
        return

    is_itm = proximity_pct <= 0
    color = COLOR_CRITICAL if level == "critical" else COLOR_WARNING
    level_label = "CRITICAL" if level == "critical" else "Warning"

    title = f"{level_label}: {leg.symbol} Short {leg.option_type} @ ${leg.strike:.2f}"
    if is_itm:
        title += " ITM"

    fields: list[dict[str, Any]] = [
        {"name": "Account", "value": leg.account_label or leg.account_id[-4:], "inline": True},
        {"name": "Underlying Price", "value": f"${underlying_price:.2f}", "inline": True},
        {"name": "Strike", "value": f"${leg.strike:.2f}", "inline": True},
        {"name": "DTE", "value": str(leg.dte), "inline": True},
        {
            "name": "Proximity",
            "value": f"{'ITM' if is_itm else f'{proximity_pct:.1%} from strike'}",
            "inline": True,
        },
        {"name": "Strategy", "value": _strategy_label(leg), "inline": True},
    ]

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {"text": f"{leg.symbol} {leg.strike:.0f}{leg.option_type[0]} {leg.expiration}"},
    }

    _post_webhook(webhook_url, {"embeds": [embed]})


def send_error(webhook_url: str, message: str) -> None:
    """Send a system error alert (e.g., token expired)."""
    if not webhook_url:
        return
    embed = {
        "title": "Option Monitor Error",
        "description": message,
        "color": COLOR_ERROR,
    }
    _post_webhook(webhook_url, {"embeds": [embed]})


def _post_webhook(webhook_url: str, payload: dict) -> None:
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Discord notification")
