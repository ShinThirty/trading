"""Tradier API endpoint definitions with typed request/response models."""

import re
from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import CONTRACT_MULTIPLIER, Endpoint, ParamsRequest, PathRequest
from trading_clients.options import parse_occ
from trading_clients.portfolio import NormalizedPosition
from trading_clients.table_helpers import (
    fmt_large,
    fmt_number,
    kv_table,
    list_table,
    to_float_zero,
)

# Compact OCC option symbol (no space padding), e.g. "VXX190517P00016000".
_OCC_RE = re.compile(r"^[A-Z.]+\d{6}[CP]\d{8}$")

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _ensure_list(val: Any) -> list:
    """Tradier sometimes returns a single dict instead of a list."""
    if isinstance(val, dict):
        return [val]
    return val or []


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class GetExpirationsRequest(ParamsRequest):
    symbol: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "includeAllRoots": "true", "strikes": "false"}


@dataclass
class GetStrikesRequest(ParamsRequest):
    symbol: str
    expiration: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "expiration": self.expiration}


@dataclass
class GetChainRequest(ParamsRequest):
    symbol: str
    expiration: str
    greeks: bool = True

    def to_params(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "expiration": self.expiration,
            "greeks": str(self.greeks).lower(),
        }


@dataclass
class GetLookupRequest(ParamsRequest):
    underlying: str

    def to_params(self) -> dict[str, str]:
        return {"underlying": self.underlying}


@dataclass
class GetHistoryRequest(ParamsRequest):
    symbol: str
    interval: str = "daily"
    start: str | None = None
    end: str | None = None

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {"symbol": self.symbol, "interval": self.interval}
        if self.start:
            params["start"] = self.start
        if self.end:
            params["end"] = self.end
        return params


@dataclass
class SearchRequest(ParamsRequest):
    q: str
    indexes: bool = False

    def to_params(self) -> dict[str, str]:
        return {"q": self.q, "indexes": str(self.indexes).lower()}


@dataclass
class GetQuotesRequest(ParamsRequest):
    symbols: str
    greeks: bool = False

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols, "greeks": str(self.greeks).lower()}


@dataclass
class GetTimesalesRequest(ParamsRequest):
    symbol: str
    interval: str = "5min"
    start: str | None = None
    end: str | None = None
    session_filter: str = "open"

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "session_filter": self.session_filter,
        }
        if self.start:
            params["start"] = self.start
        if self.end:
            params["end"] = self.end
        return params


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class ExpirationsResponse:
    dates: list[str]

    @classmethod
    def from_response(cls, data: list[str]) -> "ExpirationsResponse":
        return cls(dates=data or [])

    def to_output(self) -> str:
        if not self.dates:
            return "(no expirations)"
        return ", ".join(self.dates)


@dataclass
class StrikesResponse:
    strikes: list

    @classmethod
    def from_response(cls, data: list) -> "StrikesResponse":
        return cls(strikes=data or [])

    def to_output(self) -> str:
        if not self.strikes:
            return "(no strikes)"
        return ", ".join(fmt_number(s) for s in self.strikes)


@dataclass
class OptionChainResponse:
    options: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "OptionChainResponse":
        return cls(options=data or [])

    def to_output(self) -> str:
        if not self.options:
            return "(no options)"
        rows = []
        for o in self.options:
            greeks = o.get("greeks", {}) or {}
            rows.append(
                {
                    "Symbol": o.get("symbol", ""),
                    "Type": o.get("option_type", ""),
                    "Strike": fmt_number(o.get("strike")),
                    "Bid": fmt_number(o.get("bid")),
                    "Bid Sz": fmt_large(o.get("bidsize")),
                    "Ask": fmt_number(o.get("ask")),
                    "Ask Sz": fmt_large(o.get("asksize")),
                    "Last": fmt_number(o.get("last")),
                    "Change": fmt_number(o.get("change")),
                    "Change %": fmt_number(o.get("change_percentage")),
                    "Vol": fmt_large(o.get("volume")),
                    "OI": fmt_large(o.get("open_interest")),
                    "IV": fmt_number(greeks.get("mid_iv"), 4),
                    "Delta": fmt_number(greeks.get("delta"), 4),
                    "Gamma": fmt_number(greeks.get("gamma"), 4),
                    "Theta": fmt_number(greeks.get("theta"), 4),
                    "Vega": fmt_number(greeks.get("vega"), 4),
                    "Rho": fmt_number(greeks.get("rho"), 4),
                }
            )
        return list_table(rows)


@dataclass
class OptionLookupResponse:
    options: list

    @classmethod
    def from_response(cls, data: list) -> "OptionLookupResponse":
        return cls(options=data or [])

    def to_output(self) -> str:
        if not self.options:
            return "(no options)"
        return ", ".join(str(o) for o in self.options)


