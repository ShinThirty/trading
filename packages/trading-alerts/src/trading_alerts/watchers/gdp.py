"""BEA Gross Domestic Product (GDP) new-release watcher.

GDP publishes monthly at 8:30 AM ET — three estimates per quarter rotate
through the calendar (advance, second, third), so over a calendar year
there are 12 GDP releases (4 quarters × 3 estimates). Each release has a
distinct URL slug like /news/2026/gdp-advance-estimate-1st-quarter-2026,
which is a stable dedup key.

Watcher fetches the BEA current-releases index, extracts the latest GDP
release path, fetches the release page for a teaser, and dedupes on the
slug. Same pattern as pce, just a different field on the same index
response.

Cadence: weekly Thursday 14:00 UTC = 10 AM ET — late-month GDP releases
are typically Thursday at 8:30 ET. Non-GDP Thursdays no-op via dedup.
"""

import logging
from typing import Any

from trading_clients.bea_client import BeaClient
from trading_clients.endpoints.bea import (
    CURRENT_RELEASES,
    GDP_RELEASE,
    EmptyRequest,
    ReleasePathRequest,
)

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # BEA has no auth and no config knobs

    client = BeaClient()
    try:
        index = await client.get(CURRENT_RELEASES, EmptyRequest())
        if not index.gdp_release_path:
            logger.warning("GDP: no release link discovered; skipping")
            return []
        release = await client.get(GDP_RELEASE, ReleasePathRequest(path=index.gdp_release_path))
    finally:
        await client.close()

    slug = index.gdp_release_path.rsplit("/", 1)[-1] or index.gdp_release_path
    period_label = _period_from_slug(slug)
    title = f"BEA GDP ({period_label}) released" if period_label else "BEA GDP released"
    teaser = _first_sentence(release.text)

    fields: list[dict[str, Any]] = []
    if period_label:
        fields.append({"name": "Reference period", "value": period_label, "inline": True})
    fields.append(
        {
            "name": "Press release",
            "value": f"https://www.bea.gov{index.gdp_release_path}",
            "inline": False,
        }
    )
    if teaser:
        fields.append({"name": "Headline", "value": teaser, "inline": False})

    event = AlertEvent(
        dedup_key=f"gdp:{slug}",
        level="info",
        title=title,
        fields=fields,
        footer_text=(
            "BEA Gross Domestic Product — quarterly real GDP, advance/second/third estimates"
        ),
        ttl_days=45,
    )
    return [event]


def _period_from_slug(slug: str) -> str | None:
    """gdp-advance-estimate-1st-quarter-2026 -> 'Q1 2026 (advance estimate)'.

    gdp-second-estimate-2nd-quarter-2026 -> 'Q2 2026 (second estimate)'.
    """
    parts = slug.split("-")
    if "estimate" not in parts:
        return None
    try:
        est_idx = parts.index("estimate")
        # parts[1] is the estimate vintage (advance/second/third).
        vintage = parts[est_idx - 1]
        # quarter token is right after "estimate", e.g. "1st"
        quarter_tok = parts[est_idx + 1]
        # year is the last token
        year = parts[-1]
    except (ValueError, IndexError):
        return None
    if not year.isdigit() or len(year) != 4:
        return None
    quarter_num = quarter_tok[0]
    if not quarter_num.isdigit():
        return None
    return f"Q{quarter_num} {year} ({vintage} estimate)"


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
