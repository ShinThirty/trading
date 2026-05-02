"""Yahoo Finance async helpers shared by fundamentals and screens tools."""

import yfinance as yf
from trading_clients.cache import TTLCache
from yfinance import EquityQuery
from yfinance import screen as _screen

from trading_mcp.helpers import _cached

_cache = TTLCache()
_TTL_FUNDAMENTALS = 3600
_TTL_SCREENER = 300


class _yfc:
    """Namespace for Yahoo Finance async helpers used by tool modules."""

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
            EquityQuery("eq", ["region", "us"]),
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
