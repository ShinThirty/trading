import yfinance as yf
from fastmcp import Context, FastMCP
from trading_clients.cache import TTLCache
from trading_clients.endpoints.yahoo import ScreenerResponse
from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table
from yfinance import EquityQuery
from yfinance import screen as _screen

from trading_mcp.helpers import _cached

mcp = FastMCP("yahoo-tools")

_cache = TTLCache()

_TTL_FUNDAMENTALS = 3600
_TTL_SCREENER = 300


class _yfc:
    """Namespace for Yahoo Finance async helpers used by other tool modules."""

    @staticmethod
    async def predefined_screen(screen_id: str, count: int = 25) -> dict:
        return await _cached(
            _cache, f"screen:{screen_id}:{count}", _TTL_SCREENER, _screen, screen_id, count=count
        )

    @staticmethod
    async def custom_screen(
        criteria: list[dict],
        sort_field: str = "intradaymarketcap",
        sort_asc: bool = False,
        size: int = 25,
    ) -> dict:
        operands: list = [
            EquityQuery("eq", ["region", "us"]),  # ty: ignore[invalid-argument-type]
        ]
        for c in criteria:
            op, field, val = c["op"], c["field"], c["value"]
            if op == "btwn":
                operands.append(EquityQuery("btwn", [field, val[0], val[1]]))
            elif op == "is-in":
                operands.append(EquityQuery("is-in", [field, val]))
            else:
                operands.append(EquityQuery(op, [field, val]))
        query = EquityQuery("and", operands)  # type: ignore[arg-type]

        key = f"custom_screen:{sort_field}:{sort_asc}:{size}:" + str(criteria)
        return await _cached(
            _cache,
            key,
            _TTL_SCREENER,
            _screen,
            query,
            sortField=sort_field,
            sortAsc=sort_asc,
            size=size,
        )

    @staticmethod
    async def institutional_holders(symbol: str) -> list[dict]:
        def _uncached(s: str) -> list[dict]:
            df = yf.Ticker(s).institutional_holders
            if df is None or df.empty:
                return []
            return [row.to_dict() for _, row in df.iterrows()]

        return await _cached(_cache, f"holders:{symbol}", _TTL_SCREENER, _uncached, symbol)

    @staticmethod
    async def short_interest(symbol: str) -> dict:
        def _uncached(s: str) -> dict:
            info = yf.Ticker(s).info or {}
            return {
                "sharesShort": info.get("sharesShort"),
                "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
                "shortRatio": info.get("shortRatio"),
                "shortPercentOfFloat": info.get("shortPercentOfFloat"),
            }

        return await _cached(_cache, f"short:{symbol}", _TTL_SCREENER, _uncached, symbol)

    @staticmethod
    async def earnings_estimate(symbol: str) -> list[dict]:
        def _uncached(s: str) -> list[dict]:
            df = yf.Ticker(s).get_earnings_estimate()
            if df is None or df.empty:
                return []
            rows = []
            for period, row in df.iterrows():
                r = row.to_dict()
                r["period"] = str(period)
                rows.append(r)
            return rows

        return await _cached(_cache, f"eps_est:{symbol}", _TTL_FUNDAMENTALS, _uncached, symbol)

    @staticmethod
    async def income_statement(
        symbol: str, period: str = "quarterly", limit: int = 4
    ) -> list[dict]:
        def _uncached(s: str, p: str, lim: int) -> list[dict]:
            t = yf.Ticker(s)
            df = t.quarterly_income_stmt if p == "quarterly" else t.income_stmt
            if df is None or df.empty:
                return []

            def _get(label: str) -> float | None:
                return float(df.loc[label, col]) if label in df.index else None

            rows = []
            for col in df.columns[:lim]:
                rows.append(
                    {
                        "period": col.strftime("%Y-%m-%d"),
                        "revenue": _get("Total Revenue"),
                        "cost_of_revenue": _get("Cost Of Revenue"),
                        "gross_profit": _get("Gross Profit"),
                        "operating_income": _get("Operating Income"),
                        "net_income": _get("Net Income"),
                        "eps": _get("Basic EPS"),
                    }
                )
            return rows

        return await _cached(
            _cache,
            f"income:{symbol}:{period}:{limit}",
            _TTL_FUNDAMENTALS,
            _uncached,
            symbol,
            period,
            limit,
        )

    @staticmethod
    async def analyst_price_targets(symbol: str) -> dict:
        def _uncached(s: str) -> dict:
            return yf.Ticker(s).get_analyst_price_targets() or {}

        return await _cached(_cache, f"targets:{symbol}", _TTL_FUNDAMENTALS, _uncached, symbol)


# ── MCP Tools ──────────────────────────────────────────────


