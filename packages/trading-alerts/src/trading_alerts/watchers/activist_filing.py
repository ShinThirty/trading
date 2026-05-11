"""Schedule 13D activist filing watcher.

Schedule 13D is filed by anyone (or group) acquiring beneficial ownership
of >5% of a public company's voting stock *with intent to influence
control*. 13D/A is an amendment — change in position size, change in
plans, or addition of supporting holders.

Distinct from Schedule 13G (passive >5% holder, much less interesting —
indexers, pension funds). 13G is intentionally not in the trigger set.

We fire on any 13D / 13D/A appearing for a pipeline ticker. The Item 4
"Purpose of Transaction" narrative carries the actual signal (campaign
vs accumulation vs board push) and needs human reading via /analyze.

Cadence: daily morning ET. LOOKBACK_DAYS=2 with dispatcher dedup handles
re-runs.
"""

import logging
from datetime import date
from typing import Any

from trading_clients.edgar_client import EdgarClient
from trading_clients.endpoints import edgar as e

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent
from trading_alerts.pipeline_state import get_pipeline_tickers

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 2

# EDGAR has historically used both spellings; match either.
_ACTIVIST_FORMS: frozenset[str] = frozenset(
    {"SCHEDULE 13D", "SCHEDULE 13D/A", "SC 13D", "SC 13D/A"}
)


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config

    tickers = sorted(get_pipeline_tickers())
    if not tickers:
        logger.info("activist_filing: pipeline empty, nothing to scan")
        return []

    client = EdgarClient()
    today = date.today().isoformat()
    events: list[AlertEvent] = []

    try:
        for ticker in tickers:
            try:
                cik = await client.lookup_cik(ticker)
            except ValueError:
                logger.info("activist_filing: %s not in EDGAR ticker map; skipping", ticker)
                continue
            try:
                subs = await client.get(e.SUBMISSIONS, e.CikRequest(cik))
            except Exception as exc:
                logger.warning("activist_filing: SUBMISSIONS failed for %s: %s", ticker, exc)
                continue

            for filing in subs.within_window(today, LOOKBACK_DAYS):
                if filing.form.upper() not in _ACTIVIST_FORMS:
                    continue
                events.append(_to_event(ticker, cik, filing))
    finally:
        await client.close()

    logger.info(
        "activist_filing: scanned %d ticker(s), emitted %d event(s)",
        len(tickers),
        len(events),
    )
    return events


def _to_event(ticker: str, cik: int, filing: e.Filing) -> AlertEvent:
    is_amendment = filing.form.upper().endswith("/A")
    # Initial 13D is the louder event (new activist on the cap table); /A
    # amendments matter but are usually plan/position updates.
    level = "warning" if is_amendment else "critical"
    flavor = "amendment" if is_amendment else "initial filing"

    primary = filing.primary_document or ""
    if primary:
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing.accession_no_dashes}/{primary}"
        )
    else:
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&CIK={cik:010d}&type=SC+13D&dateb=&owner=include&count=10"
        )

    fields: list[dict[str, Any]] = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Form", "value": filing.form, "inline": True},
        {"name": "Filed", "value": filing.filing_date, "inline": True},
        {"name": "Accession", "value": filing.accession_number, "inline": False},
        {"name": "Filing", "value": f"[View on EDGAR]({url})", "inline": False},
    ]

    return AlertEvent(
        dedup_key=f"activist:{ticker}:{filing.accession_no_dashes}",
        level=level,
        title=f"{ticker} — Schedule 13D {flavor}",
        fields=fields,
        footer_text="SEC Schedule 13D — activist position disclosure",
        ttl_days=45,
    )
