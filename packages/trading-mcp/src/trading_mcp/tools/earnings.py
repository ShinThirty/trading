"""Earnings text artifacts: call transcripts and press releases.

Sources:
  - get_earnings_transcript: walks the PROVIDERS registry from
    transcript_providers.py in preference order (Motley Fool → Morningstar →
    future sources). Returns the first hit.
  - get_earnings_release: SEC EDGAR 8-K Exhibit 99.x (Item 2.02 filings).
"""

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e

from trading_mcp.helpers import _edgar, _exc_summary
from trading_mcp.timeouts import timeout
from trading_mcp.tools.transcript_providers import PROVIDERS

mcp = FastMCP("earnings-tools")


@mcp.tool(meta=timeout(180))
async def get_earnings_transcript(ctx: Context, symbol: str) -> str:
    """Fetch the most recent earnings call transcript for a ticker.

    Walks providers in preference order (Motley Fool → Morningstar → future
    sources). Returns the first hit. If none has it, returns a message
    describing what each provider tried.

    symbol: ticker symbol (e.g. 'AAPL'). Case-insensitive.

    Edge case: 0–2 days post-earnings before any source publishes, the most
    recent transcript may be the prior quarter's — check the date in the
    returned content.
    """
    ticker = symbol.upper()

    attempted: list[tuple[str, list[str]]] = []
    for provider in PROVIDERS:
        result = await provider(ctx, ticker)
        if result.found:
            return (
                f"# {ticker} earnings call transcript\nSource: {result.source_url}\n\n{result.text}"
            )
        attempted.append((provider.name, result.errors))

    lines = [f"No earnings transcript found for {ticker}."]
    for name, errors in attempted:
        if errors:
            lines.append(f"{name}:")
            for err in errors:
                lines.append(f"  • {err}")
        else:
            lines.append(f"{name}: no transcript available")
    return "\n".join(lines)


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
