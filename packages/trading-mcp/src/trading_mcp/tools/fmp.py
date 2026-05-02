import asyncio
from datetime import date, timedelta

from fastmcp import Context, FastMCP
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import fmp
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_large, fmt_number, list_table, to_float

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


@mcp.tool()
async def scan_informed_activity(
    ctx: Context,
    screen_count: int = 25,
    max_market_cap: float = 2e9,
    cluster_days: int = 30,
    min_insiders: int = 2,
) -> str:
    """Scan for small-cap stocks with clustered insider buying during
    high-volume/high-volatility periods.

    Based on Lakonishok (contrarian insider buying in small firms) and
    Kacperczyk & Pagnotta (informed trading in high volume/volatility).

    Flow: Yahoo screener finds active small caps → Finnhub checks each for
    insider purchase clusters → TastyTrade/Tradier enrich with IV and volume.

    Use get_option_chain on candidates to check OTM volume/OI as a final
    qualifier per the Kacperczyk & Pagnotta thesis.

    screen_count: number of small-cap candidates to screen (default 25).
    max_market_cap: market cap ceiling in dollars (default 2e9 = $2B).
    cluster_days: window in days for clustered buying (default 30).
    min_insiders: minimum distinct insiders buying in the window (default 2).

    Requires [finnhub] section in ~/.tradingrc.
    TastyTrade and Tradier are optional (used for IV and quote enrichment).
    """
    from trading_mcp.tools.yahoo import _yfc

    finnhub_client = _finnhub(ctx)

    result = await _yfc.custom_screen(
        criteria=[
            {"field": "intradaymarketcap", "op": "lt", "value": max_market_cap},
            {"field": "intradaymarketcap", "op": "gt", "value": 100_000_000},
            {"field": "avgdailyvol3m", "op": "gt", "value": 100_000},
        ],
        sort_field="percentchange",
        sort_asc=False,
        size=screen_count,
    )
    quotes = result.get("quotes", [])
    if not quotes:
        return "(no small-cap candidates from screener)"

    symbols = [q["symbol"] for q in quotes if q.get("symbol")]
    screen_data: dict[str, dict] = {q["symbol"]: q for q in quotes if q.get("symbol")}

    cutoff = (date.today() - timedelta(days=cluster_days)).isoformat()
    clustered: dict[str, list[dict]] = {}
    for sym in symbols:
        try:
            resp = await finnhub_client.get(fh.INSIDER_TRANSACTIONS, fh.SymbolRequest(sym))
        except Exception:
            continue
        purchases = [
            tx
            for tx in resp.transactions
            if tx.get("transactionCode") == "P"
            and (tx.get("transactionDate", "") >= cutoff)
            and (to_float(tx.get("change")) or 0) > 0
        ]
        if not purchases:
            continue
        unique_insiders = {tx.get("name", "") for tx in purchases}
        unique_insiders.discard("")
        if len(unique_insiders) >= min_insiders:
            clustered[sym] = purchases

    if not clustered:
        return (
            f"(no small-cap names with {min_insiders}+ insiders buying "
            f"within {cluster_days} days out of {len(symbols)} screened)"
        )

    hit_symbols = list(clustered.keys())
    tt_client = ctx.lifespan_context.get("tastytrade")
    tradier_client = ctx.lifespan_context.get("tradier")

    tasks: list = []
    task_labels: list[str] = []
    symbols_csv = ",".join(hit_symbols)

    if tt_client:
        tasks.append(tt_client.get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbols_csv)))
        task_labels.append("tt")
    if tradier_client:
        tasks.append(tradier_client.get(t.QUOTES, t.GetQuotesRequest(symbols_csv)))
        task_labels.append("tradier")

    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    tt_by_sym: dict[str, dict] = {}
    tradier_by_sym: dict[str, dict] = {}
    for i, label in enumerate(task_labels):
        r = results[i]
        if isinstance(r, BaseException):
            continue
        if label == "tt":
            for item in r.items:
                tt_by_sym[item.get("symbol", "")] = item
        elif label == "tradier":
            for q in r.quotes:
                tradier_by_sym[q.get("symbol", "")] = q

    scored: list[tuple[int, float, dict[str, str]]] = []
    for sym in hit_symbols:
        txns = clustered[sym]
        sq = screen_data.get(sym, {})
        tt_item = tt_by_sym.get(sym, {})
        tq = tradier_by_sym.get(sym, {})

        unique_buyers = {tx.get("name", "") for tx in txns}
        unique_buyers.discard("")
        n_insiders = len(unique_buyers)
        total_value = sum(
            (to_float(tx.get("change")) or 0) * (to_float(tx.get("transactionPrice")) or 0)
            for tx in txns
        )

        iv_rank_raw = to_float(tt_item.get("tw-implied-volatility-index-rank"))
        iv_rank = f"{iv_rank_raw * 100:.0f}%" if iv_rank_raw is not None else ""
        liq = str(tt_item.get("liquidity-rating", "")) if tt_item.get("liquidity-rating") else ""

        vol = to_float(tq.get("volume") or sq.get("regularMarketVolume"))
        avg_vol = to_float(tq.get("average_volume") or sq.get("averageDailyVolume3Month"))
        vol_ratio = ""
        if vol is not None and avg_vol and avg_vol > 0:
            vol_ratio = f"{vol / avg_vol:.1f}x"

        price = to_float(tq.get("last") or sq.get("regularMarketPrice"))
        chg_pct = to_float(tq.get("change_percentage") or sq.get("regularMarketChangePercent"))
        chg_str = f"{chg_pct:+.1f}%" if chg_pct is not None else ""
        mcap = to_float(sq.get("marketCap"))

        row = {
            "Symbol": sym,
            "Mkt Cap": fmt_large(mcap),
            "Sector": (sq.get("sector") or "")[:15],
            "Insiders": str(n_insiders),
            "Txns": str(len(txns)),
            "$ Bought": fmt_large(total_value),
            "Price": fmt_number(price),
            "Chg%": chg_str,
            "Vol/Avg": vol_ratio,
            "IV Rank": iv_rank,
            "Liq": liq,
        }
        scored.append((n_insiders, total_value, row))

    scored.sort(key=lambda c: (c[0], c[1]), reverse=True)
    rows = [c[2] for c in scored]

    header = (
        f"## Informed Activity Scanner\n"
        f"{len(rows)} hits from {len(symbols)} small-cap candidates "
        f"(<${max_market_cap / 1e9:.0f}B) "
        f"with {min_insiders}+ insiders buying within {cluster_days} days\n\n"
    )
    return header + list_table(rows)
