"""China A-share quotes, history, fundamentals, fund flow, Stock Connect (via AKShare)."""

from typing import Any

import akshare as ak
from fastmcp import Context, FastMCP
from trading_clients.cache import TTLCache
from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table

from trading_mcp.helpers import _cached

mcp = FastMCP("cn-market-tools")

_cache = TTLCache()

_TTL_QUOTE = 60
_TTL_HISTORY = 300
_TTL_FUNDAMENTALS = 3600

_FINANCIAL_ROWS = [
    "归母净利润",
    "营业总收入",
    "营业成本",
    "基本每股收益",
    "每股净资产",
    "净资产收益率(ROE)",
    "总资产报酬率(ROA)",
    "毛利率",
    "销售净利率",
    "资产负债率",
    "经营现金流量净额",
    "每股现金流",
    "营业总收入增长率",
    "归属母公司净利润增长率",
    "流动比率",
    "速动比率",
]

_LARGE_VALUE_ROWS = {"归母净利润", "营业总收入", "营业成本", "经营现金流量净额"}


def _sina_symbol(symbol: str) -> str:
    if symbol.startswith("6"):
        return f"sh{symbol}"
    return f"sz{symbol}"


class _ak:
    @staticmethod
    async def history(
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        adjust: str = "qfq",
    ) -> list[dict]:
        def _uncached() -> list[dict]:
            kwargs: dict[str, Any] = {
                "symbol": _sina_symbol(symbol),
                "adjust": adjust,
            }
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            df = ak.stock_zh_a_daily(**kwargs)
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(
            _cache,
            f"cn_hist:{symbol}:{start_date}:{end_date}:{adjust}",
            _TTL_HISTORY,
            _uncached,
        )

    @staticmethod
    async def company_info(symbol: str) -> list[dict]:
        def _uncached() -> list[dict]:
            df = ak.stock_individual_info_em(symbol=symbol)
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(_cache, f"cn_info:{symbol}", _TTL_FUNDAMENTALS, _uncached)

    @staticmethod
    async def financial_abstract(symbol: str) -> list[dict]:
        def _uncached() -> list[dict]:
            df = ak.stock_financial_abstract(symbol=symbol)
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(_cache, f"cn_fin:{symbol}", _TTL_FUNDAMENTALS, _uncached)

    @staticmethod
    async def fund_flow(symbol: str, market: str) -> list[dict]:
        def _uncached() -> list[dict]:
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(_cache, f"cn_flow:{symbol}:{market}", _TTL_QUOTE, _uncached)

    @staticmethod
    async def stock_connect_summary() -> list[dict]:
        def _uncached() -> list[dict]:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(_cache, "cn_connect_summary", _TTL_QUOTE, _uncached)


@mcp.tool()
async def get_cn_quote(ctx: Context, symbol: str) -> str:
    """Get a real-time quote for a China A-share stock.

    Returns: last price, open, high, low, close, volume, turnover, change %.

    symbol: 6-digit A-share code (e.g. '600519' for Kweichow Moutai,
      '000858' for Wuliangye, '300750' for CATL).

    Uses AKShare (free, no API key required). Data from East Money.
    """
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    rows = await _ak.history(symbol, start_date=start, end_date=end)
    if not rows:
        return f"(no quote data for {symbol})"
    latest = rows[-1]
    result = {
        "日期": str(latest.get("date", "")),
        "代码": symbol,
        "开盘": fmt_number(latest.get("open")),
        "最高": fmt_number(latest.get("high")),
        "最低": fmt_number(latest.get("low")),
        "收盘": fmt_number(latest.get("close")),
        "成交量": fmt_large(latest.get("volume")),
        "成交额": fmt_large(latest.get("amount")),
        "换手率": fmt_number(latest.get("turnover")),
    }
    return kv_table(result)


@mcp.tool()
async def get_cn_history(
    ctx: Context,
    symbol: str,
    start_date: str = "",
    end_date: str = "",
    adjust: str = "qfq",
    limit: int = 30,
) -> str:
    """Get historical daily price data for a China A-share stock.

    symbol: 6-digit A-share code (e.g. '600519').
    start_date: start date as YYYYMMDD (e.g. '20260101'). Omit for all history.
    end_date: end date as YYYYMMDD. Omit for latest.
    adjust: 'qfq' (forward-adjusted, default), 'hfq' (backward-adjusted),
      or '' (unadjusted).
    limit: max rows to return, most recent first (default 30).

    Uses AKShare (free, no API key required). Data from Sina Finance.
    """
    rows = await _ak.history(symbol, start_date, end_date, adjust)
    if not rows:
        return f"(no history for {symbol})"
    rows = rows[-limit:]
    table_rows = [
        {
            "日期": str(r.get("date", "")),
            "开盘": fmt_number(r.get("open")),
            "最高": fmt_number(r.get("high")),
            "最低": fmt_number(r.get("low")),
            "收盘": fmt_number(r.get("close")),
            "成交量": fmt_large(r.get("volume")),
            "成交额": fmt_large(r.get("amount")),
        }
        for r in rows
    ]
    return list_table(table_rows)


