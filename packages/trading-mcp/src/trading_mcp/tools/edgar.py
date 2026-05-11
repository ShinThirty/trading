"""Generic SEC EDGAR primitives: filings index + filing-content fetcher.

These two tools cover everything a public company files (8-K, 10-Q, 10-K, 13D,
Form 4, S-3, DEF 14A, 20-F, 6-K, …). Earnings-specific helpers live in
tools/earnings.py and compose these primitives.
"""

from collections import defaultdict
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _edgar, _exc_summary

mcp = FastMCP("edgar-tools")


def _fmt_items(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


@mcp.tool()
async def get_recent_filings(
    ctx: Context,
    symbol: str,
    days: int = 30,
    forms: list[str] | None = None,
) -> str:
    """List recent SEC filings for a ticker, grouped by signal-severity tier.

    Source: SEC EDGAR submissions feed. Covers all forms (8-K, 10-Q, 10-K, 13D,
    Form 4, S-3, DEF 14A, 20-F, 6-K, etc.). 8-K Item codes are pre-extracted so
    you can spot material events (5.02 executive change, 4.02 restatement, 1.01
    material agreement, …) without a second fetch.

    Pair with get_filing_content(symbol, accession_number, document) to read the
    actual text of any filing surfaced here.

    symbol: ticker symbol (e.g. 'NVDA'). Case-insensitive.
    days: lookback window in calendar days (default 30).
    forms: optional list of form codes to include (e.g. ['8-K', '10-Q']). If
        None, all forms within the window are returned.

    Tiers (ordered by signal severity):
      MATERIAL — 8-K with items {1.01, 1.02, 2.01, 2.05, 2.06, 4.01, 4.02, 5.02,
                 7.01, 8.01}; SC 13D activist filings; NT late-filings.
      EARNINGS — 8-K Item 2.02; 10-Q; 10-K; 20-F.
      INTERIM  — 6-K (foreign issuer interim disclosure — variable content).
      INSIDER  — Form 4 (officer/director/10%+ holder transactions).
      GOVERNANCE — DEF 14A and amendments.
      CAPITAL — S-1/S-3/S-4 shelf and equity raises.
      ROUTINE — everything else (S-8, Form 3/5, Form 144, SC 13G, prospectus
                supplements, etc.).
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
    except Exception as ex:
        return f"⚠ {_exc_summary(f'EDGAR submissions for CIK {cik}', ex)}"

    today = date.today().isoformat()
    window = subs.within_window(today, days)
    if forms:
        wanted = {f.upper() for f in forms}
        window = [f for f in window if f.form.upper() in wanted]

    if not window:
        scope = f" (forms={forms})" if forms else ""
        return f"No SEC filings for {ticker} in the last {days} days{scope}"

    grouped: dict[str, list[e.Filing]] = defaultdict(list)
    for filing in window:
        grouped[filing.tier].append(filing)

    sections: list[str] = []
    sections.append(f"# {ticker} recent SEC filings (last {days} days)")
    sections.append(
        f"CIK {cik:010d} · {len(window)} filings across {len(grouped)} tier(s)"
    )

    for tier in e.TIER_ORDER:
        rows_data = grouped.get(tier)
        if not rows_data:
            continue
        rows = [
            [
                f.filing_date,
                f.form,
                _fmt_items(f.items),
                f.primary_document or "—",
                f.accession_number,
            ]
            for f in rows_data
        ]
        sections.append(f"\n## {tier} ({len(rows_data)})")
        sections.append(
            md_table(["Date", "Form", "Items", "Primary Doc", "Accession #"], rows)
        )

    return "\n".join(sections)


_DEFAULT_MAX_CHARS = 100_000


@mcp.tool()
async def get_filing_content(
    ctx: Context,
    symbol: str,
    accession_number: str,
    document: str,
    max_chars: int = _DEFAULT_MAX_CHARS,
    offset: int = 0,
) -> str:
    """Fetch and parse the text of a specific document inside an SEC filing.

    Use after get_recent_filings to read the actual contents of any filing.
    Strips HTML/scripts/styles and returns clean text.

    symbol: ticker symbol (used to resolve CIK).
    accession_number: with or without dashes (e.g. '0000320193-26-000011').
    document: filename to fetch — use the 'Primary Doc' shown in
        get_recent_filings output, or any exhibit name from the filing index
        (e.g. 'ex99-1.htm' for a press release attachment).
    max_chars: cap on returned text (default 100k chars ≈ 25k tokens). 8-K
        press releases easily fit; 10-Q/10-K primary docs are typically
        300k-1M chars and will be truncated. Re-call with a larger
        max_chars or a non-zero offset to read further.
    offset: number of chars to skip from the start. Useful for paging through
        long 10-Q/10-K filings — the first ~15-20k chars of these are
        inline-XBRL tag soup, so offset=20000 gets you straight to the
        narrative.

    For multi-document filings (8-K with exhibits, 10-K with segments) you may
    need separate calls — start with the primary document, then drill into
    exhibits if relevant.
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()
    accession_no_dashes = accession_number.replace("-", "")

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, accession_no_dashes, document),
        )
    except Exception as ex:
        return (
            f"⚠ Failed to fetch {document} from accession {accession_number}: "
            f"{_exc_summary('EDGAR filing doc', ex)}"
        )

    full_text = doc.text or ""
    total = len(full_text)
    start = max(0, min(offset, total))
    end = min(total, start + max(0, max_chars))
    body = full_text[start:end] or "(no content)"

    notes: list[str] = []
    if start > 0:
        notes.append(f"skipped first {start:,} chars (offset)")
    if end < total:
        notes.append(
            f"truncated at {end:,}/{total:,} chars; re-call with "
            f"offset={end} to continue"
        )
    note_line = f"Note: {'; '.join(notes)}\n" if notes else ""

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"
    return (
        f"# {ticker} filing content — {document}\n"
        f"Accession: {accession_number}\n"
        f"Source: {url}\n"
        f"{note_line}\n"
        f"{body}"
    )
