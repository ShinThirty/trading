"""Tradier API endpoint definitions with typed request/response models."""

from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint, ParamsRequest, PathRequest
from trading_clients.table_helpers import (
    fmt_large,
    fmt_number,
    kv_table,
    list_table,
    md_table,
)

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
class SymbolRequest(ParamsRequest):
    symbol: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol}


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

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {"symbol": self.symbol, "interval": self.interval}
        if self.start:
            params["start"] = self.start
        if self.end:
            params["end"] = self.end
        return params


@dataclass
class AccountIdRequest(PathRequest, ParamsRequest):
    account_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class GetOrdersRequest(PathRequest, ParamsRequest):
    account_id: str
    status: str | None = None
    page: int | None = None
    limit: int | None = None

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.status:
            params["status"] = self.status
        if self.page:
            params["page"] = str(self.page)
        if self.limit:
            params["limit"] = str(self.limit)
        return params


@dataclass
class GetOrderDetailRequest(PathRequest, ParamsRequest):
    account_id: str
    order_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id, "order_id": self.order_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class GetGainLossRequest(PathRequest, ParamsRequest):
    account_id: str
    page: int | None = None
    limit: int | None = None
    sort_by: str | None = None
    sort: str | None = None

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.page:
            params["page"] = str(self.page)
        if self.limit:
            params["limit"] = str(self.limit)
        if self.sort_by:
            params["sortBy"] = self.sort_by
        if self.sort:
            params["sort"] = self.sort
        return params


@dataclass
class GetAccountHistoryRequest(PathRequest, ParamsRequest):
    account_id: str
    page: int | None = None
    limit: int | None = None
    activity_type: str | None = None

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.page:
            params["page"] = str(self.page)
        if self.limit:
            params["limit"] = str(self.limit)
        if self.activity_type:
            params["type"] = self.activity_type
        return params


@dataclass
class PlaceOrderRequest(PathRequest, BodyRequest):
    account_id: str
    order_params: dict[str, str]

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_body(self) -> dict[str, Any]:
        return self.order_params


@dataclass
class ModifyOrderRequest(PathRequest, BodyRequest):
    account_id: str
    order_id: str
    modifications: dict[str, str]

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id, "order_id": self.order_id}

    def to_body(self) -> dict[str, Any]:
        return self.modifications


@dataclass
class CancelOrderRequest(PathRequest, ParamsRequest):
    account_id: str
    order_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id, "order_id": self.order_id}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class ExpirationsResponse:
    dates: list[str]

    @classmethod
    def from_response(cls, data: list[str]) -> "ExpirationsResponse":
        return cls(dates=data or [])

    def to_markdown(self) -> str:
        if not self.dates:
            return "(no expirations)"
        return md_table(["Expiration"], [[d] for d in self.dates])


@dataclass
class StrikesResponse:
    strikes: list

    @classmethod
    def from_response(cls, data: list) -> "StrikesResponse":
        return cls(strikes=data or [])

    def to_markdown(self) -> str:
        if not self.strikes:
            return "(no strikes)"
        return md_table(["Strike"], [[fmt_number(s)] for s in self.strikes])


@dataclass
class OptionChainResponse:
    options: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "OptionChainResponse":
        return cls(options=data or [])

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
        if not self.options:
            return "(no options)"
        return md_table(["Option Symbol"], [[str(o)] for o in self.options])


@dataclass
class HistoryResponse:
    days: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "HistoryResponse":
        return cls(days=data or [])

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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


@dataclass
class ProfileResponse:
    accounts: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "ProfileResponse":
        return cls(accounts=data or [])

    def to_markdown(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account": a.get("account_number", ""),
                "Type": a.get("type", ""),
                "Classification": a.get("classification", ""),
                "Option Level": str(a.get("option_level", "")),
                "Day Trader": str(a.get("day_trader", "")),
                "Status": a.get("status", ""),
            }
            for a in self.accounts
        ]
        return list_table(rows)


@dataclass
class BalancesResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "BalancesResponse":
        return cls(data=data or {})

    def to_markdown(self) -> str:
        if not self.data:
            return "(no data)"
        selected = {
            "Account": self.data.get("account_number"),
            "Account Type": self.data.get("account_type"),
            "Total Equity": fmt_number(self.data.get("total_equity")),
            "Total Cash": fmt_number(self.data.get("total_cash")),
            "Market Value": fmt_number(self.data.get("market_value")),
            "Option Value": fmt_number(self.data.get("option_long_value")),
            "Stock Buying Power": fmt_number(self.data.get("stock_buying_power")),
            "Option Buying Power": fmt_number(self.data.get("option_buying_power")),
            "Pending Cash": fmt_number(self.data.get("pending_cash")),
            "Uncleared Funds": fmt_number(self.data.get("uncleared_funds")),
        }
        return kv_table({k: v for k, v in selected.items() if v})


