from fastmcp import Context, FastMCP
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import fmp
from trading_clients.endpoints import tastytrade as tt
from trading_clients.table_helpers import fmt_number, list_table

from trading_mcp.helpers import _finnhub, _fmp

mcp = FastMCP("fmp-tools")


@mcp.tool()
async def get_company_profile(ctx: Context, symbol: str) -> str:
    """Get company profile: name, price, market cap, beta, avg volume, last dividend,
    52-week range, sector, industry, exchange, and CEO.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] section in ~/.tradingrc.
    """
    return (await _fmp(ctx).get(fmp.PROFILE, fmp.SymbolRequest(symbol))).to_output()


@mcp.tool()
async def get_income_statement(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get income statement from SEC filings: revenue, cost of revenue, gross profit,
    operating income, net income, EPS.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc. Falls back to Yahoo Finance
    if Finnhub has no data for the symbol.
    """
    from trading_mcp.tools.yahoo import _yfc

    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    output = result.income_markdown(limit)
    if output != "(no data)":
        return output

    data = await _yfc().income_statement(symbol, freq, limit)
    if not data:
        return f"(no income statement data for {symbol})"

    def _fmt(v: float | None) -> str:
        if v is None:
            return ""
        if abs(v) >= 1e9:
            return f"{v / 1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"{v / 1e6:.1f}M"
        return fmt_number(v)

    rows = [
        {
            "Period": d["period"],
            "Revenue": _fmt(d["revenue"]),
            "Gross Profit": _fmt(d["gross_profit"]),
            "Operating Income": _fmt(d["operating_income"]),
            "Net Income": _fmt(d["net_income"]),
            "EPS": fmt_number(d["eps"]),
        }
        for d in data
    ]
    return f"(via Yahoo Finance)\n{list_table(rows)}"


@mcp.tool()
async def get_balance_sheet(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get balance sheet from SEC filings: cash, current assets, total assets,
    current liabilities, long-term debt, total liabilities, total equity.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    return result.balance_sheet_markdown(limit)


@mcp.tool()
async def get_cash_flow(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get cash flow statement from SEC filings: operating cash flow, capex,
    investing/financing cash flows, dividends, buybacks.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    return result.cash_flow_markdown(limit)


@mcp.tool()
async def get_key_metrics(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get key financial metrics: EV/EBITDA, ROE, ROA, current ratio, debt/equity, FCF yield.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    resp = await _fmp(ctx).get(fmp.KEY_METRICS, fmp.FinancialRequest(symbol, period, limit))
    return resp.to_output()


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
async def get_fmp_earnings_calendar(ctx: Context, symbol: str, limit: int = 5) -> str:
    """Get earnings history: date, EPS estimate/actual, revenue estimate/actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5).
    Requires [fmp] section in ~/.tradingrc.
    """
    return (await _fmp(ctx).get(fmp.EARNINGS, fmp.EarningsRequest(symbol, limit))).to_output()


@mcp.tool()
async def get_sector_performance(ctx: Context, date: str, exchange: str = "NYSE") -> str:
    """Get sector performance for a specific date: average percentage change for each
    of 11 sectors (Technology, Healthcare, Financial Services, etc.), sorted best to worst.

    Useful for understanding sector rotation and whether a stock's movement is
    stock-specific or sector-wide.

    date: trading date (YYYY-MM-DD). Use a recent trading day (not weekend/holiday).
    exchange: 'NYSE' (default) or 'NASDAQ'.

    Requires [fmp] section in ~/.tradingrc.
    """
    return (
        await _fmp(ctx).get(fmp.SECTOR_PERFORMANCE, fmp.SectorPerformanceRequest(date, exchange))
    ).to_output()