@dataclass
class HistoryResponse:
    days: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "HistoryResponse":
        return cls(days=data or [])

    def to_output(self) -> str:
        if not self.days:
            return "(no data)"
        rows = [
            {
                "Date": d.get("date", ""),
                "Open": fmt_number(d.get("open")),
                "High": fmt_number(d.get("high")),
                "Low": fmt_number(d.get("low")),
                "Close": fmt_number(d.get("close")),
                "Volume": fmt_large(d.get("volume")),
            }
            for d in self.days
        ]
        return list_table(rows)


@dataclass
class SearchResponse:
    results: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "SearchResponse":
        return cls(results=data or [])

    def to_output(self) -> str:
        if not self.results:
            return "(no results)"
        rows = [
            {
                "Symbol": s.get("symbol", ""),
                "Exchange": s.get("exchange", ""),
                "Type": s.get("type", ""),
                "Description": s.get("description", ""),
            }
            for s in self.results
        ]
        return list_table(rows)


@dataclass
class QuotesResponse:
    quotes: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "QuotesResponse":
        return cls(quotes=data or [])

    def to_output(self) -> str:
        if not self.quotes:
            return "(no quotes)"
        rows = []
        for q in self.quotes:
            is_option = q.get("option_type") is not None
            row: dict[str, str] = {"Symbol": q.get("symbol", "")}
            if is_option:
                row["Type"] = q.get("option_type", "")
                row["Strike"] = fmt_number(q.get("strike"))
                row["Exp"] = q.get("expiration_date", "")
            row |= {
                "Last": fmt_number(q.get("last")),
                "Bid": fmt_number(q.get("bid")),
                "Bid Sz": fmt_large(q.get("bidsize")),
                "Ask": fmt_number(q.get("ask")),
                "Ask Sz": fmt_large(q.get("asksize")),
                "Volume": fmt_large(q.get("volume")),
                "Change": fmt_number(q.get("change")),
                "Change %": fmt_number(q.get("change_percentage")),
            }
            if is_option:
                row["OI"] = fmt_large(q.get("open_interest"))
            else:
                row |= {
                    "Prev Close": fmt_number(q.get("prevclose")),
                    "Open": fmt_number(q.get("open")),
                    "High": fmt_number(q.get("high")),
                    "Low": fmt_number(q.get("low")),
                    "Avg Vol": fmt_large(q.get("average_volume")),
                    "52W High": fmt_number(q.get("week_52_high")),
                    "52W Low": fmt_number(q.get("week_52_low")),
                }
            greeks = q.get("greeks")
            if greeks:
                row |= {
                    "IV": fmt_number(greeks.get("mid_iv"), 4),
                    "Delta": fmt_number(greeks.get("delta"), 4),
                    "Gamma": fmt_number(greeks.get("gamma"), 4),
                    "Theta": fmt_number(greeks.get("theta"), 4),
                    "Vega": fmt_number(greeks.get("vega"), 4),
                    "Rho": fmt_number(greeks.get("rho"), 4),
                }
            rows.append(row)
        has_stocks = any(q.get("option_type") is None for q in self.quotes)
        has_options = any(q.get("option_type") is not None for q in self.quotes)
        has_greeks = any("IV" in r for r in rows)
        cols = ["Symbol"]
        if has_options:
            cols += ["Type", "Strike", "Exp"]
        cols += ["Last", "Bid", "Bid Sz", "Ask", "Ask Sz", "Volume", "Change", "Change %"]
        if has_options:
            cols += ["OI"]
        if has_stocks:
            cols += ["Prev Close", "Open", "High", "Low", "Avg Vol", "52W High", "52W Low"]
        if has_greeks:
            cols += ["IV", "Delta", "Gamma", "Theta", "Vega", "Rho"]
        return list_table(rows, cols)


@dataclass
class TimesalesResponse:
    ticks: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "TimesalesResponse":
        return cls(ticks=data or [])

    def to_output(self) -> str:
        if not self.ticks:
            return "(no data)"
        rows = [
            {
                "Time": t.get("time", "")[:19],
                "Price": fmt_number(t.get("price")),
                "Open": fmt_number(t.get("open")),
                "High": fmt_number(t.get("high")),
                "Low": fmt_number(t.get("low")),
                "Close": fmt_number(t.get("close")),
                "Volume": fmt_large(t.get("volume")),
            }
            for t in self.ticks
        ]
        return list_table(rows)


