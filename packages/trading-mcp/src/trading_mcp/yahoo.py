"""Yahoo Finance helpers via yfinance.

Wraps yfinance calls for stock screening, institutional ownership,
and short interest. Returns plain dicts/DataFrames — formatting is
handled by callers in server.py.
"""

import yfinance as yf
from yfinance import EquityQuery
from yfinance import screen as _screen


def predefined_screen(screen_id: str, count: int = 25) -> dict:
    """Run a predefined Yahoo Finance screen."""
    return _screen(screen_id, count=count)


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
    return _screen(query, sortField=sort_field, sortAsc=sort_asc, size=size)


def institutional_holders(symbol: str) -> list[dict]:
    """Get top institutional holders for a symbol. Returns list of row dicts."""
    df = yf.Ticker(symbol).institutional_holders
    if df is None or df.empty:
        return []
    return [row.to_dict() for _, row in df.iterrows()]


def short_interest(symbol: str) -> dict:
    """Get short interest metrics for a symbol from Ticker.info."""
    info = yf.Ticker(symbol).info or {}
    return {
        "sharesShort": info.get("sharesShort"),
        "sharesShortPriorMonth": info.get("sharesShortPriorMonth"),
        "shortRatio": info.get("shortRatio"),
        "shortPercentOfFloat": info.get("shortPercentOfFloat"),
    }


def earnings_estimate(symbol: str) -> list[dict]:
    """Get analyst EPS estimates. Returns list of row dicts with period as a field."""
    df = yf.Ticker(symbol).get_earnings_estimate()
    if df is None or df.empty:
        return []
    rows = []
    for period, row in df.iterrows():
        r = row.to_dict()
        r["period"] = str(period)
        rows.append(r)
    return rows


def analyst_price_targets(symbol: str) -> dict:
    """Get analyst consensus price targets: current, low, mean, median, high."""
    return yf.Ticker(symbol).get_analyst_price_targets() or {}
