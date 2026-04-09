"""Lambda handler: check positions, evaluate thresholds, send Discord alerts.

MVP: stateless — no DynamoDB dedup/cooldown yet. Alerts fire every invocation
if thresholds are met. Phase 2 adds state management.
"""

import logging
import time
from typing import Any

from trading_clients.endpoints.tradier import (
    CLOCK,
    QUOTES,
    GetQuotesRequest,
)
from trading_clients.endpoints.tradier import (
    EmptyRequest as TradierEmptyRequest,
)
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    POSITIONS,
    AccountRequest,
)
from trading_clients.endpoints.webull import (
    EmptyRequest as WebullEmptyRequest,
)
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient

from option_monitor.config import MonitorConfig, load_config
from option_monitor.discord import send_alert, send_error
from option_monitor.monitor.positions import extract_short_legs
from option_monitor.monitor.thresholds import evaluate

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level cache for Lambda warm starts
_config: MonitorConfig | None = None


def _get_config() -> MonitorConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _compute_proximity(leg_option_type: str, strike: float, price: float) -> float:
    """Compute directional proximity: positive = OTM, negative = ITM."""
    if leg_option_type == "CALL":
        return (strike - price) / strike
    else:
        return (price - strike) / strike


def handler(event: Any, context: Any) -> dict:
    """Lambda entry point."""
    config = _get_config()
    tradier = TradierClient(config.tradier)
    webull = WebullClient(config.webull)

    try:
        # Check if market is open
        clock = tradier.raw_get(CLOCK, TradierEmptyRequest())
        market_state = clock.get("state", "closed")
        if market_state != "open":
            logger.info("Market is %s, skipping", market_state)
            return {"status": "market_closed", "state": market_state}

        # Discover all accounts and fetch positions from each
        accounts = webull.raw_get(ACCOUNT_LIST, WebullEmptyRequest())
        if not isinstance(accounts, list) or not accounts:
            logger.warning("No Webull accounts found")
            return {"status": "no_accounts"}

        legs = []
        for acct in accounts:
            time.sleep(2)  # respect Webull rate limit (2 req/2s for account endpoints)
            acct_id = acct.get("account_id", "")
            acct_label = acct.get("account_label", acct.get("account_type", ""))
            positions = webull.raw_get(POSITIONS, AccountRequest(account_id=acct_id))
            if not isinstance(positions, list):
                positions = []
            acct_legs = extract_short_legs(positions, acct_id, acct_label)
            legs.extend(acct_legs)
            logger.info(
                "Account %s (%s): %d short legs", acct_id[-4:], acct_label, len(acct_legs)
            )

        if not legs:
            logger.info("No short option legs found across %d accounts", len(accounts))
            return {"status": "no_short_legs", "accounts": len(accounts)}

        # Batch fetch underlying quotes
        symbols = list({leg.symbol for leg in legs})
        quotes = tradier.raw_get(QUOTES, GetQuotesRequest(symbols=",".join(symbols)))
        if not isinstance(quotes, list):
            quotes = []
        price_map = {q["symbol"]: q["last"] for q in quotes if q.get("last") is not None}

        notifications = 0

        for leg in legs:
            price = price_map.get(leg.symbol)
            if price is None:
                logger.warning("No quote for %s, skipping", leg.symbol)
                continue

            level = evaluate(leg, price)
            if level is None:
                continue

            proximity = _compute_proximity(leg.option_type, leg.strike, price)
            send_alert(config.discord_webhook_url, leg, level, price, proximity)
            notifications += 1
            logger.info(
                "ALERT %s: %s price=%.2f strike=%.2f proximity=%.1f%% dte=%d",
                level.upper(),
                leg.dedup_key,
                price,
                leg.strike,
                proximity * 100,
                leg.dte,
            )

        return {
            "status": "ok",
            "legs_checked": len(legs),
            "notifications_sent": notifications,
        }

    except RuntimeError as e:
        error_msg = str(e)
        logger.error("Runtime error: %s", error_msg)
        if "401" in error_msg or "token" in error_msg.lower():
            send_error(
                config.discord_webhook_url,
                f"Webull token expired — manual re-verification needed.\n\n`{error_msg}`",
            )
        return {"status": "error", "message": error_msg}

    finally:
        webull.close()
        tradier.close()
