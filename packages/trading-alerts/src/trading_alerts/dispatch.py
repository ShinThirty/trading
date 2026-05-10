"""Post an AlertEvent if its dedup_key hasn't been sent before."""

import logging
import time

from trading_alerts.config import AlertsConfig
from trading_alerts.discord import send_embed
from trading_alerts.event import AlertEvent
from trading_alerts.state import AlertRecord, AlertStore

logger = logging.getLogger(__name__)


def dispatch(config: AlertsConfig, store: AlertStore, event: AlertEvent) -> str:
    """Dedup, post, persist. Returns 'sent' / 'duplicate' / 'muted' / 'no-discord'."""
    now = time.time()
    prev = store.get(event.dedup_key)

    if prev is not None:
        if prev.muted_until and now < prev.muted_until:
            logger.info("MUTED: %s (until %s)", event.dedup_key, int(prev.muted_until))
            return "muted"
        logger.info("DUPLICATE: %s already sent at %s", event.dedup_key, int(prev.last_notified_at))
        return "duplicate"

    if config.discord is None:
        logger.warning("No Discord config — alert %s would have been sent", event.dedup_key)
        return "no-discord"

    send_embed(config.discord, event)
    store.put(
        AlertRecord(
            dedup_key=event.dedup_key,
            level=event.level,
            last_notified_at=now,
            cooldown_until=now,
            ttl_expire=int(now + event.ttl_days * 86400),
        )
    )
    logger.info("SENT: %s level=%s", event.dedup_key, event.level)
    return "sent"
