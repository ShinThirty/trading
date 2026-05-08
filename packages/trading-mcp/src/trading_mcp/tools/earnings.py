"""Earnings text artifacts: call transcripts and press releases.

Sources:
  - get_earnings_transcript: scraped from Motley Fool via monthly sitemap discovery.
  - get_earnings_release: SEC EDGAR 8-K Exhibit 99.x (Item 2.02 filings).
"""

from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e
from trading_clients.endpoints import fool as f

from trading_mcp.helpers import _edgar, _fool

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

    for year, month in _month_offsets(date.today(), 3):
        sitemap = await fool.get(f.MONTHLY_SITEMAP, f.MonthlySitemapRequest(year, month))
        path = sitemap.find_latest_transcript(ticker)
        if path:
            last_seen_path = path
            break

    if not last_seen_path:
        return f"No earnings transcript found for {ticker} in the last 3 months on fool.com"

    transcript = await fool.get(f.TRANSCRIPT_PAGE, f.TranscriptPageRequest(last_seen_path))
    return f"# {ticker} earnings call transcript\nSource: https://www.fool.com{last_seen_path}\n\n{transcript.to_output()}"


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

    cik = await edgar.lookup_cik(ticker)
    subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
    filing = subs.find_latest_earnings_8k()
    if not filing:
        return f"No recent 8-K with Item 2.02 (Results of Operations) for {ticker}"

    index = await edgar.get(
        e.FILING_INDEX, e.FilingIndexRequest(cik, filing.accession_no_dashes)
    )
    filename = index.find_press_release()
    if not filename:
        return (
            f"8-K {filing.accession_number} ({filing.filing_date}) for {ticker} "
            f"has no Exhibit 99.x press release"
        )

    doc = await edgar.get(
        e.FILING_DOC,
        e.FilingDocRequest(cik, filing.accession_no_dashes, filename),
    )
    url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik}/{filing.accession_no_dashes}/{filename}"
    )
    return (
        f"# {ticker} earnings press release ({filing.filing_date})\n"
        f"8-K accession: {filing.accession_number}\n"
        f"Source: {url}\n\n{doc.to_output()}"
    )
