"""Yahoo Finance async helpers shared by fundamentals and screens tools."""

import yfinance as yf
from trading_clients.cache import TTLCache
from yfinance import EquityQuery
from yfinance import screen as _screen

from trading_mcp.helpers import _cached

_cache = TTLCache()
_TTL_FUNDAMENTALS = 3600
_TTL_SCREENER = 300
_TTL_QUOTE = 60


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

    @staticmethod
    async def global_quote(symbol: str) -> dict:
        """Latest daily bar + metadata for any Yahoo symbol, including foreign
        listings ('000660.KS', '7203.T'). Returns {} when Yahoo has no data.
        While the home market trades the last bar is Yahoo's ~15-20 min delayed
        price; after its close it is the official close."""

        def _uncached(s: str) -> dict:
            tk = yf.Ticker(s)
            hist = tk.history(period="10d", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                return {}
            bar = hist.iloc[-1]
            out: dict = {
                "symbol": s,
                "date": hist.index[-1].strftime("%Y-%m-%d"),
                "open": float(bar["Open"]),
                "high": float(bar["High"]),
                "low": float(bar["Low"]),
                "close": float(bar["Close"]),
                "volume": float(bar["Volume"]),
            }
            if len(hist) > 1:
                out["prev_close"] = float(hist["Close"].iloc[-2])
            try:
                fi = tk.fast_info
                out["currency"] = str(fi["currency"])
                out["exchange"] = str(fi["exchange"])
            except Exception:
                pass  # metadata is best-effort; prices already set
            return out

        return await _cached(_cache, f"gquote:{symbol}", _TTL_QUOTE, _uncached, symbol)

    @staticmethod
    async def fx_rate(pair: str) -> dict:
        """FX rate for a 6-letter pair ('USDKRW') via Yahoo '{pair}=X'.
        Rate = quote-currency units per 1 base-currency unit. Returns {} when
        Yahoo has no data; 'asof' is 'live' from fast_info or the daily bar
        date on fallback."""

        def _uncached(p: str) -> dict:
            tk = yf.Ticker(f"{p}=X")
            rate = 0.0
            try:
                rate = float(tk.fast_info["lastPrice"])
            except Exception:
                rate = 0.0
            if rate > 0:
                return {"pair": p, "rate": rate, "asof": "live"}
            hist = tk.history(period="5d", interval="1d")
            if hist is None or hist.empty:
                return {}
            return {
                "pair": p,
                "rate": float(hist["Close"].iloc[-1]),
                "asof": hist.index[-1].strftime("%Y-%m-%d"),
            }

        return await _cached(_cache, f"fx:{pair}", _TTL_QUOTE, _uncached, pair)

    @staticmethod
    async def exchange_code(symbol: str) -> str | None:
        """Yahoo's internal exchange code for a ticker (e.g. 'ASE', 'NYQ',
        'NMS'). Returns None on lookup failure or when Yahoo has no exchange
        info. Cached for an hour — exchange listings rarely change."""

        def _uncached(s: str) -> str | None:
            try:
                info = yf.Ticker(s).info or {}
            except Exception:
                return None
            code = info.get("exchange")
            return str(code).upper() if code else None

        return await _cached(_cache, f"exchange:{symbol}", _TTL_FUNDAMENTALS, _uncached, symbol)
