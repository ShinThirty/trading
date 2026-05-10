"""Configuration loading from ~/.tradingrc (local) or SSM Parameter Store (Lambda)."""

import configparser
import json
import os
from dataclasses import dataclass
from pathlib import Path

RC_PATH = Path.home() / ".tradingrc"


@dataclass(frozen=True)
class DiscordConfig:
    bot_token: str
    channel_id: str


@dataclass(frozen=True)
class AlertsConfig:
    discord: DiscordConfig | None = None
    dynamodb_table: str | None = None  # None = in-memory store (local dev)


def load_from_rc(path: Path = RC_PATH) -> AlertsConfig:
    """Load credentials from ~/.tradingrc INI file (local development)."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    parser = configparser.ConfigParser()
    parser.read(path)

    discord = None
    if parser.has_section("discord") and parser.has_option("discord", "bot_token"):
        discord = DiscordConfig(
            bot_token=parser.get("discord", "bot_token"),
            channel_id=parser.get("discord", "channel_id"),
        )

    return AlertsConfig(discord=discord)


def load_from_ssm(parameter_name: str | None = None) -> AlertsConfig:
    """Load credentials from SSM Parameter Store SecureString (Lambda)."""
    import boto3

    name = parameter_name or os.environ.get("SSM_PARAMETER", "/trading-alerts/credentials")
    client = boto3.client("ssm")
    resp = client.get_parameter(Name=name, WithDecryption=True)
    data = json.loads(resp["Parameter"]["Value"])
    return AlertsConfig(
        discord=DiscordConfig(
            bot_token=data["discord_bot_token"],
            channel_id=data["discord_channel_id"],
        ),
        dynamodb_table=os.environ.get("DYNAMODB_TABLE", "trading-alerts"),
    )


def load_config() -> AlertsConfig:
    """Auto-detect environment: SSM if running in Lambda, else ~/.tradingrc."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return load_from_ssm()
    return load_from_rc()
