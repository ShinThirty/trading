"""SnapTrade API endpoint definitions with typed request/response models.

SnapTrade exposes read-only brokerage account data — accounts, positions, and
option holdings — across many brokers (Fidelity/NetBenefits via Akoya). The
response models normalize each account's holdings into the shared position-dict
shape the portfolio aggregation consumes: short options kept as negative value
at the ×100 multiplier, money-market holdings flagged is_cash, and option
underlying/type/strike parsed from the OCC ticker.
"""

import re
from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import CONTRACT_MULTIPLIER, Endpoint, ParamsRequest, PathRequest
from trading_clients.portfolio import NormalizedPosition
from trading_clients.table_helpers import fmt_number, list_table

# OCC option ticker tail: YYMMDD + C/P + 8-digit strike (e.g. "…260710P00027500").
_OCC_TYPE_RE = re.compile(r"\d{6}([CP])\d{8}")

# Only aggregate brokerage/retirement accounts — skip credit cards etc. (LOC).
_INVESTMENT_CATEGORY = "INVESTMENT"


def _pct(pnl: float, basis: float) -> float:
    return (pnl / abs(basis) * 100.0) if basis else 0.0


def _map_position(pos: dict[str, Any]) -> NormalizedPosition:
    """SnapTrade equity/fund position → NormalizedPosition."""
    sym = (pos.get("symbol") or {}).get("symbol") or {}
    units = float(pos.get("units") or 0.0)
    price = float(pos.get("price") or 0.0)
    cost = float(pos.get("average_purchase_price") or 0.0)
    pnl = float(pos.get("open_pnl") or 0.0)
    return NormalizedPosition(
        symbol=sym.get("symbol") or "",
        quantity=units,
        last=price,
        value=units * price,
        cost=cost,
        pnl=pnl,
        pnl_pct=_pct(pnl, cost * units),
        is_option=False,
        is_cash=bool(pos.get("cash_equivalent")),
    )


def _map_option(opt: dict[str, Any]) -> NormalizedPosition:
    """SnapTrade option position → normalized position dict (value at ×100).

    SnapTrade reports `price` (last) per-share but `average_purchase_price`
    per-contract (the ×100 is already baked in — a per-share reading of, e.g.,
    135.34 on a $27.50-strike put is impossible). So the contract multiplier
    applies only to `price`; the per-share cost is avg ÷ 100, and the total cost
    basis is avg × units directly. Multiplying avg by the mult again double-counts
    the ×100 and inflates P&L 100×.
    """
    osym = (opt.get("symbol") or {}).get("option_symbol") or {}
    ticker = osym.get("ticker") or ""
    m = _OCC_TYPE_RE.search(ticker)
    units = float(opt.get("units") or 0.0)
    price = float(opt.get("price") or 0.0)
    avg_per_contract = float(opt.get("average_purchase_price") or 0.0)
    value = units * price * CONTRACT_MULTIPLIER
    cost_basis = avg_per_contract * units
    return NormalizedPosition(
        symbol=ticker,
        underlying=(osym.get("underlying_symbol") or {}).get("symbol") or "",
        quantity=units,
        last=price,
        value=value,
        cost=avg_per_contract / CONTRACT_MULTIPLIER,
        pnl=value - cost_basis,
        pnl_pct=_pct(value - cost_basis, cost_basis),
        is_option=True,
        is_cash=False,
        expiration=osym.get("expiration_date"),
        option_type="call" if (m and m.group(1) == "C") else "put",
        strike=float(osym.get("strike_price") or 0.0),
    )


def _activity_symbol(act: dict[str, Any]) -> str:
    """Display ticker for an activity row: option ticker if present, else the
    equity symbol (UniversalSymbol nests the ticker one or two levels deep)."""
    opt = act.get("option_symbol") or {}
    if opt.get("ticker"):
        return opt["ticker"]
    sym = act.get("symbol") or {}
    inner = sym.get("symbol")
    if isinstance(inner, dict):
        return inner.get("symbol") or ""
    return inner or ""


def _activity_row(act: dict[str, Any]) -> dict[str, str]:
    """One transaction → a display row (amount signed: +inflow / −outflow)."""
    return {
        "Date": (act.get("trade_date") or "")[:10],
        "Type": act.get("type") or "",
        "Symbol": _activity_symbol(act),
        "Units": fmt_number(act.get("units"), 0),
        "Price": fmt_number(act.get("price")),
        "Amount": fmt_number(act.get("amount")),
        "Fee": fmt_number(act.get("fee")),
        "Description": (act.get("description") or "")[:40],
    }


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class AccountPathRequest(PathRequest, ParamsRequest):
    """GET scoped to a single account via {account_id} path template."""

    account_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class AccountActivitiesRequest(PathRequest, ParamsRequest):
    """Transaction history for one account, with pagination + optional filters.

    type is a comma-separated SnapTrade activity filter (e.g. "DIVIDEND,INTEREST"
    or "BUY,SELL"); dates are inclusive YYYY-MM-DD bounds.
    """

    account_id: str
    offset: int = 0
    limit: int = 100
    start_date: str | None = None
    end_date: str | None = None
    type: str | None = None

    def to_path_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}

    def to_params(self) -> dict[str, str]:
        params = {"offset": str(self.offset), "limit": str(self.limit)}
        if self.start_date:
            params["startDate"] = self.start_date
        if self.end_date:
            params["endDate"] = self.end_date
        if self.type:
            params["type"] = self.type
        return params


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class AccountListResponse:
    accounts: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "AccountListResponse":
        return cls(accounts=data or [])

    def investment_accounts(self) -> list[dict]:
        """Brokerage/retirement accounts only (skip credit cards / LOC)."""
        return [a for a in self.accounts if a.get("account_category") == _INVESTMENT_CATEGORY]

    def to_output(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account": a.get("name") or a.get("id") or "",
                "Institution": a.get("institution_name") or "",
                "Type": a.get("raw_type") or a.get("account_category") or "",
                "NLV": fmt_number(((a.get("balance") or {}).get("total") or {}).get("amount")),
                "ID": a.get("id") or "",
            }
            for a in self.accounts
        ]
        return list_table(rows)


