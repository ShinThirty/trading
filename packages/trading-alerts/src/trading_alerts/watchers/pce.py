"""BEA Personal Income and Outlays (PCE) new-release watcher.

PCE publishes near month-end at 8:30 AM ET — the Fed's preferred inflation
gauge (core PCE in particular). The URL slug rotates each release
(e.g. /news/2026/personal-income-and-outlays-march-2026), so the slug
itself is a stable dedup key.

Watcher fetches the BEA current-releases index, extracts the latest PCE
release path, fetches the release page for a teaser, and dedupes on the
slug. New slug -> info-level alert with the headline opening sentence.

Cadence: daily 14:30 UTC during days 26-31 of each month — covers the
typical end-month publish window.
"""

import logging
from typing import Any

from trading_clients.bea_client import BeaClient
from trading_clients.endpoints.bea import (
    CURRENT_RELEASES,
    PCE_RELEASE,
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
        if not index.pce_release_path:
            logger.warning("PCE: no release link discovered; skipping")
            return []
        release = await client.get(PCE_RELEASE, ReleasePathRequest(path=index.pce_release_path))
    finally:
        await client.close()

    slug = index.pce_release_path.rsplit("/", 1)[-1] or index.pce_release_path
    period_label = _period_from_slug(slug)
    title = (
        f"BEA Personal Income & Outlays ({period_label}) released"
        if period_label
        else "BEA Personal Income & Outlays released"
    )
    teaser = _first_sentence(release.text)

    fields: list[dict[str, Any]] = []
    if period_label:
        fields.append({"name": "Reference period", "value": period_label, "inline": True})
    fields.append(
        {
            "name": "Press release",
            "value": f"https://www.bea.gov{index.pce_release_path}",
            "inline": False,
        }
    )
    if teaser:
        fields.append({"name": "Headline", "value": teaser, "inline": False})

    event = AlertEvent(
        dedup_key=f"pce:{slug}",
        level="info",
        title=title,
        fields=fields,
        footer_text="BEA Personal Income & Outlays — Fed's preferred inflation gauge (core PCE)",
        ttl_days=45,
    )
    return [event]


def _period_from_slug(slug: str) -> str | None:
    """personal-income-and-outlays-march-2026 -> 'March 2026'."""
    parts = slug.split("-")
    if len(parts) < 2:
        return None
    month = parts[-2]
    year = parts[-1]
    if not year.isdigit() or len(year) != 4:
        return None
    return f"{month.capitalize()} {year}"


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