@dataclass
class ClockResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "ClockResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(
            {
                "State": self.data.get("state"),
                "Description": self.data.get("description"),
                "Date": self.data.get("date"),
                "Timestamp": self.data.get("timestamp"),
                "Next State": self.data.get("next_state"),
                "Next Change": self.data.get("next_change"),
            }
        )


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# ── Market Data ─────────────────────────────────────────────

EXPIRATIONS = Endpoint(
    "/v1/markets/options/expirations",
    cache_ttl=3600,
    response_model=ExpirationsResponse,
    extract=lambda d: d.get("expirations", {}).get("date", []),
)

STRIKES = Endpoint(
    "/v1/markets/options/strikes",
    cache_ttl=3600,
    response_model=StrikesResponse,
    extract=lambda d: d.get("strikes", {}).get("strike", []),
)

CHAIN = Endpoint(
    "/v1/markets/options/chains",
    cache_ttl=30,
    response_model=OptionChainResponse,
    extract=lambda d: d.get("options", {}).get("option", []),
)

OPTION_LOOKUP = Endpoint(
    "/v1/markets/options/lookup",
    cache_ttl=3600,
    response_model=OptionLookupResponse,
    extract=lambda d: (
        d.get("symbols", [{}])[0].get("options", [])
        if isinstance(d.get("symbols"), list)
        else d.get("symbols", {}).get("options", [])
    ),
)

HISTORY = Endpoint(
    "/v1/markets/history",
    cache_ttl=300,
    response_model=HistoryResponse,
    extract=lambda d: _ensure_list((d.get("history") or {}).get("day", [])),
)

SEARCH = Endpoint(
    "/v1/markets/search",
    cache_ttl=3600,
    response_model=SearchResponse,
    extract=lambda d: _ensure_list((d.get("securities") or {}).get("security", [])),
)

QUOTES = Endpoint(
    "/v1/markets/quotes",
    response_model=QuotesResponse,
    extract=lambda d: _ensure_list(d.get("quotes", {}).get("quote", [])),
)

TIMESALES = Endpoint(
    "/v1/markets/timesales",
    cache_ttl=60,
    response_model=TimesalesResponse,
    extract=lambda d: _ensure_list((d.get("series") or {}).get("data", [])),
)

CLOCK = Endpoint(
    "/v1/markets/clock",
    cache_ttl=30,
    response_model=ClockResponse,
    extract=lambda d: d.get("clock", {}),
)


# ═══════════════════════════════════════════════════════════════
# Account (read-only): profile, balances, positions, orders
# ═══════════════════════════════════════════════════════════════


@dataclass
class AccountPathRequest(PathRequest, ParamsRequest):
    """GET scoped to a single account via {account_id} path template."""

    account_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class AccountProfileResponse:
    accounts: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountProfileResponse":
        return cls(accounts=data or [])

    def account_numbers(self) -> list[str]:
        return [a.get("account_number", "") for a in self.accounts if a.get("account_number")]

    def to_output(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account #": a.get("account_number", ""),
                "Type": a.get("type", ""),
                "Class": a.get("classification", ""),
                "Opt Lvl": str(a.get("option_level", "")),
                "Day Trader": str(a.get("day_trader", "")),
                "Status": a.get("status", ""),
            }
            for a in self.accounts
        ]
        return list_table(rows)


@dataclass
class AccountBalancesResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "AccountBalancesResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        d = self.data
        if not d:
            return "(no balance)"
        fields = {
            "Account #": d.get("account_number"),
            "Type": d.get("account_type"),
            "Net Liq (Equity)": fmt_number(d.get("total_equity")),
            "Total Cash": fmt_number(d.get("total_cash")),
            "Market Value": fmt_number(d.get("market_value")),
            "Long Mkt Value": fmt_number(d.get("long_market_value")),
            "Short Mkt Value": fmt_number(d.get("short_market_value")),
            "Stock Long Value": fmt_number(d.get("stock_long_value")),
            "Option Long Value": fmt_number(d.get("option_long_value")),
            "Open P&L": fmt_number(d.get("open_pl")),
            "Close P&L": fmt_number(d.get("close_pl")),
            "Uncleared Funds": fmt_number(d.get("uncleared_funds")),
            "Pending Cash": fmt_number(d.get("pending_cash")),
        }
        return kv_table({k: v for k, v in fields.items() if v not in (None, "")})


