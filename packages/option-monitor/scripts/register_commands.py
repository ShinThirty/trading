#!/usr/bin/env python3
"""Register Discord slash commands for the option monitor bot.

One-time setup. Run after creating the Discord Application.

Usage:
    DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... \
        uv run python packages/option-monitor/scripts/register_commands.py

Environment variables:
    DISCORD_APP_ID    — Application ID from Discord Developer Portal
    DISCORD_BOT_TOKEN — Bot token from Discord Developer Portal
"""

import os
import sys

import httpx

DISCORD_API = "https://discord.com/api/v10"

COMMANDS = [
    {
        "name": "unmute",
        "description": "Unmute a previously muted option alert",
        "type": 1,  # CHAT_INPUT
        "options": [
            {
                "name": "leg",
                "description": "Option leg to unmute (e.g., AMZN-225.00-2026-06-18-CALL)",
                "type": 3,  # STRING
                "required": True,
            }
        ],
    },
    {
        "name": "muted",
        "description": "List all currently muted option alerts",
        "type": 1,
    },
]


def main() -> None:
    app_id = os.environ.get("DISCORD_APP_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")

    if not app_id or not bot_token:
        print("Error: Set DISCORD_APP_ID and DISCORD_BOT_TOKEN environment variables")
        sys.exit(1)

    url = f"{DISCORD_API}/applications/{app_id}/commands"
    headers = {"Authorization": f"Bot {bot_token}"}

    # Bulk overwrite global commands
    resp = httpx.put(url, json=COMMANDS, headers=headers, timeout=30)

    if resp.status_code == 200:
        commands = resp.json()
        print(f"Registered {len(commands)} commands:")
        for cmd in commands:
            print(f"  /{cmd['name']} — {cmd['description']}")
    else:
        print(f"Error {resp.status_code}: {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    main()
