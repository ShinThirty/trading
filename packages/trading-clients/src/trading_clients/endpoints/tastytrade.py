"""TastyTrade API endpoint definitions with typed request/response models."""

from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint, ParamsRequest, PathRequest
from trading_clients.options import parse_occ
from trading_clients.portfolio import NormalizedPosition
from trading_clients.table_helpers import fmt_number, kv_table, list_table, to_float_zero

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class MarketMetricsRequest(ParamsRequest):
    symbols: str  # comma-separated, e.g. "AAPL,QCOM"

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols}


@dataclass
class DividendHistoryRequest(PathRequest, ParamsRequest):
    symbol: str

    def to_path_params(self) -> dict[str, str]:
        return {"symbol": self.symbol}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class WatchlistRequest(PathRequest, ParamsRequest):
    name: str

    def to_path_params(self) -> dict[str, str]:
        return {"name": self.name}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


def _fmt_ratio_pct(val: float | str | None) -> str:
    """Format a decimal ratio (0.45) as a percentage string (45.0%)."""
    if val is None or val == "":
        return ""
    try:
        return f"{float(val) * 100:.1f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_raw_pct(val: float | str | None) -> str:
    """Format a value already in percentage units (27.85 → 27.9%)."""
    if val is None or val == "":
        return ""
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_updated_at(val: str | None) -> str:
    """Format an ISO 8601 timestamp like '2026-05-01T19:54:33.797Z' as '2026-05-01 19:54Z'."""
    if not val:
        return ""
    s = str(val)
    if "T" not in s:
        return s
    date, _, rest = s.partition("T")
    hm = rest[:5]
    return f"{date} {hm}Z"


def _fmt_earnings(earnings: dict | None) -> str:
    """Format earnings info: date + time-of-day + estimated flag."""
    if not earnings:
        return ""
    date = earnings.get("expected-report-date", "")
    if not date or date == "1970-01-01":
        return ""
    tod = earnings.get("time-of-day", "")
    estimated = earnings.get("estimated", False)
    parts = [date]
    if tod:
        parts.append(tod)
    if estimated:
        parts.append("(est)")
    return " ".join(parts)


@dataclass
class MarketMetricsResponse:
    items: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "MarketMetricsResponse":
        return cls(items=data or [])

    def to_output(self) -> str:
        if not self.items:
            return "(no metrics)"
        rows = []
        for item in self.items:
            row = {
                "Symbol": item.get("symbol", ""),
                "IV Index": _fmt_ratio_pct(item.get("implied-volatility-index")),
                "IV Rank": _fmt_ratio_pct(item.get("tw-implied-volatility-index-rank")),
                "IV Pctl": _fmt_ratio_pct(item.get("implied-volatility-percentile")),
                "IV 5d Chg": _fmt_ratio_pct(item.get("implied-volatility-index-5-day-change")),
                "IV 30d": _fmt_raw_pct(item.get("implied-volatility-30-day")),
                "HV 30d": _fmt_raw_pct(item.get("historical-volatility-30-day")),
                "HV 60d": _fmt_raw_pct(item.get("historical-volatility-60-day")),
                "HV 90d": _fmt_raw_pct(item.get("historical-volatility-90-day")),
                "IV-HV": _fmt_raw_pct(item.get("iv-hv-30-day-difference")),
                "Earnings": _fmt_earnings(item.get("earnings")),
                "Liq": str(item.get("liquidity-rating", "")),
                "IV As Of": _fmt_updated_at(item.get("implied-volatility-updated-at")),
            }
            rows.append(row)
        return list_table(rows)


@dataclass
class DividendHistoryResponse:
    dividends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "DividendHistoryResponse":
        return cls(dividends=data or [])

    def to_output(self) -> str:
        if not self.dividends:
            return "(no dividends)"
        entries = [
            f"{d.get('occurred-date', '')} ${fmt_number(d.get('amount'), 4)}"
            for d in self.dividends
        ]
        return ", ".join(entries)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

MARKET_METRICS = Endpoint(
    "/market-metrics",
    cache_ttl=300,
    response_model=MarketMetricsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)

DIVIDEND_HISTORY = Endpoint(
    "/market-metrics/historic-corporate-events/dividends/{symbol}",
    cache_ttl=3600,
    response_model=DividendHistoryResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)


@dataclass
class WatchlistsResponse:
    watchlists: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "WatchlistsResponse":
        return cls(watchlists=data or [])

    def to_output(self) -> str:
        if not self.watchlists:
            return "(no watchlists)"
        entries = [
            f"{w.get('name', '')} ({len(w.get('watchlist-entries', []))})" for w in self.watchlists
        ]
        return ", ".join(entries)


@dataclass
class WatchlistDetailResponse:
    watchlist: dict

    @classmethod
    def from_response(cls, data: dict) -> "WatchlistDetailResponse":
        return cls(watchlist=data or {})

    def to_output(self) -> str:
        if not self.watchlist:
            return "(no watchlist)"
        entries = self.watchlist.get("watchlist-entries", [])
        if not entries:
            return "(empty watchlist)"
        name = self.watchlist.get("name", "Watchlist")
        symbols = [e.get("symbol", "") for e in entries if e.get("symbol")]
        return f"**{name}** ({len(symbols)} symbols): {', '.join(symbols)}"


