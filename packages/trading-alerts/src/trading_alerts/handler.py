"""Lambda dispatcher: route EventBridge trigger payloads to watchers.

Each EventBridge rule sends `{"trigger": "<name>"}` to this single Lambda.
The handler looks up the watcher by name, runs it, and dispatches any
AlertEvents it returns.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from trading_alerts.config import AlertsConfig, load_config
from trading_alerts.dispatch import dispatch
from trading_alerts.event import AlertEvent
from trading_alerts.state import AlertStore, alert_store
from trading_alerts.watchers import (
    beige_book,
    cpi,
    dix,
    factset_ei,
    gex,
    naaim,
    nfp,
    pce,
    qra,
    tsmc_revenue,
    wpsr,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

WatcherFn = Callable[[AlertsConfig], Coroutine[Any, Any, list[AlertEvent]]]

WATCHERS: dict[str, WatcherFn] = {
    "naaim": naaim.run,
    "gex": gex.run,
    "dix": dix.run,
    "tsmc_revenue": tsmc_revenue.run,
    "wpsr": wpsr.run,
    "beige_book": beige_book.run,
    "qra": qra.run,
    "factset_ei": factset_ei.run,
    "nfp": nfp.run,
    "cpi": cpi.run,
    "pce": pce.run,
}

# Module-level cache for Lambda warm starts
_config: AlertsConfig | None = None
_store: AlertStore | None = None


def _get_config() -> AlertsConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_store(config: AlertsConfig) -> AlertStore:
    global _store
    if _store is None:
        _store = alert_store(config.dynamodb_table)
    return _store


def handler(event: Any, context: Any) -> dict:
    """Lambda entry point — dispatch a single trigger by name."""
    trigger = event.get("trigger") if isinstance(event, dict) else None
    if not trigger:
        return {"status": "error", "message": "missing 'trigger' key in event"}

    runner = WATCHERS.get(trigger)
    if runner is None:
        return {
            "status": "error",
            "message": f"unknown trigger: {trigger!r}",
            "available": sorted(WATCHERS),
        }

    config = _get_config()
    store = _get_store(config)
    logger.info("Running watcher: %s", trigger)

    try:
        events = asyncio.run(runner(config))
    except Exception as e:
        logger.exception("Watcher %s raised", trigger)
        return {"status": "error", "trigger": trigger, "message": str(e)}

    results: dict[str, str] = {}
    for ev in events:
        results[ev.dedup_key] = dispatch(config, store, ev)

    return {
        "status": "ok",
        "trigger": trigger,
        "events_emitted": len(events),
        "results": results,
    }
