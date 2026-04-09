"""Configuration loading from ~/.tradingrc (local) or AWS Secrets Manager (Lambda)."""

import configparser
import json
import os
from dataclasses import dataclass
from pathlib import Path

from trading_clients.config import TradierConfig, WebullConfig

RC_PATH = Path.home() / ".tradingrc"


@dataclass(frozen=True)
class MonitorConfig:
    webull: WebullConfig
    tradier: TradierConfig
    discord_webhook_url: str


def load_from_rc(path: Path = RC_PATH) -> MonitorConfig:
    """Load credentials from ~/.tradingrc INI file (local development)."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    parser = configparser.ConfigParser()
    parser.read(path)

    webull_section = parser["webull"]
    tradier_section = parser["tradier"]

    discord_url = ""
    if parser.has_section("discord"):
        discord_url = parser.get("discord", "webhook_url", fallback="")

    return MonitorConfig(
        webull=WebullConfig(
            app_key=webull_section["app_key"],
            app_secret=webull_section["app_secret"],
            region_id=webull_section.get("region_id", "us"),
            token=webull_section.get("token") or None,
        ),
        tradier=TradierConfig(
            api_token=tradier_section["api_token"],
            sandbox=parser.getboolean("tradier", "sandbox", fallback=True),
        ),
        discord_webhook_url=discord_url,
    )


def load_from_secrets_manager(secret_name: str | None = None) -> MonitorConfig:
    """Load credentials from AWS Secrets Manager (Lambda)."""
    import boto3

    name = secret_name or os.environ.get("SECRET_NAME", "option-monitor/credentials")
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=name)
    data = json.loads(resp["SecretString"])
    return MonitorConfig(
        webull=WebullConfig(
            app_key=data["webull_app_key"],
            app_secret=data["webull_app_secret"],
            region_id="us",
            token=data["webull_token"],
        ),
        tradier=TradierConfig(
            api_token=data["tradier_api_token"],
            sandbox=data.get("tradier_sandbox", "false").lower() == "true",
        ),
        discord_webhook_url=data["discord_webhook_url"],
    )


def load_config() -> MonitorConfig:
    """Auto-detect environment: Secrets Manager if AWS_LAMBDA_FUNCTION_NAME is set, else RC."""
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return load_from_secrets_manager()
    return load_from_rc()
