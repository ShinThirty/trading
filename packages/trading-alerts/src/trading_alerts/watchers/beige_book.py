"""Federal Reserve Beige Book new-release watcher.

The Beige Book is the Fed's qualitative summary of economic conditions across
the 12 districts, published 8x/year ~2 weeks before each FOMC meeting. It's
the closest read on conditions the Fed itself is using when sizing the next
rate decision, so the release week — not just the wording — is itself a
signal that the rate-decision clock has started ticking.

Fetches the index page, finds the latest YYYYMM release token, and dedupes
on it. When a new period appears, fires a single info-level alert containing
the headline period plus the first sentences of the Overall / Labor / Prices
national-summary sections so the substance is visible at a glance.

Cadence: weekly Wednesday 19:00 UTC = 3 PM ET. New Beige Books publish
Wednesday 2 PM ET; the +1h slack accounts for the website's CDN settling.
"""

import logging
from typing import Any

from trading_clients.beige_book_client import BeigeBookClient
from trading_clients.endpoints.beige_book import (
    INDEX,
    SUMMARY,
    BeigeBookSummaryResponse,
    EmptyRequest,
    SummaryRequest,
)

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # Fed has no auth and no config knobs

    client = BeigeBookClient()
    try:
        index = await client.get(INDEX, EmptyRequest())
        latest = index.latest()
        if latest is None:
            logger.warning("Beige Book: no releases discovered; skipping")
            return []

        summary: BeigeBookSummaryResponse = await client.get(SUMMARY, SummaryRequest(period=latest))
    finally:
        await client.close()

    period_label = summary.period_label if summary.period_label != "?" else latest
    title = f"Beige Book {period_label} released"

    fields: list[dict[str, Any]] = [
        {"name": "Release", "value": period_label, "inline": True},
    ]
    if summary.prepared_by:
        fields.append({"name": "Prepared by", "value": summary.prepared_by, "inline": True})
    if summary.information_cutoff:
        fields.append({"name": "Info cutoff", "value": summary.information_cutoff, "inline": True})
    for label, body in (
        ("Overall", summary.overall),
        ("Labor", summary.labor),
        ("Prices", summary.prices),
    ):
        if body:
            fields.append({"name": label, "value": _first_sentence(body), "inline": False})

    event = AlertEvent(
        dedup_key=f"beige-book:{latest}",
        level="info",
        title=title,
        fields=fields,
        footer_text="Federal Reserve Beige Book — qualitative read on what the FOMC is seeing",
        ttl_days=60,  # 8x/yr ≈ 6.5 weeks between releases; comfortable buffer
    )
    return [event]


def _first_sentence(text: str, max_chars: int = 400) -> str:
    """Take the first sentence (up to max_chars) for embed display."""
    text = text.strip()
    if not text:
        return ""
    # Find the end of the first sentence — period followed by space + capital,
    # or just the first period if simpler.
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 >= len(text) or text[i + 1] in " \t"):
            candidate = text[: i + 1]
            if len(candidate) >= 40:  # avoid catching abbreviations like "U.S."
                return _truncate(candidate, max_chars)
    return _truncate(text, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
