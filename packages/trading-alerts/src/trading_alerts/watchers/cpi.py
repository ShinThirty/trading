"""BLS Consumer Price Index (CPI) new-release watcher.

CPI publishes mid-month at 8:30 AM ET (typical window: days 10-15) — the
inflation read that anchors Fed policy expectations and the rates curve.
The press release URL (/news.release/cpi.htm) is static; only the rendered
content rotates each month.

Watcher fetches the press release narrative, extracts the reference month
from the opening sentence and the release year from the date stamp, and
dedupes on month-year. New period -> info-level alert with the headline
sentence.

Cadence: daily 14:30 UTC during days 10-15 of each month — covers the
typical 10-15 release window with a few hours of slack after the 8:30 ET
publish. Non-CPI days no-op via dedup.
"""

import logging
import re
from typing import Any

from trading_clients.bls_client import BlsClient
from trading_clients.endpoints.bls import (
    CPI_RELEASE,
    CpiReleaseResponse,
    EmptyRequest,
)

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)

_REFERENCE_MONTH_RE = re.compile(
    r"\bin\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\b",
    re.IGNORECASE,
)
_RELEASE_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?:\d{1,2},\s+)?(\d{4})\b",
    re.IGNORECASE,
)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # BLS has no auth and no config knobs

    client = BlsClient()
    try:
        resp: CpiReleaseResponse = await client.get(CPI_RELEASE, EmptyRequest())
    finally:
        await client.close()

    if not resp.text:
        logger.warning("CPI: empty body; skipping")
        return []

    period, release_year = _extract_period(resp.text)
    if period is None:
        logger.warning("CPI: could not parse reference month from body; skipping")
        return []

    dedup_key = f"cpi:{period}-{release_year or 'unknown'}"
    title = f"BLS CPI ({period} {release_year or ''}) released".strip()
    teaser = _first_sentence(resp.text)

    fields: list[dict[str, Any]] = [
        {"name": "Reference month", "value": period, "inline": True},
    ]
    if release_year:
        fields.append({"name": "Release year", "value": release_year, "inline": True})
    fields.append(
        {
            "name": "Press release",
            "value": "https://www.bls.gov/news.release/cpi.htm",
            "inline": False,
        }
    )
    if teaser:
        fields.append({"name": "Headline", "value": teaser, "inline": False})

    event = AlertEvent(
        dedup_key=dedup_key,
        level="info",
        title=title,
        fields=fields,
        footer_text="BLS Consumer Price Index — monthly headline + core inflation",
        ttl_days=45,
    )
    return [event]


def _extract_period(text: str) -> tuple[str | None, str | None]:
    m = _REFERENCE_MONTH_RE.search(text)
    period = m.group(1).capitalize() if m else None
    rd = _RELEASE_DATE_RE.search(text)
    year = rd.group(2) if rd else None
    return period, year


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
