"""FOMC statement new-release watcher.

The FOMC issues a statement at the end of each scheduled meeting (8x/year),
typically Wednesday 2:00 PM ET — the single highest-impact policy
artifact for the rates curve, the dollar, and equity duration. The
statement URL embeds the meeting date (monetary{YYYYMMDD}a.htm), so the
date itself is a stable dedup key.

Watcher fetches the FOMC calendar to discover the latest statement path,
fetches the statement page for a teaser, and dedupes on the embedded
date. New meeting -> info-level alert with the opening sentence so the
policy stance (hold / cut / hike) is visible at a glance.

Cadence: weekly Wednesday 19:30 UTC = 3:30 PM ET, ~90 min after the
typical 2:00 PM ET release. Non-FOMC Wednesdays no-op via dedup.
"""

import logging
from typing import Any

from trading_clients.endpoints.fed import (
    FOMC_CALENDAR,
    FOMC_STATEMENT,
    EmptyRequest,
    StatementPathRequest,
    extract_meeting_date,
)
from trading_clients.fed_client import FedClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # Fed has no auth and no config knobs

    client = FedClient()
    try:
        calendar = await client.get(FOMC_CALENDAR, EmptyRequest())
        latest_path = calendar.latest()
        if not latest_path:
            logger.warning("FOMC: no statements discovered; skipping")
            return []
        statement = await client.get(FOMC_STATEMENT, StatementPathRequest(path=latest_path))
    finally:
        await client.close()

    meeting_date = extract_meeting_date(latest_path)
    title = f"FOMC statement ({meeting_date}) released"
    teaser = _first_sentence(statement.text)

    fields: list[dict[str, Any]] = [
        {"name": "Meeting date", "value": meeting_date, "inline": True},
    ]
    fields.append(
        {
            "name": "Statement",
            "value": f"https://www.federalreserve.gov{latest_path}",
            "inline": False,
        }
    )
    if teaser:
        fields.append({"name": "Headline", "value": teaser, "inline": False})

    event = AlertEvent(
        dedup_key=f"fomc:{meeting_date}",
        level="info",
        title=title,
        fields=fields,
        footer_text="FOMC statement — 8x/yr policy decision, the highest-impact rates artifact",
        ttl_days=60,
    )
    return [event]


def _first_sentence(text: str, max_chars: int = 400) -> str:
    text = text.strip()
    if not text:
        return ""
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 >= len(text) or text[i + 1] in " \t\n"):
            candidate = text[: i + 1]
            if len(candidate) >= 60:
                return _truncate(candidate, max_chars)
    return _truncate(text, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