@mcp.tool()
async def get_cn_company_info(ctx: Context, symbol: str) -> str:
    """Get basic company profile for a China A-share stock.

    Returns: stock code, name, industry, listing date, total shares, float shares,
    total market cap, float market cap.

    symbol: 6-digit A-share code (e.g. '600519').

    Uses AKShare (free, no API key required). Data from East Money.
    """
    rows = await _ak.company_info(symbol)
    if not rows:
        return f"(no company info for {symbol})"
    large_fields = {"总市值", "流通市值", "总股本", "流通股"}
    result: dict[str, str] = {}
    for r in rows:
        item = str(r.get("item", ""))
        val = r.get("value")
        if item in large_fields:
            result[item] = fmt_large(val)
        else:
            result[item] = str(val)
    return kv_table(result)


@mcp.tool()
async def get_cn_financials(ctx: Context, symbol: str, periods: int = 4) -> str:
    """Get key financial metrics for a China A-share stock across recent quarters.

    Returns a table of quarterly financials: revenue, net income, EPS, ROE, ROA,
    gross margin, net margin, debt ratio, cash flow, growth rates.

    symbol: 6-digit A-share code (e.g. '600519').
    periods: number of recent quarters to show (default 4, max 8).

    Uses AKShare (free, no API key required). Data from East Money.
    """
    rows = await _ak.financial_abstract(symbol)
    if not rows:
        return f"(no financial data for {symbol})"

    periods = min(periods, 8)
    target_rows = {r["指标"]: r for r in rows if r["指标"] in _FINANCIAL_ROWS}

    all_cols = list(rows[0].keys())
    date_cols = [c for c in all_cols if c not in ("选项", "指标") and len(c) == 8]
    date_cols = date_cols[:periods]

    if not date_cols:
        return f"(no quarterly data for {symbol})"

    table_rows: list[dict] = []
    for label in _FINANCIAL_ROWS:
        r = target_rows.get(label)
        if r is None:
            continue
        row_data: dict[str, str] = {"指标": label}
        for dc in date_cols:
            val = r.get(dc)
            if label in _LARGE_VALUE_ROWS:
                row_data[dc] = fmt_large(val)
            elif val is not None:
                row_data[dc] = fmt_number(val)
            else:
                row_data[dc] = ""
        table_rows.append(row_data)

    return list_table(table_rows)


@mcp.tool()
async def get_cn_fund_flow(ctx: Context, symbol: str, market: str = "", limit: int = 10) -> str:
    """Get capital (money) flow data for a China A-share stock.

    Shows net inflow/outflow by investor size: super-large orders, large orders,
    medium orders, and small orders. Useful for gauging institutional vs retail activity.

    symbol: 6-digit A-share code (e.g. '600519').
    market: 'sh' for Shanghai, 'sz' for Shenzhen. If omitted, inferred from symbol
      (6xxxxx = sh, 0xxxxx/3xxxxx = sz).
    limit: number of recent trading days to show (default 10).

    Uses AKShare (free, no API key required). Data from East Money.
    """
    if not market:
        market = "sh" if symbol.startswith("6") else "sz"
    rows = await _ak.fund_flow(symbol, market)
    if not rows:
        return f"(no fund flow data for {symbol})"
    rows = rows[-limit:]
    table_rows = [
        {
            "日期": str(r.get("日期", ""))[:10],
            "收盘价": fmt_number(r.get("收盘价")),
            "涨跌幅%": fmt_number(r.get("涨跌幅")),
            "主力净流入": fmt_large(r.get("主力净流入-净额")),
            "主力占比%": fmt_number(r.get("主力净流入-净占比")),
            "超大单净流入": fmt_large(r.get("超大单净流入-净额")),
            "大单净流入": fmt_large(r.get("大单净流入-净额")),
            "小单净流入": fmt_large(r.get("小单净流入-净额")),
        }
        for r in rows
    ]
    return list_table(table_rows)


@mcp.tool()
async def get_cn_stock_connect(ctx: Context) -> str:
    """Get latest Stock Connect (沪深港通) fund flow summary.

    Shows northbound (foreign into A-shares) and southbound (mainland into HK)
    net buy amounts, fund flow, and related index performance for today.

    Uses AKShare (free, no API key required). Data from East Money.
    """
    rows = await _ak.stock_connect_summary()
    if not rows:
        return "(no Stock Connect data available)"
    table_rows = [
        {
            "交易日": str(r.get("交易日", ""))[:10],
            "类型": str(r.get("类型", "")),
            "板块": str(r.get("板块", "")),
            "资金方向": str(r.get("资金方向", "")),
            "成交净买额(亿)": fmt_number(r.get("成交净买额")),
            "资金净流入(亿)": fmt_number(r.get("资金净流入")),
            "相关指数": str(r.get("相关指数", "")),
            "指数涨跌幅%": fmt_number(r.get("指数涨跌幅")),
        }
        for r in rows
    ]
    return list_table(table_rows)
