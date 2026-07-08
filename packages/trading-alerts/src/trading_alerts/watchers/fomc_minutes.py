"""FOMC minutes new-release watcher.

The Fed releases the minutes of each scheduled FOMC meeting three weeks
after the decision, Wednesday 2:00 PM ET. The minutes carry the
deliberation texture the statement omits — staff economic outlook,
balance-sheet discussion, and the participants' "a few / several / many /
most" language that reprices the rates curve on release day. The minutes
URL embeds the meeting date (fomcminutes{YYYYMMDD}.htm), so the date
itself is a stable dedup key.

Watcher fetches the FOMC calendar to discover the latest minutes path,
fetches the minutes page for a teaser (opening of the Participants' Views
section — where the signal lives), and dedupes on the embedded date.

Cadence: weekly Wednesday 19:30 UTC = 3:30 PM ET, ~90 min after the
typical 2:00 PM ET release. Non-release Wednesdays no-op via dedup.
"""

import logging
from typing import Any

from trading_clients.endpoints.fed import (
    FOMC_CALENDAR,
    FOMC_MINUTES,
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
        latest_path = calendar.latest_minutes()
        if not latest_path:
            logger.warning("FOMC minutes: none discovered; skipping")
            return []
        minutes = await client.get(FOMC_MINUTES, StatementPathRequest(path=latest_path))
    finally:
        await client.close()

    meeting_date = extract_meeting_date(latest_path)
    title = f"FOMC minutes ({meeting_date} meeting) released"
    participants = minutes.section("Participants' Views")
    teaser = _first_sentence(participants[1]) if participants else ""

    fields: list[dict[str, Any]] = [
        {"name": "Meeting date", "value": meeting_date, "inline": True},
    ]
    fields.append(
        {
            "name": "Minutes",
            "value": f"https://www.federalreserve.gov{latest_path}",
            "inline": False,
        }
    )
    if teaser:
        fields.append({"name": "Participants' Views (opening)", "value": teaser, "inline": False})

    event = AlertEvent(
        dedup_key=f"fomc-minutes:{meeting_date}",
        level="info",
        title=title,
        fields=fields,
        footer_text="FOMC minutes — deliberation texture, 3 weeks after each decision",
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
