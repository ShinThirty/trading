"""Discord interaction handler — processes button clicks and slash commands.

Lambda function URL receives Discord interactions, verifies Ed25519 signatures,
and routes to the appropriate handler (mute buttons, /unmute, /muted).
"""

import json
import logging
import os
import time
from base64 import b64decode
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Discord interaction types
PING = 1
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3

# Discord response types
PONG = 1
CHANNEL_MESSAGE = 4

# Lazy-loaded resources (Lambda warm start cache)
_table = None
_verify_key = None


def _get_table():
    global _table
    if _table is None:
        import boto3

        table_name = os.environ["DYNAMODB_TABLE"]
        _table = boto3.resource("dynamodb").Table(table_name)
    return _table


def _get_verify_key():
    global _verify_key
    if _verify_key is None:
        from nacl.signing import VerifyKey

        public_key = os.environ["DISCORD_PUBLIC_KEY"]
        _verify_key = VerifyKey(bytes.fromhex(public_key))
    return _verify_key


def _verify_signature(body: str, signature: str, timestamp: str) -> bool:
    """Verify Discord Ed25519 request signature."""
    try:
        key = _get_verify_key()
        key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
        return True
    except Exception:
        logger.exception("Signature verification failed")
        return False


def _respond(content: str, ephemeral: bool = True) -> dict:
    """Build a Discord interaction response."""
    flags = 64 if ephemeral else 0  # EPHEMERAL flag
    return {
        "type": CHANNEL_MESSAGE,
        "data": {"content": content, "flags": flags},
    }


def _handle_mute_button(custom_id: str) -> dict:
    """Handle Mute 1h / Mute 24h button click.

    custom_id format: mute:{seconds}:{dedup_key}
    """
    parts = custom_id.split(":", 2)
    if len(parts) != 3:
        return _respond("Invalid button data.")

    _, duration_str, dedup_key = parts
    duration = int(duration_str)
    now = time.time()

    table = _get_table()
    try:
        table.update_item(
            Key={"dedup_key": dedup_key},
            UpdateExpression="SET muted_until = :until",
            ExpressionAttributeValues={":until": int(now + duration)},
        )
    except Exception:
        logger.exception("Failed to mute %s", dedup_key)
        return _respond("Failed to mute — check Lambda logs.")

    hours = duration // 3600
    label = f"{hours}h" if hours else f"{duration // 60}m"
    # Extract readable leg name from dedup_key (after the colon)
    leg_label = dedup_key.split(":", 1)[-1] if ":" in dedup_key else dedup_key
    logger.info("MUTED %s for %s", dedup_key, label)
    return _respond(f"Muted **{leg_label}** for {label}.")


def _handle_unmute(options: list[dict]) -> dict:
    """Handle /unmute slash command."""
    leg = next((o["value"] for o in options if o["name"] == "leg"), None)
    if not leg:
        return _respond("Missing `leg` parameter.")

    table = _get_table()
    # Scan for matching muted records (muted_until > now)
    now = int(time.time())
    try:
        resp = table.scan(
            FilterExpression="muted_until > :now",
            ExpressionAttributeValues={":now": now},
        )
    except Exception:
        logger.exception("Failed to scan muted alerts")
        return _respond("Failed to fetch muted alerts.")

    # Match by leg label (case-insensitive substring match)
    search = leg.upper()
    matched = [item for item in resp.get("Items", []) if search in item["dedup_key"].upper()]

    if not matched:
        return _respond(f"No muted alerts matching `{leg}`.")

    unmuted = []
    for item in matched:
        try:
            table.update_item(
                Key={"dedup_key": item["dedup_key"]},
                UpdateExpression="SET muted_until = :zero",
                ExpressionAttributeValues={":zero": 0},
            )
            unmuted.append(item["dedup_key"].split(":", 1)[-1])
        except Exception:
            logger.exception("Failed to unmute %s", item["dedup_key"])

    if not unmuted:
        return _respond("Failed to unmute — check Lambda logs.")

    labels = "\n".join(f"- {u}" for u in unmuted)
    logger.info("UNMUTED %d alerts", len(unmuted))
    return _respond(f"Unmuted:\n{labels}")


def _handle_muted() -> dict:
    """Handle /muted slash command — list currently muted alerts."""
    table = _get_table()
    now = time.time()

    try:
        resp = table.scan(
            FilterExpression="muted_until > :now",
            ExpressionAttributeValues={":now": int(now)},
        )
    except Exception:
        logger.exception("Failed to scan muted alerts")
        return _respond("Failed to fetch muted alerts.")

    items = resp.get("Items", [])
    if not items:
        return _respond("No alerts currently muted.")

    lines = []
    for item in items:
        remaining = int(item["muted_until"]) - int(now)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        leg_label = item["dedup_key"].split(":", 1)[-1]
        time_left = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        lines.append(f"- **{leg_label}** ({time_left} remaining)")

    return _respond("Currently muted:\n" + "\n".join(lines))


def handler(event: Any, context: Any) -> dict:
    """Lambda function URL entry point for Discord interactions."""
    # Parse the request from Lambda function URL event
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = b64decode(body).decode()

    headers = event.get("headers", {})
    signature = headers.get("x-signature-ed25519", "")
    timestamp = headers.get("x-signature-timestamp", "")

    json_headers = {"content-type": "application/json"}

    # Verify signature
    if not _verify_signature(body, signature, timestamp):
        return {"statusCode": 401, "body": "Invalid signature"}

    data = json.loads(body)
    interaction_type = data.get("type")

    # PING — Discord verification handshake
    if interaction_type == PING:
        return {"statusCode": 200, "headers": json_headers, "body": json.dumps({"type": PONG})}

    # Button click
    if interaction_type == MESSAGE_COMPONENT:
        custom_id = data.get("data", {}).get("custom_id", "")
        if custom_id.startswith("mute:"):
            result = _handle_mute_button(custom_id)
        else:
            result = _respond("Unknown button.")
        return {"statusCode": 200, "headers": json_headers, "body": json.dumps(result)}

    # Slash command
    if interaction_type == APPLICATION_COMMAND:
        command_name = data.get("data", {}).get("name", "")
        options = data.get("data", {}).get("options", [])

        if command_name == "unmute":
            result = _handle_unmute(options)
        elif command_name == "muted":
            result = _handle_muted()
        else:
            result = _respond(f"Unknown command: `{command_name}`")

        return {"statusCode": 200, "headers": json_headers, "body": json.dumps(result)}

    return {"statusCode": 400, "headers": json_headers, "body": "Unknown interaction type"}