@mcp.tool()
async def screen_stocks(
    ctx: Context,
    criteria: list[dict],
    sort_field: str = "intradaymarketcap",
    sort_dir: str = "DESC",
    limit: int = 25,
) -> str:
    """Screen for US stocks matching specific criteria.

    criteria: list of filter dicts, each with:
      - field: the data field to filter on
      - op: comparison operator ('gt', 'lt', 'gte', 'lte', 'eq', 'btwn', 'is-in')
      - value: comparison value (number for numeric, string for categorical).
        For 'btwn', use [min, max]. For 'is-in', use a list of values.

    Available fields:
      Market: intradaymarketcap, intradayprice, avgdailyvol3m, beta, percentchange
      Valuation: peratio.lasttwelvemonths, pricebookratio.quarterly, pegratio_5y
      Dividends: forward_dividend_yield, forward_dividend_per_share
      Growth: epsgrowth.lasttwelvemonths, quarterlyrevenuegrowth.quarterly
      Profitability: returnonequity.lasttwelvemonths, returnonassets.lasttwelvemonths,
        currentratio.lasttwelvemonths
      Categorical: sector, exchange (use 'eq' or 'is-in')
      Short Interest: days_to_cover_short.value, short_percentage_of_float.value

    Sectors: 'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
      'Communication Services', 'Industrials', 'Consumer Defensive', 'Energy',
      'Basic Materials', 'Real Estate', 'Utilities'

    sort_field: field to sort by (default 'intradaymarketcap').
    sort_dir: 'DESC' or 'ASC'.
    limit: max results to return (default 25, max 250).

    Example: large-cap tech with low P/E:
      criteria=[
        {"field": "intradaymarketcap", "op": "gt", "value": 50000000000},
        {"field": "sector", "op": "eq", "value": "Technology"},
        {"field": "peratio.lasttwelvemonths", "op": "lt", "value": 25}
      ]

    Uses Yahoo Finance via yfinance (no API key required). Data is 15-minute delayed.
    """
    ascending = sort_dir == "ASC"
    result = await _yfc.custom_screen(criteria, sort_field, ascending, limit)
    return ScreenerResponse.from_response(result).to_output()


@mcp.tool()
async def get_predefined_screen(ctx: Context, screen_id: str, count: int = 25) -> str:
    """Get a predefined stock screen from Yahoo Finance.

    screen_id: one of:
      - 'most_actives' — highest volume today
      - 'day_gainers' — biggest percentage gainers today
      - 'day_losers' — biggest percentage losers today
      - 'aggressive_small_caps' — high-growth small caps
      - 'growth_technology_stocks' — growing tech stocks
      - 'most_shorted_stocks' — highest short interest
      - 'undervalued_large_caps' — large caps trading below intrinsic value
      - 'undervalued_growth_stocks' — growth stocks at low valuations
      - 'small_cap_gainers' — small cap stocks gaining today
    count: number of results to return (default 25).

    Uses Yahoo Finance via yfinance (no API key required). Data is 15-minute delayed.
    """
    result = await _yfc.predefined_screen(screen_id, count)
    return ScreenerResponse.from_response(result).to_output()


@mcp.tool()
async def get_institutional_ownership(ctx: Context, symbol: str) -> str:
    """Get top institutional holders of a stock: holder name, shares held, percentage
    held, position value, and recent change.

    Shows who the biggest institutional investors are (Vanguard, BlackRock, etc.)
    and whether they're accumulating or reducing positions.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    holders = await _yfc.institutional_holders(symbol)
    if not holders:
        return f"(no institutional ownership data for {symbol})"
    rows = [
        {
            "Holder": h.get("Holder", ""),
            "Shares": fmt_large(h.get("Shares")),
            "% Held": fmt_number(h.get("pctHeld", 0) * 100),
            "Value": fmt_large(h.get("Value")),
            "Change": fmt_number(h.get("pctChange", 0) * 100),
            "Date": str(h.get("Date Reported", ""))[:10],
        }
        for h in holders
    ]
    return list_table(rows)


@mcp.tool()
async def get_short_interest(ctx: Context, symbol: str) -> str:
    """Get short interest data for a stock: shares short, short ratio (days to cover),
    short % of float, and month-over-month change.

    Useful for gauging squeeze risk on CSP positions and identifying heavily shorted names.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    data = await _yfc.short_interest(symbol)
    if not any(data.values()):
        return f"(no short interest data for {symbol})"
    result: dict[str, str] = {}
    if data["sharesShort"] is not None:
        result["Shares Short"] = fmt_large(data["sharesShort"])
    if data["sharesShortPriorMonth"] is not None:
        result["Shares Short (Prior Month)"] = fmt_large(data["sharesShortPriorMonth"])
    if data["shortRatio"] is not None:
        result["Short Ratio (Days to Cover)"] = fmt_number(data["shortRatio"])
    if data["shortPercentOfFloat"] is not None:
        result["Short % of Float"] = fmt_number(data["shortPercentOfFloat"] * 100) + "%"
    return kv_table(result)