@dataclass
class AccountPositionsResponse:
    positions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountPositionsResponse":
        return cls(positions=data or [])

    def to_normalized(self) -> list[NormalizedPosition]:
        """Normalize for aggregation. Tradier positions carry no price, so
        last/value/pnl are left at 0.0 — the fetch layer fills them from a
        batched quote. Tradier reports cost_basis as a signed total (negative
        credit for shorts); `cost` keeps its per-unit magnitude — positive for
        shorts too, matching other brokers."""
        result: list[NormalizedPosition] = []
        for p in self.positions:
            symbol = p.get("symbol", "")
            qty = to_float_zero(p.get("quantity"))
            cost_basis = to_float_zero(p.get("cost_basis"))
            is_opt = bool(_OCC_RE.match(symbol))
            mult = CONTRACT_MULTIPLIER if is_opt else 1
            denom = (abs(qty) * mult) or 1
            pos = NormalizedPosition(
                symbol=symbol,
                quantity=qty,
                last=0.0,
                cost=abs(cost_basis) / denom,
                value=0.0,
                pnl=0.0,
                pnl_pct=0.0,
                is_option=is_opt,
                is_cash=False,
            )
            if is_opt:
                underlying, exp, option_type, strike = parse_occ(symbol)
                pos.underlying = underlying
                pos.option_type = option_type
                pos.strike = strike
                pos.expiration = exp
                pos.strategy = ""
            result.append(pos)
        return result

    def to_output(self) -> str:
        if not self.positions:
            return "(no positions)"
        has_options = any(_OCC_RE.match(p.get("symbol", "")) for p in self.positions)
        rows = []
        for p in self.positions:
            symbol = p.get("symbol", "")
            row: dict[str, str] = {
                "Symbol": symbol,
                "Qty": fmt_number(p.get("quantity"), 0),
                "Cost Basis": fmt_number(p.get("cost_basis")),
                "Acquired": (p.get("date_acquired") or "")[:10],
            }
            if has_options:
                if _OCC_RE.match(symbol):
                    underlying, exp, option_type, strike = parse_occ(symbol)
                    row |= {
                        "Underlying": underlying,
                        "Option": option_type,
                        "Strike": fmt_number(strike),
                        "Exp": exp,
                    }
                else:
                    row |= {"Underlying": "", "Option": "", "Strike": "", "Exp": ""}
            rows.append(row)
        return list_table(rows)


@dataclass
class AccountOrdersResponse:
    orders: list[dict]

    _OPEN_STATUSES = {"open", "pending", "partially_filled"}

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountOrdersResponse":
        return cls(orders=data or [])

    def filter_by_status(self, status: str) -> "AccountOrdersResponse":
        if status == "all":
            return self
        if status == "open":
            keep = [o for o in self.orders if o.get("status") in self._OPEN_STATUSES]
        else:
            keep = [o for o in self.orders if o.get("status") == status]
        return AccountOrdersResponse(orders=keep)

    def to_output(self) -> str:
        if not self.orders:
            return "(no orders)"
        rows = []
        for o in self.orders:
            rows.append(
                {
                    "Order ID": str(o.get("id", "")),
                    "Symbol": o.get("option_symbol") or o.get("symbol", ""),
                    "Side": o.get("side", ""),
                    "Type": o.get("type", ""),
                    "Class": o.get("class", ""),
                    "Qty": fmt_number(o.get("quantity"), 0),
                    "Filled": fmt_number(o.get("exec_quantity"), 0),
                    "Price": fmt_number(o.get("price")),
                    "Avg Fill": fmt_number(o.get("avg_fill_price")),
                    "Status": o.get("status", ""),
                    "Duration": o.get("duration", ""),
                    "Created": (o.get("create_date") or "")[:19],
                }
            )
        return list_table(rows)


def _extract_tradier_positions(d: dict) -> list:
    """Tradier returns the JSON string "null" for `positions` when the account
    is flat — guard against it before reaching into `.position`."""
    pos = d.get("positions")
    if not isinstance(pos, dict):
        return []
    return _ensure_list(pos.get("position", []))


def _extract_tradier_orders(d: dict) -> list:
    orders = d.get("orders")
    if not isinstance(orders, dict):
        return []
    return _ensure_list(orders.get("order", []))


PROFILE = Endpoint(
    "/v1/user/profile",
    cache_ttl=300,
    response_model=AccountProfileResponse,
    extract=lambda d: _ensure_list((d.get("profile") or {}).get("account", [])),
)

BALANCES = Endpoint(
    "/v1/accounts/{account_id}/balances",
    cache_ttl=60,
    response_model=AccountBalancesResponse,
    extract=lambda d: d.get("balances", {}),
)

POSITIONS = Endpoint(
    "/v1/accounts/{account_id}/positions",
    cache_ttl=60,
    response_model=AccountPositionsResponse,
    extract=_extract_tradier_positions,
)

ORDERS = Endpoint(
    "/v1/accounts/{account_id}/orders",
    cache_ttl=30,
    response_model=AccountOrdersResponse,
    extract=_extract_tradier_orders,
)
