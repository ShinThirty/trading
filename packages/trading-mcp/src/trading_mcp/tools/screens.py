"""Stock screens, watchlists, top movers, short-interest stats."""

from datetime import date, timedelta

import httpx
from fastmcp import Context, FastMCP
from trading_clients.cache import TTLCache
from trading_clients.endpoints import alphavantage as av
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints.yahoo import ScreenerResponse
from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table

from trading_mcp.helpers import _alphavantage, _tastytrade
from trading_mcp.yfinance_helper import _yfc

mcp = FastMCP("screens-tools")


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
async def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks.

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return (await _alphavantage(ctx).get(av.MOVERS, av.MoversRequest())).to_output()


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


@mcp.tool()
async def get_public_watchlists(ctx: Context) -> str:
    """List all TastyTrade curated watchlists with symbol counts.

    Includes sector lists, high IV rank names, liquid options, dividend aristocrats,
    earnings calendars, and more. Use get_public_watchlist to get the symbols in
    a specific list.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return (await _tastytrade(ctx).get(tt.PUBLIC_WATCHLISTS, tt.EmptyRequest())).to_output()


@mcp.tool()
async def get_public_watchlist(ctx: Context, name: str) -> str:
    """Get all symbols in a TastyTrade curated watchlist.

    name: watchlist name (e.g. 'tasty IVR', 'High Options Volume',
      '52 Week Near Low', 'A.I. Stocks', 'Dividend Aristocrats').
      Use get_public_watchlists to see available names.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return (await _tastytrade(ctx).get(tt.PUBLIC_WATCHLIST, tt.WatchlistRequest(name))).to_output()


# ── FINRA short volume ──────────────────────────────────────

_FINRA_BASE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
_finra_cache = TTLCache()
_FINRA_TTL = 86400 * 7


async def _fetch_finra_day(client: httpx.AsyncClient, d: date) -> list[dict]:
    key = f"finra:{d.isoformat()}"
    hit = _finra_cache.get(key, _FINRA_TTL)
    if hit is not None:
        return hit

    url = _FINRA_BASE_URL.format(date=d.strftime("%Y%m%d"))
    try:
        resp = await client.get(url)
        if resp.status_code == 403:
            return []
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    rows: list[dict] = []
    for line in resp.text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "date": parts[0],
                "symbol": parts[1],
                "short_volume": float(parts[2]),
                "short_exempt_volume": float(parts[3]),
                "total_volume": float(parts[4]),
            }
        )

    _finra_cache.put(key, rows)
    return rows


def _business_days(end: date, count: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return days


@mcp.tool()
async def get_short_volume(ctx: Context, symbol: str, days: int = 20) -> str:
    """Get daily short sale volume from FINRA for the last N trading days.

    Shows short volume, total volume, and short volume ratio (short / total)
    for each trading day. Useful for tracking squeeze dynamics between the
    bi-monthly short interest reports.

    symbol: ticker symbol (e.g. 'WOLF', 'GME').
    days: number of trading days to fetch (default 20, max 60).

    Source: FINRA Combined NMS short volume data (no API key required).
    """
    symbol = symbol.upper()
    days = min(days, 60)
    targets = _business_days(date.today() - timedelta(days=1), days)

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for d in targets:
            rows = await _fetch_finra_day(client, d)
            for r in rows:
                if r["symbol"] == symbol:
                    short_vol = r["short_volume"]
                    total_vol = r["total_volume"]
                    ratio = short_vol / total_vol * 100 if total_vol > 0 else 0
                    results.append(
                        {
                            "Date": d.strftime("%Y-%m-%d"),
                            "Short Vol": fmt_large(short_vol),
                            "Total Vol": fmt_large(total_vol),
                            "Short %": f"{ratio:.1f}%",
                            "Exempt Vol": fmt_large(r["short_exempt_volume"]),
                        }
                    )
                    break

    if not results:
        return f"No FINRA short volume data found for {symbol}."

    short_pcts = []
    for r in results:
        try:
            short_pcts.append(float(r["Short %"].rstrip("%")))
        except ValueError:
            pass
    avg_pct = sum(short_pcts) / len(short_pcts) if short_pcts else 0

    header = f"## {symbol} Daily Short Volume ({len(results)} days)\n\n"
    header += f"Average short volume ratio: {avg_pct:.1f}%\n\n"
    return header + list_table(results)
