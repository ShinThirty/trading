"""Earnings text artifacts: call transcripts and press releases.

Sources:
  - get_earnings_transcript: scraped from Motley Fool via monthly sitemap discovery.
  - get_earnings_release: SEC EDGAR 8-K Exhibit 99.x (Item 2.02 filings).
"""

from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e
from trading_clients.endpoints import fool as f

from trading_mcp.helpers import _edgar, _exc_summary, _fool

mcp = FastMCP("earnings-tools")


def _month_offsets(today: date, n: int) -> list[tuple[int, int]]:
    """Return [(year, month)] for current and n preceding months."""
    out: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


@mcp.tool()
async def get_earnings_transcript(ctx: Context, symbol: str) -> str:
    """Fetch the most recent earnings call transcript for a ticker.

    Source: Motley Fool (scraped via their public monthly sitemap, then the
    transcript page). Includes prepared remarks and Q&A. Free, no config.

    symbol: ticker symbol (e.g. 'AAPL'). Case-insensitive.

    Returns the transcript text, or a message if none was found in the last 3 months.
    Edge case: 0–2 days post-earnings before Fool publishes, this may return the prior
    quarter's transcript — check the date in the returned content.
    """
    fool = _fool(ctx)
    ticker = symbol.upper()
    last_seen_path: str | None = None

    sitemap_errors: list[str] = []
    for year, month in _month_offsets(date.today(), 3):
        try:
            sitemap = await fool.get(f.MONTHLY_SITEMAP, f.MonthlySitemapRequest(year, month))
        except Exception as ex:
            sitemap_errors.append(_exc_summary(f"Fool sitemap {year}-{month:02d}", ex))
            continue
        path = sitemap.find_latest_transcript(ticker)
        if path:
            last_seen_path = path
            break

    if not last_seen_path:
        if sitemap_errors:
            errs = "\n  • ".join(sitemap_errors)
            return (
                f"⚠ Could not discover transcript URL for {ticker}. Sitemap fetch errors:\n"
                f"  • {errs}"
            )
        return f"No earnings transcript found for {ticker} in the last 3 months on fool.com"

    try:
        transcript = await fool.get(f.TRANSCRIPT_PAGE, f.TranscriptPageRequest(last_seen_path))
    except Exception as ex:
        return (
            f"⚠ Found transcript URL but page fetch failed: "
            f"{_exc_summary('Fool transcript page', ex)}\n"
            f"Discovered URL: https://www.fool.com{last_seen_path}"
        )

    return (
        f"# {ticker} earnings call transcript\n"
        f"Source: https://www.fool.com{last_seen_path}\n\n"
        f"{transcript.to_output()}"
    )


@mcp.tool()
async def get_earnings_release(ctx: Context, symbol: str) -> str:
    """Fetch the most recent earnings press release (8-K Exhibit 99.x) for a ticker.

    Source: SEC EDGAR. Resolves ticker → CIK, finds the most recent 8-K with Item 2.02
    (Results of Operations and Financial Condition), and extracts the press-release exhibit.
    Press releases typically include reported financials, segment breakdowns, and guidance.

    symbol: ticker symbol (e.g. 'AAPL'). Case-insensitive.

    Optional [edgar] section in ~/.tradingrc with user_agent if you hit SEC rate-limits.
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        # Ticker missing from EDGAR map — this message is already self-explanatory.
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
    except Exception as ex:
        return f"⚠ {_exc_summary(f'EDGAR submissions for CIK {cik}', ex)}"

    filing = subs.find_latest_earnings_8k()
    if not filing:
        return f"No recent 8-K with Item 2.02 (Results of Operations) for {ticker}"

    try:
        index = await edgar.get(
            e.FILING_INDEX, e.FilingIndexRequest(cik, filing.accession_no_dashes)
        )
    except Exception as ex:
        return (
            f"⚠ Found 8-K {filing.accession_number} ({filing.filing_date}) but "
            f"filing index fetch failed: {_exc_summary('EDGAR filing index', ex)}"
        )

    filename = index.find_press_release()
    if not filename:
        return (
            f"8-K {filing.accession_number} ({filing.filing_date}) for {ticker} "
            f"has no Exhibit 99.x press release"
        )

    try:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, filing.accession_no_dashes, filename),
        )
    except Exception as ex:
        return (
            f"⚠ Found press release exhibit {filename} but doc fetch failed: "
            f"{_exc_summary('EDGAR filing doc', ex)}"
        )

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing.accession_no_dashes}/{filename}"
    return (
        f"# {ticker} earnings press release ({filing.filing_date})\n"
        f"8-K accession: {filing.accession_number}\n"
        f"Source: {url}\n\n{doc.to_output()}"
    )
