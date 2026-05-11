"""Material 8-K watcher — fires on signal-bearing 8-K items for pipeline tickers.

8-K is the SEC's "we have to tell you something happened" form. Most 8-Ks
are routine (Item 9.01 Financial Statements/Exhibits, etc.); a small set of
item codes carry real signal. We trigger when the filing's items intersect
endpoints.edgar.MATERIAL_8K_ITEMS:

  1.01 Material definitive agreement       1.02 Termination of agreement
  2.01 Acquisition / disposition           2.05 Restructuring charges
  2.06 Material impairment                 4.01 Auditor change
  4.02 Non-reliance on prior financials    5.02 Officer / director change
  7.01 Reg FD disclosure                   8.01 Other events

Earnings 8-Ks (Item 2.02) are excluded — earnings_calendar + transcript
tooling already cover that surface and would otherwise create duplicate
alerts every quarter.

One alert per (ticker, accession). Dedup key includes the accession number
so re-runs the same day stay silent.

Cadence: daily morning ET (after EDGAR's overnight refresh). LOOKBACK_DAYS
is 2 so a missed run still catches yesterday's filings — dispatcher dedup
handles the overlap.
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

ITEM_DESCRIPTIONS: dict[str, str] = {
    "1.01": "Material definitive agreement",
    "1.02": "Termination of material agreement",
    "2.01": "Acquisition / disposition of assets",
    "2.05": "Restructuring charges",
    "2.06": "Material impairment",
    "4.01": "Auditor change",
    "4.02": "Non-reliance on prior financials (restatement)",
    "5.02": "Officer / director change",
    "7.01": "Reg FD disclosure",
    "8.01": "Other events",
}

# Items where the *fact* of the filing is itself stock-moving. Other items
# carry signal too but the magnitude depends on the narrative — those go out
# at "info" level so the user can mute by default if they prefer.
HIGH_SIGNAL_ITEMS: frozenset[str] = frozenset({"2.01", "2.05", "2.06", "4.02", "5.02"})


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # EDGAR has no auth; the client uses a polite User-Agent.

    tickers = sorted(get_pipeline_tickers())
    if not tickers:
        logger.info("material_8k: pipeline empty, nothing to scan")
        return []

    client = EdgarClient()
    today = date.today().isoformat()
    events: list[AlertEvent] = []

    try:
        for ticker in tickers:
            try:
                cik = await client.lookup_cik(ticker)
            except ValueError:
                logger.info("material_8k: %s not in EDGAR ticker map; skipping", ticker)
                continue
            try:
                subs = await client.get(e.SUBMISSIONS, e.CikRequest(cik))
            except Exception as exc:
                logger.warning("material_8k: SUBMISSIONS failed for %s: %s", ticker, exc)
                continue

            for filing in subs.within_window(today, LOOKBACK_DAYS):
                if filing.form != "8-K":
                    continue
                hit_items = sorted(set(filing.items) & e.MATERIAL_8K_ITEMS)
                if not hit_items:
                    continue
                events.append(_to_event(ticker, cik, filing, hit_items))
    finally:
        await client.close()

    logger.info(
        "material_8k: scanned %d ticker(s), emitted %d event(s)",
        len(tickers),
        len(events),
    )
    return events


def _to_event(
    ticker: str,
    cik: int,
    filing: e.Filing,
    hit_items: list[str],
) -> AlertEvent:
    desc_lines = [
        f"**{code}** — {ITEM_DESCRIPTIONS.get(code, 'unknown item')}" for code in hit_items
    ]
    level = "warning" if set(hit_items) & HIGH_SIGNAL_ITEMS else "info"

    primary = filing.primary_document or ""
    if primary:
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing.accession_no_dashes}/{primary}"
        )
    else:
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&CIK={cik:010d}&type=8-K&dateb=&owner=include&count=10"
        )

    fields: list[dict[str, Any]] = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Filed", "value": filing.filing_date, "inline": True},
        {"name": "Accession", "value": filing.accession_number, "inline": True},
        {"name": "Items", "value": "\n".join(desc_lines), "inline": False},
        {"name": "Filing", "value": f"[View on EDGAR]({url})", "inline": False},
    ]

    return AlertEvent(
        dedup_key=f"material_8k:{ticker}:{filing.accession_no_dashes}",
        level=level,
        title=f"{ticker} 8-K — items {', '.join(hit_items)}",
        fields=fields,
        footer_text="SEC 8-K material event — pipeline ticker",
        ttl_days=45,
    )