@dataclass
class PositionsResponse:
    positions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "PositionsResponse":
        return cls(positions=data or [])

    def to_markdown(self) -> str:
        if not self.positions:
            return "(no positions)"
        rows = [
            {
                "Symbol": p.get("symbol", ""),
                "Qty": fmt_number(p.get("quantity"), 0),
                "Cost Basis": fmt_number(p.get("cost_basis")),
                "Date Acquired": p.get("date_acquired", ""),
            }
            for p in self.positions
        ]
        return list_table(rows)


@dataclass
class OrdersResponse:
    orders: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "OrdersResponse":
        return cls(orders=data or [])

    def to_markdown(self) -> str:
        if not self.orders:
            return "(no orders)"
        rows = [
            {
                "ID": str(o.get("id", "")),
                "Class": o.get("class", ""),
                "Symbol": o.get("symbol", ""),
                "Side": o.get("side", ""),
                "Qty": fmt_number(o.get("quantity"), 0),
                "Type": o.get("type", ""),
                "Price": fmt_number(o.get("price")),
                "Stop": fmt_number(o.get("stop_price")),
                "Status": o.get("status", ""),
                "Duration": o.get("duration", ""),
                "Created": (o.get("create_date") or "")[:10],
            }
            for o in self.orders
        ]
        return list_table(rows)


@dataclass
class KVResponse:
    """Generic key-value response for order detail, place, modify, cancel."""

    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "KVResponse":
        return cls(data=data or {})

    def to_markdown(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(self.data)


@dataclass
class GainLossResponse:
    items: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "GainLossResponse":
        return cls(items=data or [])

    def to_markdown(self) -> str:
        if not self.items:
            return "(no closed positions)"
        rows = [
            {
                "Symbol": g.get("symbol", ""),
                "Qty": fmt_number(g.get("quantity"), 0),
                "Open Date": (g.get("open_date") or "")[:10],
                "Close Date": (g.get("close_date") or "")[:10],
                "Term": g.get("term", ""),
                "Cost": fmt_number(g.get("cost")),
                "Proceeds": fmt_number(g.get("proceeds")),
                "Gain/Loss": fmt_number(g.get("gain_loss")),
                "G/L %": fmt_number(g.get("gain_loss_percent")),
            }
            for g in self.items
        ]
        return list_table(rows)


@dataclass
class AccountHistoryResponse:
    events: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountHistoryResponse":
        return cls(events=data or [])

    def to_markdown(self) -> str:
        if not self.events:
            return "(no activity)"
        rows = [
            {
                "Date": (e.get("date") or "")[:10],
                "Type": e.get("type", ""),
                "Amount": fmt_number(e.get("amount")),
                "Description": e.get("description", ""),
            }
            for e in self.events
        ]
        return list_table(rows)


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

# ── Account ─────────────────────────────────────────────────

PROFILE = Endpoint(
    "/v1/user/profile",
    response_model=ProfileResponse,
    extract=lambda d: _ensure_list(d.get("profile", {}).get("account", [])),
)

BALANCES = Endpoint(
    "/v1/accounts/{account_id}/balances",
    response_model=BalancesResponse,
    extract=lambda d: d.get("balances", {}),
)

POSITIONS = Endpoint(
    "/v1/accounts/{account_id}/positions",
    response_model=PositionsResponse,
    extract=lambda d: _ensure_list(
        (d.get("positions") or {}).get("position", [])
        if d.get("positions") not in ("null", None)
        else []
    ),
)

ORDERS = Endpoint(
    "/v1/accounts/{account_id}/orders",
    response_model=OrdersResponse,
    extract=lambda d: _ensure_list(
        (d.get("orders") or {}).get("order", []) if d.get("orders") not in ("null", None) else []
    ),
)

ORDER_DETAIL = Endpoint(
    "/v1/accounts/{account_id}/orders/{order_id}",
    response_model=KVResponse,
    extract=lambda d: d.get("order", {}),
)

GAINLOSS = Endpoint(
    "/v1/accounts/{account_id}/gainloss",
    response_model=GainLossResponse,
    extract=lambda d: _ensure_list(
        (d.get("gainloss") or {}).get("closed_position", [])
        if d.get("gainloss") not in ("null", None)
        else []
    ),
)

ACCOUNT_HISTORY = Endpoint(
    "/v1/accounts/{account_id}/history",
    response_model=AccountHistoryResponse,
    extract=lambda d: _ensure_list(
        (d.get("history") or {}).get("event", []) if d.get("history") not in ("null", None) else []
    ),
)

# ── Order Management ────────────────────────────────────────

PLACE_ORDER = Endpoint(
    "/v1/accounts/{account_id}/orders",
    response_model=KVResponse,
    extract=lambda d: d.get("errors") if "errors" in d else d.get("order", d),
)

MODIFY_ORDER = Endpoint(
    "/v1/accounts/{account_id}/orders/{order_id}",
    response_model=KVResponse,
    extract=lambda d: d.get("order", {}),
)

CANCEL_ORDER = Endpoint(
    "/v1/accounts/{account_id}/orders/{order_id}",
    response_model=KVResponse,
    extract=lambda d: d.get("order", {}),
)
