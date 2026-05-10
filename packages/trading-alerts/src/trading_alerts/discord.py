"""Discord bot notifications: generic embed sender + mute buttons.

Each alert posts:
- An embed (title, color, fields, footer)
- An action row with Mute 1h / Mute 24h buttons whose custom_id encodes
  the dedup_key, parsed by interaction.py when the user clicks.
"""

import logging
from typing import Any

import httpx

from trading_alerts.config import DiscordConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"

COLOR_INFO = 0x3498DB  # blue
COLOR_WARNING = 0xFFAA00  # amber
COLOR_CRITICAL = 0xFF0000  # red
COLOR_ERROR = 0x8B0000  # dark red (system errors only)

LEVEL_COLOR: dict[str, int] = {
    "info": COLOR_INFO,
    "warning": COLOR_WARNING,
    "critical": COLOR_CRITICAL,
}


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


def send_embed(discord: DiscordConfig, event: AlertEvent) -> None:
    """Post an alert embed with mute buttons."""
    embed: dict[str, Any] = {
        "title": event.title,
        "color": LEVEL_COLOR.get(event.level, COLOR_INFO),
    }
    if event.fields:
        embed["fields"] = event.fields
    if event.footer_text:
        embed["footer"] = {"text": event.footer_text}

    payload: dict[str, Any] = {
        "embeds": [embed],
        "components": [_mute_buttons(event.dedup_key)],
    }
    _post_bot(discord, payload)


def send_error(discord: DiscordConfig | None, message: str) -> None:
    """Post a system-level error (no mute buttons; we want to see these)."""
    if not discord:
        return
    embed = {
        "title": "Trading Alerts Error",
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
