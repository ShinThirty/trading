from fastmcp import Context, FastMCP
from trading_clients.endpoints import finnhub as fh
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.helpers import _finnhub

mcp = FastMCP("finnhub-tools")


@mcp.tool()
async def get_company_news(
    ctx: Context, symbol: str, from_date: str, to_date: str, limit: int = 20
) -> str:
    """Get recent news articles for a specific company.

    symbol: ticker symbol (e.g. 'AAPL').
    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (
        await _finnhub(ctx).get(fh.COMPANY_NEWS, fh.CompanyNewsRequest(symbol, from_date, to_date))
    ).to_output()


@mcp.tool()
async def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.MARKET_NEWS, fh.MarketNewsRequest(category))).to_output()


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
async def get_basic_financials(ctx: Context, symbol: str) -> str:
    """Get key financial metrics: P/E, P/B, EPS, dividend yield, 52-week high/low,
    market cap, beta, ROE, debt/equity.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = await _finnhub(ctx).get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol))
    return resp.to_output()


@mcp.tool()
async def get_eps_estimates(ctx: Context, symbol: str) -> str:
    """Get analyst EPS estimates for upcoming quarters and years: average, high, low,
    number of analysts, year-ago EPS, and growth rate.

    Periods: current quarter (0q), next quarter (+1q), current year (0y), next year (+1y).

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_mcp.tools.yahoo import _yfc

    data = await _yfc().earnings_estimate(symbol)
    if not data:
        return f"(no EPS estimates for {symbol})"
    rows = [
        {
            "Period": d["period"],
            "# Analysts": str(int(d.get("numberOfAnalysts", 0))),
            "Avg": fmt_number(d.get("avg")),
            "Low": fmt_number(d.get("low")),
            "High": fmt_number(d.get("high")),
            "Year Ago": fmt_number(d.get("yearAgoEps")),
            "Growth": fmt_number(d.get("growth")),
        }
        for d in data
    ]
    return list_table(rows)


@mcp.tool()
async def get_recommendation_trends(ctx: Context, symbol: str) -> str:
    """Get analyst recommendation trends: counts of strong buy, buy, hold, sell, and
    strong sell ratings by month.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.RECOMMENDATIONS, fh.SymbolRequest(symbol))).to_output()


@mcp.tool()
async def get_price_target(ctx: Context, symbol: str) -> str:
    """Get analyst consensus price target: current price, high, low, mean, and median
    target prices.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_mcp.tools.yahoo import _yfc

    data = await _yfc().analyst_price_targets(symbol)
    if not data:
        return f"(no price targets for {symbol})"
    return kv_table(
        {
            "Current": fmt_number(data.get("current")),
            "Target Low": fmt_number(data.get("low")),
            "Target Mean": fmt_number(data.get("mean")),
            "Target Median": fmt_number(data.get("median")),
            "Target High": fmt_number(data.get("high")),
        }
    )


@mcp.tool()
async def get_insider_transactions(ctx: Context, symbol: str, limit: int = 20) -> str:
    """Get recent insider transactions: buys, sells, and grants by company officers
    and directors.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: max number of transactions to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = await _finnhub(ctx).get(fh.INSIDER_TRANSACTIONS, fh.SymbolRequest(symbol))
    resp.transactions = resp.transactions[:limit]
    return resp.to_output()


@mcp.tool()
async def get_company_peers(ctx: Context, symbol: str) -> str:
    """Get a list of peer/competitor symbols for a company.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.PEERS, fh.SymbolRequest(symbol))).to_output()
