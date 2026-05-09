"""Scheduled events: earnings, dividends, economic data releases."""

from datetime import date, timedelta

from fastmcp import Context, FastMCP
from trading_clients.endpoints import fed, fmp, fred
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import tastytrade as tt
from trading_clients.table_helpers import list_table

from trading_mcp.helpers import _fed, _finnhub, _fmp, _fred

mcp = FastMCP("calendar-tools")


@mcp.tool()
async def get_earnings_calendar(
    ctx: Context,
    from_date: str,
    to_date: str,
    symbol: str | None = None,
    limit: int = 50,
) -> str:
    """Get upcoming and recent earnings reports. Automatically filters out micro-caps.

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    symbol: optional ticker to filter for (e.g. 'TSLA'). Returns only that symbol's
      earnings entry when set.
    limit: max number of entries to return (default 50).

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = await _finnhub(ctx).get(fh.EARNINGS_CALENDAR, fh.DateRangeRequest(from_date, to_date))
    if symbol:
        resp.earnings = [e for e in resp.earnings if e.get("symbol", "").upper() == symbol.upper()]
    resp.earnings = resp.earnings[:limit]
    return resp.to_output()


@mcp.tool()
async def get_fmp_earnings_calendar(ctx: Context, symbol: str, limit: int = 5) -> str:
    """Get earnings history: date, EPS estimate/actual, revenue estimate/actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5).
    Requires [fmp] section in ~/.tradingrc.
    """
    return (await _fmp(ctx).get(fmp.EARNINGS, fmp.EarningsRequest(symbol, limit))).to_output()


@mcp.tool()
async def get_dividend_history(ctx: Context, symbol: str) -> str:
    """Get dividend payment history: ex-date, pay date, record date, amount.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] or [tastytrade] section in ~/.tradingrc.
    """
    fmp_client = ctx.lifespan_context.get("fmp")
    if fmp_client:
        try:
            resp = await fmp_client.get(fmp.DIVIDEND_HISTORY, fmp.SymbolRequest(symbol))
            return resp.to_output()
        except ValueError:
            pass
    tt_client = ctx.lifespan_context.get("tastytrade")
    if tt_client:
        resp = await tt_client.get(tt.DIVIDEND_HISTORY, tt.DividendHistoryRequest(symbol))
        return resp.to_output()
    raise RuntimeError(
        "No dividend data source available. Add [fmp] or [tastytrade] to ~/.tradingrc"
    )


@mcp.tool()
async def get_upcoming_economic_releases(ctx: Context, days_ahead: int = 14) -> str:
    """Get upcoming macro releases tagged by category: Labor (NFP, JOLTS, ADP,
    Jobless Claims), Inflation (CPI, PCE, PPI), Activity (Retail Sales, IP,
    Durable Goods), Housing (Starts, New Sales, Existing Sales), Trade, Growth (GDP),
    Policy (FOMC decision day).

    FOMC dates are sourced from fed.gov's calendar (decision day = day 2 of each
    two-day meeting). Daily noise (SOFR, Coinbase, etc.) is filtered out.

    days_ahead: forward window in days (default 14).
    Requires [fred] section in ~/.tradingrc.
    """
    today = date.today()
    today_iso = today.isoformat()
    end_iso = (today + timedelta(days=days_ahead)).isoformat()
    fred_client = _fred(ctx)
    rows: list[tuple[str, str, str]] = []
    for release_id, (category, name) in fred.MACRO_RELEASES.items():
        resp = await fred_client.get(
            fred.RELEASE_DATES,
            fred.GetReleaseDatesRequest(
                release_id=release_id,
                realtime_start=today_iso,
                realtime_end=end_iso,
            ),
        )
        for d in resp.dates:
            rows.append((d, category, name))
    fomc = await _fed(ctx).get(fed.FOMC_CALENDAR, fed.EmptyRequest())
    for d in fomc.meeting_dates:
        if today_iso <= d <= end_iso:
            rows.append((d, "Policy", "FOMC Decision"))
    if not rows:
        return "(no upcoming macro releases in window)"
    rows.sort(key=lambda r: (r[0], r[1]))
    return list_table([{"Date": d, "Category": cat, "Release": name} for d, cat, name in rows])
