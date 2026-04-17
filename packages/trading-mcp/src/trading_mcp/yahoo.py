"""Yahoo Finance helpers via yfinance.

Wraps yfinance calls for stock screening, institutional ownership,
and short interest. Returns plain dicts/DataFrames — formatting is
handled by callers in server.py.
"""

from typing import Any

import yfinance as yf
from trading_clients.cache import ThreadSafeTTLCache
from yfinance import EquityQuery
from yfinance import screen as _screen

_cache = ThreadSafeTTLCache()

_TTL_FUNDAMENTALS = 3600  # earnings, income stmt, price targets
_TTL_SCREENER = 300  # screeners, short interest, holders


def _cached(key: str, ttl: int, fn: Any, *args: Any, **kwargs: Any) -> Any:
    hit = _cache.get(key, ttl)
    if hit is not None:
        return hit
    result = fn(*args, **kwargs)
    _cache.put(key, result)
    return result


def predefined_screen(screen_id: str, count: int = 25) -> dict:
    """Run a predefined Yahoo Finance screen."""
    return _cached(f"screen:{screen_id}:{count}", _TTL_SCREENER, _screen, screen_id, count=count)


def custom_screen(
    criteria: list[dict],
    sort_field: str = "intradaymarketcap",
    sort_asc: bool = False,
    size: int = 25,
) -> dict:
    """Run a custom stock screen from criteria dicts."""
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
    return _cached(
        key, _TTL_SCREENER, _screen, query, sortField=sort_field, sortAsc=sort_asc, size=size
    )


def _institutional_holders_uncached(symbol: str) -> list[dict]:
    df = yf.Ticker(symbol).institutional_holders
    if df is None or df.empty:
        return []
    return [row.to_dict() for _, row in df.iterrows()]


def institutional_holders(symbol: str) -> list[dict]:
    """Get top institutional holders for a symbol. Returns list of row dicts."""
    return _cached(f"holders:{symbol}", _TTL_SCREENER, _institutional_holders_uncached, symbol)


def _short_interest_uncached(symbol: str) -> dict:
    info = yf.Ticker(symbol).info or {}
    return {
        "sharesShort": info.get("sharesShort"),
        "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
        "shortRatio": info.get("shortRatio"),
        "shortPercentOfFloat": info.get("shortPercentOfFloat"),
    }


def short_interest(symbol: str) -> dict:
    """Get short interest metrics for a symbol from Ticker.info."""
    return _cached(f"short:{symbol}", _TTL_SCREENER, _short_interest_uncached, symbol)


def _earnings_estimate_uncached(symbol: str) -> list[dict]:
    df = yf.Ticker(symbol).get_earnings_estimate()
    if df is None or df.empty:
        return []
    rows = []
    for period, row in df.iterrows():
        r = row.to_dict()
        r["period"] = str(period)
        rows.append(r)
    return rows


def earnings_estimate(symbol: str) -> list[dict]:
    """Get analyst EPS estimates. Returns list of row dicts with period as a field."""
    return _cached(f"eps_est:{symbol}", _TTL_FUNDAMENTALS, _earnings_estimate_uncached, symbol)


def _income_statement_uncached(symbol: str, period: str, limit: int) -> list[dict]:
    t = yf.Ticker(symbol)
    df = t.quarterly_income_stmt if period == "quarterly" else t.income_stmt
    if df is None or df.empty:
        return []

    def _get(label: str) -> float | None:
        return float(df.loc[label, col]) if label in df.index else None

    rows = []
    for col in df.columns[:limit]:
        rows.append({
            "period": col.strftime("%Y-%m-%d"),
            "revenue": _get("Total Revenue"),
            "cost_of_revenue": _get("Cost Of Revenue"),
            "gross_profit": _get("Gross Profit"),
            "operating_income": _get("Operating Income"),
            "net_income": _get("Net Income"),
            "eps": _get("Basic EPS"),
        })
    return rows


def income_statement(symbol: str, period: str = "quarterly", limit: int = 4) -> list[dict]:
    """Get income statement data. Returns list of quarterly/annual row dicts.

    Each dict has: period, revenue, cost_of_revenue, gross_profit,
    operating_income, net_income, eps (basic).
    """
    return _cached(
        f"income:{symbol}:{period}:{limit}",
        _TTL_FUNDAMENTALS,
        _income_statement_uncached,
        symbol,
        period,
        limit,
    )


def _analyst_price_targets_uncached(symbol: str) -> dict:
    return yf.Ticker(symbol).get_analyst_price_targets() or {}


def analyst_price_targets(symbol: str) -> dict:
    """Get analyst consensus price targets: current, low, mean, median, high."""
    return _cached(f"targets:{symbol}", _TTL_FUNDAMENTALS, _analyst_price_targets_uncached, symbol)
