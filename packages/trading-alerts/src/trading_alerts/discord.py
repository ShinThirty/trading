"""Discord bot notifications with rich embeds and mute buttons."""

import logging
from typing import Any

import httpx

from trading_alerts.config import DiscordConfig
from trading_alerts.monitor.positions import ShortOptionLeg

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"

COLOR_WARNING = 0xFFAA00  # amber
COLOR_CRITICAL = 0xFF0000  # red
COLOR_ERROR = 0x8B0000  # dark red for system errors


def _strategy_label(leg: ShortOptionLeg) -> str:
    if leg.option_type == "CALL" and leg.strategy == "COVERED_STOCK":
        return "Covered Call"
    if leg.option_type == "PUT":
        return "Cash-Secured Put"
    return leg.strategy


def _mute_buttons(dedup_key: str) -> dict:
    """Action row with Mute 1h and Mute 24h buttons."""
    return {
        "type": 1,  # ACTION_ROW
        "components": [
            {
                "type": 2,  # BUTTON
                "style": 2,  # SECONDARY (grey)
                "label": "Mute 1h",
                "custom_id": f"mute:3600:{dedup_key}",
            },
            {
                "type": 2,
                "style": 2,
                "label": "Mute 24h",
                "custom_id": f"mute:86400:{dedup_key}",
            },
        ],
    }


def send_alert(
    discord: DiscordConfig | None,
    leg: ShortOptionLeg,
    level: str,
    underlying_price: float,
    proximity_pct: float,
) -> None:
    """Send a warning or critical alert with mute buttons."""
    if not discord:
        logger.warning("No Discord bot configured, skipping notification")
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

    payload: dict[str, Any] = {
        "embeds": [embed],
        "components": [_mute_buttons(leg.dedup_key)],
    }

    _post_bot(discord, payload)


def send_error(discord: DiscordConfig | None, message: str) -> None:
    """Send a system error alert (e.g., token expired)."""
    if not discord:
        return
    embed = {
        "title": "Option Monitor Error",
        "description": message,
        "color": COLOR_ERROR,
    }
    _post_bot(discord, {"embeds": [embed]})


def _post_bot(discord: DiscordConfig, payload: dict) -> None:
    url = f"{DISCORD_API}/channels/{discord.channel_id}/messages"
    headers = {"Authorization": f"Bot {discord.bot_token}"}
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception:
        logger.exception("Failed to send Discord notification")