@dataclass
class AccountPositionsResponse:
    positions: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "AccountPositionsResponse":
        return cls(positions=data or [])

    def to_normalized(self) -> list[NormalizedPosition]:
        """Normalize equity/fund positions for aggregation (money-market → is_cash)."""
        return [_map_position(p) for p in self.positions]

    def to_output(self) -> str:
        norm = self.to_normalized()
        if not norm:
            return "(no positions)"
        rows = [
            {
                "Symbol": p.symbol,
                "Qty": fmt_number(p.quantity, 0),
                "Last": fmt_number(p.last),
                "Value": fmt_number(p.value),
                "Cash": "✓" if p.is_cash else "",
            }
            for p in norm
        ]
        return list_table(rows)


@dataclass
class AccountOptionsResponse:
    options: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "AccountOptionsResponse":
        return cls(options=data or [])

    def to_normalized(self) -> list[NormalizedPosition]:
        """Normalize option positions for aggregation (short = negative value ×100)."""
        return [_map_option(o) for o in self.options]

    def to_output(self) -> str:
        norm = self.to_normalized()
        if not norm:
            return "(no options)"
        rows = [
            {
                "Symbol": o.symbol,
                "Underlying": o.underlying,
                "Type": o.option_type,
                "Strike": fmt_number(o.strike),
                "Exp": o.expiration or "",
                "Qty": fmt_number(o.quantity, 0),
                "Value": fmt_number(o.value),
            }
            for o in norm
        ]
        return list_table(rows)


@dataclass
class BalancesResponse:
    """Per-currency cash + buying power for one account (usually a single USD row)."""

    balances: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "BalancesResponse":
        return cls(balances=data or [])

    def to_output(self) -> str:
        if not self.balances:
            return "(no balances)"
        rows = [
            {
                "Currency": (b.get("currency") or {}).get("code") or "",
                "Cash": fmt_number(b.get("cash")),
                "Buying Power": fmt_number(b.get("buying_power")),
            }
            for b in self.balances
        ]
        return list_table(rows)


@dataclass
class AccountActivitiesResponse:
    """Paginated transaction history (fills, dividends, interest, option
    assignment/expiration, transfers) — SnapTrade has no order-status read, so
    this is the record of what actually settled."""

    activities: list[dict]
    total: int = 0
    offset: int = 0

    @classmethod
    def from_response(cls, data: Any) -> "AccountActivitiesResponse":
        if isinstance(data, dict):
            pagination = data.get("pagination") or {}
            return cls(
                activities=data.get("data") or [],
                total=int(pagination.get("total") or 0),
                offset=int(pagination.get("offset") or 0),
            )
        return cls(activities=data or [])  # defensive: some responses are a bare list

    def to_output(self) -> str:
        if not self.activities:
            return "(no activities)"
        table = list_table([_activity_row(a) for a in self.activities])
        shown = len(self.activities)
        if self.total > shown:
            last = self.offset + shown
            table += f"\n\nShowing {self.offset + 1}–{last} of {self.total} (paginate via offset)."
        return table


# ═══════════════════════════════════════════════════════════════
# Endpoints (all read-only; brokerages are connected in the dashboard)
# ═══════════════════════════════════════════════════════════════

ACCOUNTS = Endpoint(
    "/accounts",
    cache_ttl=300,
    rate_key="snaptrade",
    response_model=AccountListResponse,
)

BALANCES = Endpoint(
    "/accounts/{account_id}/balances",
    cache_ttl=60,
    rate_key="snaptrade",
    response_model=BalancesResponse,
)

POSITIONS = Endpoint(
    "/accounts/{account_id}/positions",
    cache_ttl=60,
    rate_key="snaptrade",
    response_model=AccountPositionsResponse,
)

OPTIONS = Endpoint(
    "/accounts/{account_id}/options",
    cache_ttl=60,
    rate_key="snaptrade",
    response_model=AccountOptionsResponse,
)

ACTIVITIES = Endpoint(
    "/accounts/{account_id}/activities",
    cache_ttl=30,
    rate_key="snaptrade",
    response_model=AccountActivitiesResponse,
)
