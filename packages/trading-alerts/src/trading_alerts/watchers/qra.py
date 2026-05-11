"""Treasury Quarterly Refunding Announcement (QRA) Policy Statement watcher.

The QRA Policy Statement is released 4x/year (early Feb / May / Aug / Nov)
on Wednesday 8:30 AM ET, two days after Monday's borrowing estimate. It
sets next-quarter auction sizes, the bill-vs-coupon mix, the buyback
program, and forward guidance — the texture that drives the Treasury
supply expectation embedded in the front and belly of the curve.

Fetches the most-recent-documents page, dedupes on the press-release slug,
and when a new statement appears posts an info-level alert with the
release date, inferred quarter label, link, and an excerpt of the body.

Cadence: weekly Wednesday 14:00 UTC = 10 AM ET, ~90 min after the 8:30 ET
release. Conservatively fires every Wednesday year-round; the slug-based
dedup means a non-QRA Wednesday is a no-op.
"""

import logging
from typing import Any

from trading_clients.endpoints.treasury import (
    QRA_LATEST_INDEX,
    QRA_STATEMENT,
    EmptyRequest,
    StatementPathRequest,
)
from trading_clients.treasury_client import TreasuryClient

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # Treasury has no auth and no config knobs

    client = TreasuryClient()
    try:
        index = await client.get(QRA_LATEST_INDEX, EmptyRequest())
        if not index.latest_path:
            logger.warning("QRA: no Policy Statement link discovered; skipping")
            return []
        statement = await client.get(QRA_STATEMENT, StatementPathRequest(path=index.latest_path))
    finally:
        await client.close()

    slug = index.latest_path.rsplit("/", 1)[-1] or index.latest_path
    quarter_label = _quarter_label(statement.release_date)
    title = (
        f"Treasury QRA {quarter_label} Policy Statement released"
        if quarter_label
        else "Treasury QRA Policy Statement released"
    )

    fields: list[dict[str, Any]] = []
    if statement.release_date:
        fields.append({"name": "Release date", "value": statement.release_date, "inline": True})
    if quarter_label:
        fields.append({"name": "Quarter", "value": quarter_label, "inline": True})
    fields.append(
        {
            "name": "Press release",
            "value": f"https://home.treasury.gov{index.latest_path}",
            "inline": False,
        }
    )
    excerpt = _excerpt(statement.text)
    if excerpt:
        fields.append({"name": "Excerpt", "value": excerpt, "inline": False})

    event = AlertEvent(
        dedup_key=f"qra:{slug}",
        level="info",
        title=title,
        fields=fields,
        footer_text="Treasury QRA — sets next-quarter auction sizes, bill/coupon mix, buybacks",
        ttl_days=120,  # 4x/yr ≈ 13 weeks between releases; comfortable buffer
    )
    return [event]


def _quarter_label(release_date: str | None) -> str | None:
    """Infer 'YYYY QN' from a YYYY-MM-DD release date."""
    if not release_date or len(release_date) < 7:
        return None
    try:
        year = int(release_date[:4])
        month = int(release_date[5:7])
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    quarter = (month - 1) // 3 + 1
    return f"{year} Q{quarter}"


def _excerpt(text: str, max_chars: int = 600) -> str:
    """Take the first ~max_chars of substantive prose. The text already starts
    at the 'WASHINGTON — ...' marker (extractor trimmed boilerplate), so the
    leading slice is the body opening."""
    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Cut at the last sentence boundary within the budget so the excerpt
    # doesn't end mid-word.
    snippet = text[:max_chars]
    last_period = snippet.rfind(". ")
    if last_period >= max_chars - 200:  # only trim if we keep most of the budget
        return snippet[: last_period + 1]
    return snippet.rstrip() + "…"
