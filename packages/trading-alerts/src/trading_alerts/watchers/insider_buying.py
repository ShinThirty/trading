"""Insider buying watcher — Form 4 cluster + single-large purchases.

Two distinct fire paths for pipeline tickers, both buys-only (Code=P,
open-market purchases — grants, exercises, planned 10b5-1 sales are excluded
because they're noisy or non-discretionary):

  * **Cluster** — ≥2 distinct insiders buying within a rolling 5-day window.
    Lakonishok-style signal: one insider can be wrong about timing or have
    idiosyncratic reasons; multiple insiders converging on the same window
    suggests shared conviction. ≥3 distinct insiders escalates to "critical".

  * **Single-large** — one filing whose total purchase value crosses a
    role-tiered $-threshold. CEO/CFO buying is rare and high-conviction, so
    they fire at $100K (and "critical" level). All other officers, directors,
    and 10%+ holders fire at $250K (and "warning" level).

A single filing can contribute to both a cluster fire AND a single-large
fire — different dedup keys so they don't collide.

LOOKBACK_DAYS=5 because insider activity is lumpy. Dispatcher dedup
(cluster keyed on the buyer set; single keyed on accession) handles re-runs
inside the window.

Cadence: daily morning ET. Staggered 30 min after activist_filing (which is
itself staggered 15 min after material_8k) to avoid triple-tapping EDGAR's
rate limit in the same second.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from trading_clients.edgar_client import EdgarClient
from trading_clients.endpoints import edgar as e

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent
from trading_alerts.pipeline_state import get_pipeline_tickers

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 5

CLUSTER_MIN_INSIDERS = 2
CLUSTER_CRITICAL_INSIDERS = 3

SINGLE_LARGE_CEO_CFO_USD = 100_000
SINGLE_LARGE_OTHER_USD = 250_000


@dataclass(frozen=True)
class _BuyRecord:
    """One pipeline-ticker Form 4 with buys, normalized for the aggregation pass."""

    accession: str
    accession_no_dashes: str
    filing_date: str  # YYYY-MM-DD — date EDGAR received the filing
    person: str
    role: str  # CEO / CFO / OFFICER / DIRECTOR / 10%+ / OTHER
    is_ceo_or_cfo: bool
    total_value: float
    total_shares: float
    avg_price: float | None
    latest_tx_date: str  # YYYY-MM-DD — most recent transaction date inside the filing


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # EDGAR is unauthenticated; client uses a polite User-Agent.

    tickers = sorted(get_pipeline_tickers())
    if not tickers:
        logger.info("insider_buying: pipeline empty, nothing to scan")
        return []

    client = EdgarClient()
    today = date.today().isoformat()
    events: list[AlertEvent] = []

    try:
        for ticker in tickers:
            try:
                cik = await client.lookup_cik(ticker)
            except ValueError:
                logger.info("insider_buying: %s not in EDGAR ticker map; skipping", ticker)
                continue
            try:
                subs = await client.get(e.SUBMISSIONS, e.CikRequest(cik))
            except Exception as exc:
                logger.warning("insider_buying: SUBMISSIONS failed for %s: %s", ticker, exc)
                continue

            form4_filings = [f for f in subs.within_window(today, LOOKBACK_DAYS) if f.form == "4"]
            if not form4_filings:
                continue

            buys = await _collect_buys(client, cik, form4_filings)
            if not buys:
                continue

            # Cluster fire — ≥N distinct insiders buying inside the window.
            distinct_buyers = sorted({b.person for b in buys})
            if len(distinct_buyers) >= CLUSTER_MIN_INSIDERS:
                events.append(_cluster_event(ticker, cik, buys, distinct_buyers))

            # Single-large fire — one event per filing crossing the $-threshold.
            for b in buys:
                threshold = SINGLE_LARGE_CEO_CFO_USD if b.is_ceo_or_cfo else SINGLE_LARGE_OTHER_USD
                if b.total_value >= threshold:
                    events.append(_single_event(ticker, cik, b))
    finally:
        await client.close()

    logger.info(
        "insider_buying: scanned %d ticker(s), emitted %d event(s)",
        len(tickers),
        len(events),
    )
    return events


async def _collect_buys(
    client: EdgarClient,
    cik: int,
    form4_filings: list[e.Filing],
) -> list[_BuyRecord]:
    out: list[_BuyRecord] = []
    for filing in form4_filings:
        if not filing.primary_document:
            continue
        try:
            resp = await client.get(
                e.FILING_FORM4,
                e.FilingDocRequest(
                    cik=cik,
                    accession_no_dashes=filing.accession_no_dashes,
                    filename=filing.primary_document,
                ),
            )
        except Exception as exc:
            logger.warning(
                "insider_buying: FORM4 fetch failed for %s/%s: %s",
                cik,
                filing.accession_number,
                exc,
            )
            continue
        if resp.filing is None:
            continue
        if not resp.filing.purchases():
            continue
        out.append(
            _BuyRecord(
                accession=filing.accession_number,
                accession_no_dashes=filing.accession_no_dashes,
                filing_date=filing.filing_date,
                person=resp.filing.person,
                role=resp.filing.role_tag,
                is_ceo_or_cfo=resp.filing.is_ceo_or_cfo,
                total_value=resp.filing.total_purchase_value,
                total_shares=resp.filing.total_purchase_shares,
                avg_price=resp.filing.avg_purchase_price,
                latest_tx_date=resp.filing.latest_purchase_date or filing.filing_date,
            )
        )
    return out


def _cluster_event(
    ticker: str,
    cik: int,
    buys: list[_BuyRecord],
    distinct_buyers: list[str],
) -> AlertEvent:
    n = len(distinct_buyers)
    level = "critical" if n >= CLUSTER_CRITICAL_INSIDERS else "warning"
    total_value = sum(b.total_value for b in buys)
    window_start = min(b.latest_tx_date for b in buys)
    window_end = max(b.latest_tx_date for b in buys)
    window = window_start if window_start == window_end else f"{window_start} → {window_end}"

    # Dedup by the SET of distinct buyers so the cluster re-fires only when a
    # new buyer joins (which is itself signal). Hash to keep the key bounded.
    buyers_hash = hashlib.sha1(",".join(distinct_buyers).encode()).hexdigest()[:12]

    # Per-buyer summary (one line each), capped to keep the embed under
    # Discord's 1024-char field limit.
    by_person: dict[str, list[_BuyRecord]] = {}
    for b in buys:
        by_person.setdefault(b.person, []).append(b)

    insider_lines: list[str] = []
    for person in distinct_buyers[:10]:
        person_buys = by_person[person]
        person_value = sum(b.total_value for b in person_buys)
        role = person_buys[0].role
        latest = max(b.latest_tx_date for b in person_buys)
        insider_lines.append(f"**{person}** ({role}) — {_fmt_usd(person_value)} on {latest}")
    if len(distinct_buyers) > 10:
        insider_lines.append(f"…+{len(distinct_buyers) - 10} more")

    filing_lines: list[str] = []
    for b in buys[:10]:
        filing_lines.append(f"[{b.accession}]({_filing_url(cik, b.accession_no_dashes)})")
    if len(buys) > 10:
        filing_lines.append(f"…+{len(buys) - 10} more")

    fields: list[dict[str, Any]] = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Insiders", "value": str(n), "inline": True},
        {"name": "Total Value", "value": _fmt_usd(total_value), "inline": True},
        {"name": "Window", "value": window, "inline": False},
        {"name": "Buyers", "value": "\n".join(insider_lines), "inline": False},
        {"name": "Filings", "value": "\n".join(filing_lines), "inline": False},
    ]
    return AlertEvent(
        dedup_key=f"insider_cluster:{ticker}:{buyers_hash}",
        level=level,
        title=f"{ticker} — insider cluster buy ({n} insiders, {_fmt_usd(total_value)})",
        fields=fields,
        footer_text="SEC Form 4 — clustered open-market purchases",
        ttl_days=14,
    )


def _single_event(ticker: str, cik: int, b: _BuyRecord) -> AlertEvent:
    level = "critical" if b.is_ceo_or_cfo else "warning"
    avg_price = f"${b.avg_price:.2f}" if b.avg_price is not None else "—"
    fields: list[dict[str, Any]] = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Buyer", "value": b.person, "inline": True},
        {"name": "Role", "value": b.role, "inline": True},
        {"name": "Shares", "value": f"{int(b.total_shares):,}", "inline": True},
        {"name": "Avg Price", "value": avg_price, "inline": True},
        {"name": "Value", "value": _fmt_usd(b.total_value), "inline": True},
        {"name": "Tx Date", "value": b.latest_tx_date, "inline": True},
        {"name": "Filed", "value": b.filing_date, "inline": True},
        {
            "name": "Filing",
            "value": f"[{b.accession}]({_filing_url(cik, b.accession_no_dashes)})",
            "inline": False,
        },
    ]
    return AlertEvent(
        dedup_key=f"insider_single:{ticker}:{b.accession_no_dashes}",
        level=level,
        title=f"{ticker} — {b.role} buy {_fmt_usd(b.total_value)}",
        fields=fields,
        footer_text="SEC Form 4 — single open-market purchase above threshold",
        ttl_days=14,
    )


def _filing_url(cik: int, accession_no_dashes: str) -> str:
    # Filing index page lists all documents (raw XML + XSL-rendered HTML view).
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/"


def _fmt_usd(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"
