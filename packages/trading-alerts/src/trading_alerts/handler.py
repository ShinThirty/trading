"""Lambda dispatcher: route EventBridge trigger payloads to watchers.

Each EventBridge rule sends `{"trigger": "<name>"}` to this single Lambda.
The handler looks up the watcher by name, runs it, and dispatches any
AlertEvents it returns.
"""

import asyncio
import logging
import traceback
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any

from trading_alerts.config import AlertsConfig, load_config
from trading_alerts.dispatch import dispatch
from trading_alerts.event import AlertEvent
from trading_alerts.state import AlertStore, alert_store
from trading_alerts.watchers import (
    activist_filing,
    beige_book,
    cpi,
    dix,
    factset_ei,
    fomc,
    gdp,
    gex,
    insider_buying,
    material_8k,
    naaim,
    nfp,
    pce,
    qra,
    tsmc_revenue,
    watchdog,
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
    "gdp": gdp.run,
    "fomc": fomc.run,
    "material_8k": material_8k.run,
    "activist_filing": activist_filing.run,
    "insider_buying": insider_buying.run,
    "watchdog": watchdog.run,
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


def _ops_exception_event(trigger: str, exc: BaseException) -> AlertEvent:
    """Build a Discord-bound ops alert describing an uncaught watcher exception.

    Dedup is keyed on (trigger, exception type, today). Same bug repeating
    across the same day collapses to one Discord post; a new day re-fires so
    a long-running outage stays visible.
    """
    exc_type = type(exc).__name__
    message = str(exc) or "(no message)"
    if len(message) > 500:
        message = message[:497] + "..."
    tb = traceback.format_exc()
    if len(tb) > 800:
        tb = "..." + tb[-797:]
    return AlertEvent(
        dedup_key=f"ops:exception:{trigger}:{exc_type}:{date.today().isoformat()}",
        level="critical",
        title=f"[OPS] {trigger} raised {exc_type}",
        fields=[
            {"name": "Trigger", "value": trigger, "inline": True},
            {"name": "Exception", "value": exc_type, "inline": True},
            {"name": "Message", "value": f"```{message}```", "inline": False},
            {"name": "Traceback", "value": f"```{tb}```", "inline": False},
        ],
        footer_text="trading-alerts ops",
        ttl_days=2,
    )


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
        # Surface the failure to Discord so a broken watcher doesn't go silent.
        try:
            dispatch(config, store, _ops_exception_event(trigger, e))
        except Exception:
            logger.exception("Failed to dispatch ops exception alert for %s", trigger)
        return {"status": "error", "trigger": trigger, "message": str(e)}

    results: dict[str, str] = {}
    for ev in events:
        # One bad event (e.g. transient Discord 5xx) shouldn't kill the rest
        # of the batch — log it and keep going.
        try:
            results[ev.dedup_key] = dispatch(config, store, ev)
        except Exception:
            logger.exception("dispatch raised for %s", ev.dedup_key)
            results[ev.dedup_key] = "error"

    return {
        "status": "ok",
        "trigger": trigger,
        "events_emitted": len(events),
        "results": results,
    }