PUBLIC_WATCHLISTS = Endpoint(
    "/public-watchlists",
    cache_ttl=3600,
    response_model=WatchlistsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)

PUBLIC_WATCHLIST = Endpoint(
    "/public-watchlists/{name}",
    cache_ttl=3600,
    response_model=WatchlistDetailResponse,
    extract=lambda d: d.get("data", d),
)


# ═══════════════════════════════════════════════════════════════
# Backtesting
# ═══════════════════════════════════════════════════════════════

BACKTESTER_URL = "https://backtester.vast.tastyworks.com"


@dataclass
class BacktestRequest(BodyRequest):
    symbol: str
    start_date: str
    end_date: str
    legs: list[dict]
    entry_conditions: dict
    exit_conditions: dict

    def to_body(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "legs": self.legs,
            "entryConditions": self.entry_conditions,
            "exitConditions": self.exit_conditions,
        }


@dataclass
class BacktestIdRequest(PathRequest, ParamsRequest):
    backtest_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"id": self.backtest_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class BacktestResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "BacktestResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        status = self.data.get("status", "")
        if status != "completed":
            progress = self.data.get("progress", 0)
            bt_id = self.data.get("id", "")
            return f"Backtest {bt_id}: {status} (progress: {progress})"

        results = self.data.get("results", self.data)
        trials = results.get("trials", [])
        stats = results.get("statistics", {})

        if not trials and not stats:
            return "(no trials — entry conditions may be too restrictive)"

        # Summary from statistics
        lines: list[str] = []
        if stats:
            lines.append(
                f"**{stats.get('Number of trades', 0)} trades** | "
                f"Win: {stats.get('Win percentage', '?')}% | "
                f"P&L: ${stats.get('Total profit/loss', '?')} | "
                f"Avg premium: ${stats.get('Avg. premium', '?')}"
            )
            lines.append(
                f"Avg win: ${stats.get('Avg. win size', '?')} | "
                f"Avg loss: ${stats.get('Avg. loss size', '?')} | "
                f"Worst: ${stats.get('Worst loss', '?')} | "
                f"Best: ${stats.get('Highest profit', '?')}"
            )
            lines.append(
                f"Avg DIT: {stats.get('Avg. days in trade', '?')} | "
                f"Max DD: {stats.get('Max drawdown', '?')}% on "
                f"{str(stats.get('Max drawdown date', ''))[:10]} | "
                f"BPR/trade: ${stats.get('Avg. BPR per trade', '?')}"
            )

        # Individual trials
        if trials:
            lines.append("")
            for t in trials:
                pnl = float(t.get("profitLoss", 0))
                m = "W" if pnl > 0 else "L"
                o = str(t.get("openDateTime", ""))[:10]
                c = str(t.get("closeDateTime", ""))[:10]
                lines.append(f"{m} {o} -> {c}: ${pnl:.2f}")

        return "\n".join(lines)


BACKTEST_CREATE = Endpoint(
    "/backtests",
    response_model=BacktestResponse,
    base_url=BACKTESTER_URL,
)

BACKTEST_GET = Endpoint(
    "/backtests/{id}",
    response_model=BacktestResponse,
    base_url=BACKTESTER_URL,
)


# ═══════════════════════════════════════════════════════════════
# Account (read-only): accounts, balances, positions, orders
# ═══════════════════════════════════════════════════════════════

# Statuses for an order that is still working (not terminal).
_OPEN_ORDER_STATUSES = {
    "Received",
    "Routed",
    "In Flight",
    "Live",
    "Contingent",
    "Cancel Requested",
    "Replace Requested",
}


@dataclass
class AccountPathRequest(PathRequest, ParamsRequest):
    """GET scoped to a single account via {account_number} path template."""

    account_number: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_number": self.account_number}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class PositionsRequest(AccountPathRequest):
    """Positions need include-marks=true to populate mark/mark-price."""

    def to_params(self) -> dict[str, str]:
        return {"include-marks": "true"}


@dataclass
class AccountsResponse:
    accounts: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountsResponse":
        return cls(accounts=[a for a in (data or []) if not a.get("is-closed")])

    def account_numbers(self) -> list[str]:
        return [a.get("account-number", "") for a in self.accounts if a.get("account-number")]

    def to_output(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account #": a.get("account-number", ""),
                "Nickname": a.get("nickname", ""),
                "Type": a.get("account-type-name", ""),
                "Margin/Cash": a.get("margin-or-cash", ""),
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
            "Account #": d.get("account-number"),
            "Net Liq Value": fmt_number(d.get("net-liquidating-value")),
            "Cash Balance": fmt_number(d.get("cash-balance")),
            "Cash to Withdraw": fmt_number(d.get("cash-available-to-withdraw")),
            "Equity BP": fmt_number(d.get("equity-buying-power")),
            "Derivative BP": fmt_number(d.get("derivative-buying-power")),
            "Long Equity Value": fmt_number(d.get("long-equity-value")),
            "Short Equity Value": fmt_number(d.get("short-equity-value")),
            "Maint. Requirement": fmt_number(d.get("maintenance-requirement")),
            "Pending Cash": fmt_number(d.get("pending-cash")),
        }
        return kv_table({k: v for k, v in fields.items() if v not in (None, "")})


