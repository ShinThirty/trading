"""Lambda handler: check positions, evaluate thresholds, send Discord alerts.

Uses DynamoDB for dedup/cooldown state management. Falls back to in-memory
store for local testing (when dynamodb_table is not configured).
"""

import logging
import time
from calendar import timegm
from datetime import date, timedelta
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
from option_monitor.monitor.alerts import COOLDOWN_SECONDS, decide
from option_monitor.monitor.positions import extract_short_legs
from option_monitor.monitor.thresholds import evaluate
from option_monitor.state import AlertRecord, DynamoAlertStore, InMemoryAlertStore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level cache for Lambda warm starts
_config: MonitorConfig | None = None
_store: DynamoAlertStore | InMemoryAlertStore | None = None


def _get_config() -> MonitorConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_store(config: MonitorConfig) -> DynamoAlertStore | InMemoryAlertStore:
    global _store
    if _store is None:
        if config.dynamodb_table:
            _store = DynamoAlertStore(config.dynamodb_table)
        else:
            _store = InMemoryAlertStore()
    return _store


def _compute_proximity(leg_option_type: str, strike: float, price: float) -> float:
    """Compute directional proximity: positive = OTM, negative = ITM."""
    if leg_option_type == "CALL":
        return (strike - price) / strike
    else:
        return (price - strike) / strike


def _ttl_expire(expiration: str) -> int:
    """Calculate TTL: 7 days after option expiration (auto-cleanup)."""
    exp_date = date.fromisoformat(expiration)
    cleanup_date = exp_date + timedelta(days=7)
    return timegm(cleanup_date.timetuple())


def handler(event: Any, context: Any) -> dict:
    """Lambda entry point."""
    config = _get_config()
    tradier = TradierClient(config.tradier)
    webull = WebullClient(config.webull)
    store = _get_store(config)

    try:
        # Check if market is open
        clock = tradier.get(CLOCK, TradierEmptyRequest())
        market_state = clock.data.get("state", "closed")
        if market_state != "open":
            logger.info("Market is %s, skipping", market_state)
            return {"status": "market_closed", "state": market_state}

        # Discover all accounts and fetch positions from each
        accounts = webull.get(ACCOUNT_LIST, WebullEmptyRequest()).accounts
        if not accounts:
            logger.warning("No Webull accounts found")
            return {"status": "no_accounts"}

        legs = []
        for acct in accounts:
            time.sleep(2)  # respect Webull rate limit (2 req/2s for account endpoints)
            acct_id = acct.get("account_id", "")
            acct_label = acct.get("account_label", acct.get("account_type", ""))
            positions = webull.get(POSITIONS, AccountRequest(account_id=acct_id)).positions
            acct_legs = extract_short_legs(positions, acct_id, acct_label)
            legs.extend(acct_legs)
            logger.info("Account %s (%s): %d short legs", acct_id[-4:], acct_label, len(acct_legs))

        if not legs:
            logger.info("No short option legs found across %d accounts", len(accounts))
            return {"status": "no_short_legs", "accounts": len(accounts)}

        # Batch fetch underlying quotes
        symbols = list({leg.symbol for leg in legs})
        quotes = tradier.get(QUOTES, GetQuotesRequest(symbols=",".join(symbols))).quotes
        price_map = {q["symbol"]: q["last"] for q in quotes if q.get("last") is not None}

        now = time.time()
        notifications = 0
        suppressed = 0
        resolved = 0

        for leg in legs:
            price = price_map.get(leg.symbol)
            if price is None:
                logger.warning("No quote for %s, skipping", leg.symbol)
                continue

            level = evaluate(leg, price)
            prev = store.get(leg.dedup_key)
            decision = decide(level, prev, now)
            proximity = _compute_proximity(leg.option_type, leg.strike, price)

            if decision.should_notify:
                assert decision.level is not None
                send_alert(config.discord, leg, decision.level, price, proximity)
                store.put(
                    AlertRecord(
                        dedup_key=leg.dedup_key,
                        level=decision.level,
                        last_notified_at=now,
                        cooldown_until=now + COOLDOWN_SECONDS,
                        underlying_price=price,
                        proximity_pct=proximity,
                        dte=leg.dte,
                        ttl_expire=_ttl_expire(leg.expiration),
                    )
                )
                notifications += 1
                logger.info(
                    "%s %s: %s price=%.2f strike=%.2f proximity=%.1f%% dte=%d",
                    decision.action.upper(),
                    decision.level.upper(),
                    leg.dedup_key,
                    price,
                    leg.strike,
                    proximity * 100,
                    leg.dte,
                )

            elif decision.action == "resolve":
                store.put(
                    AlertRecord(
                        dedup_key=leg.dedup_key,
                        level="resolved",
                        last_notified_at=prev.last_notified_at if prev else now,
                        cooldown_until=0,
                        underlying_price=price,
                        proximity_pct=proximity,
                        dte=leg.dte,
                        ttl_expire=_ttl_expire(leg.expiration),
                    )
                )
                resolved += 1
                logger.info("RESOLVED: %s price=%.2f", leg.dedup_key, price)

            elif decision.action == "suppress":
                suppressed += 1
                logger.debug("SUPPRESSED: %s (cooldown)", leg.dedup_key)

        return {
            "status": "ok",
            "legs_checked": len(legs),
            "notifications_sent": notifications,
            "suppressed": suppressed,
            "resolved": resolved,
        }

    except RuntimeError as e:
        error_msg = str(e)
        logger.error("Runtime error: %s", error_msg)
        if "401" in error_msg or "token" in error_msg.lower():
            send_error(
                config.discord,
                f"Webull token expired — manual re-verification needed.\n\n`{error_msg}`",
            )
        return {"status": "error", "message": error_msg}

    finally:
        webull.close()
        tradier.close()