def _tt_position_norm(p: dict) -> NormalizedPosition:
    """Normalize one TastyTrade CurrentPosition into the shared aggregation shape.

    average-open-price / mark-price are per-unit; multiplier is 100 for options,
    1 for equity. pnl = (price-cost)*signed_qty*mult is sign-correct for shorts.
    """
    symbol = p.get("symbol", "")
    is_option = p.get("instrument-type") == "Equity Option"
    qty = to_float_zero(p.get("quantity"))
    signed_qty = -qty if p.get("quantity-direction") == "Short" else qty
    mult = to_float_zero(p.get("multiplier")) or (100 if is_option else 1)
    price = (
        to_float_zero(p.get("mark-price"))
        or to_float_zero(p.get("mark"))
        or to_float_zero(p.get("close-price"))
    )
    cost = to_float_zero(p.get("average-open-price"))
    value = price * signed_qty * mult
    pnl = (price - cost) * signed_qty * mult
    denom = abs(cost) * abs(signed_qty) * mult
    pos = NormalizedPosition(
        symbol=symbol,
        quantity=signed_qty,
        last=price,
        cost=cost,
        value=value,
        pnl=pnl,
        pnl_pct=(pnl / denom * 100) if denom else 0.0,
        is_option=is_option,
        is_cash=False,
    )
    if is_option:
        _, exp, option_type, strike = parse_occ(symbol)
        pos.underlying = p.get("underlying-symbol", "") or symbol
        pos.option_type = option_type
        pos.strike = strike
        pos.expiration = exp
        pos.strategy = ""
    return pos


@dataclass
class AccountPositionsResponse:
    positions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountPositionsResponse":
        return cls(positions=data or [])

    def to_normalized(self) -> list[NormalizedPosition]:
        return [_tt_position_norm(p) for p in self.positions if to_float_zero(p.get("quantity"))]

    def to_output(self) -> str:
        if not self.positions:
            return "(no positions)"
        rows = []
        for p in self.positions:
            n = _tt_position_norm(p)
            row: dict[str, str] = {
                "Symbol": (n.underlying or n.symbol) if n.is_option else n.symbol,
                "Qty": fmt_number(n.quantity, 0),
                "Cost": fmt_number(n.cost),
                "Mark": fmt_number(n.last),
                "Mkt Val": fmt_number(n.value),
                "P&L": fmt_number(n.pnl),
                "P&L %": fmt_number(n.pnl_pct),
            }
            if n.is_option:
                row |= {
                    "Option": n.option_type,
                    "Strike": fmt_number(n.strike),
                    "Exp": n.expiration or "",
                }
            rows.append(row)
        return list_table(rows)


@dataclass
class AccountOrdersResponse:
    orders: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountOrdersResponse":
        return cls(orders=data or [])

    def filter_by_status(self, status: str) -> "AccountOrdersResponse":
        if status == "all":
            return self
        if status == "open":
            keep = [o for o in self.orders if o.get("status") in _OPEN_ORDER_STATUSES]
        else:
            keep = [o for o in self.orders if o.get("status") == status]
        return AccountOrdersResponse(orders=keep)

    @staticmethod
    def _legs(o: dict) -> str:
        parts = []
        for leg in o.get("legs", []):
            parts.append(
                f"{leg.get('action', '')} {leg.get('quantity', '')} {leg.get('symbol', '')}".strip()
            )
        return " / ".join(parts)

    def to_output(self) -> str:
        if not self.orders:
            return "(no orders)"
        rows = []
        for o in self.orders:
            price = o.get("price")
            effect = o.get("price-effect", "")
            rows.append(
                {
                    "Order ID": str(o.get("id", "")),
                    "Underlying": o.get("underlying-symbol", ""),
                    "Type": o.get("order-type", ""),
                    "TIF": o.get("time-in-force", ""),
                    "Price": f"{fmt_number(price)} {effect}".strip() if price else "",
                    "Size": str(o.get("size", "")),
                    "Status": o.get("status", ""),
                    "Legs": self._legs(o),
                }
            )
        return list_table(rows)


ACCOUNTS = Endpoint(
    "/customers/me/accounts",
    cache_ttl=300,
    response_model=AccountsResponse,
    extract=lambda d: [
        it.get("account", {}) for it in d.get("data", {}).get("items", d.get("items", []))
    ],
)

BALANCES = Endpoint(
    "/accounts/{account_number}/balances",
    cache_ttl=60,
    response_model=AccountBalancesResponse,
    extract=lambda d: d.get("data", d),
)

POSITIONS = Endpoint(
    "/accounts/{account_number}/positions",
    cache_ttl=60,
    response_model=AccountPositionsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)

ORDERS = Endpoint(
    "/accounts/{account_number}/orders",
    cache_ttl=30,
    response_model=AccountOrdersResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)
