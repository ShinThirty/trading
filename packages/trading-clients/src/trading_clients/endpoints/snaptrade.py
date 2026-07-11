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
from trading_clients.table_helpers import fmt_number, list_table

# OCC option ticker tail: YYMMDD + C/P + 8-digit strike (e.g. "…260710P00027500").
_OCC_TYPE_RE = re.compile(r"\d{6}([CP])\d{8}")

# Only aggregate brokerage/retirement accounts — skip credit cards etc. (LOC).
_INVESTMENT_CATEGORY = "INVESTMENT"


def _pct(pnl: float, basis: float) -> float:
    return (pnl / abs(basis) * 100.0) if basis else 0.0


def _map_position(pos: dict[str, Any]) -> dict[str, Any]:
    """SnapTrade equity/fund position → normalized position dict."""
    sym = (pos.get("symbol") or {}).get("symbol") or {}
    units = float(pos.get("units") or 0.0)
    price = float(pos.get("price") or 0.0)
    cost = float(pos.get("average_purchase_price") or 0.0)
    pnl = float(pos.get("open_pnl") or 0.0)
    return {
        "symbol": sym.get("symbol") or "",
        "quantity": units,
        "last": price,
        "value": units * price,
        "cost": cost,
        "pnl": pnl,
        "pnl_pct": _pct(pnl, cost * units),
        "is_option": False,
        "is_cash": bool(pos.get("cash_equivalent")),
    }


def _map_option(opt: dict[str, Any]) -> dict[str, Any]:
    """SnapTrade option position → normalized position dict (value at ×100)."""
    osym = (opt.get("symbol") or {}).get("option_symbol") or {}
    ticker = osym.get("ticker") or ""
    m = _OCC_TYPE_RE.search(ticker)
    units = float(opt.get("units") or 0.0)
    price = float(opt.get("price") or 0.0)
    avg = float(opt.get("average_purchase_price") or 0.0)
    value = units * price * CONTRACT_MULTIPLIER
    cost_basis = avg * units * CONTRACT_MULTIPLIER
    return {
        "symbol": ticker,
        "underlying": (osym.get("underlying_symbol") or {}).get("symbol") or "",
        "quantity": units,
        "last": price,
        "value": value,
        "cost": avg,
        "pnl": value - cost_basis,
        "pnl_pct": _pct(value - cost_basis, cost_basis),
        "is_option": True,
        "is_cash": False,
        "expiration": osym.get("expiration_date"),
        "option_type": "call" if (m and m.group(1) == "C") else "put",
        "strike": float(osym.get("strike_price") or 0.0),
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

    def to_normalized(self) -> list[dict]:
        """Normalize equity/fund positions for aggregation (money-market → is_cash)."""
        return [_map_position(p) for p in self.positions]

    def to_output(self) -> str:
        norm = self.to_normalized()
        if not norm:
            return "(no positions)"
        rows = [
            {
                "Symbol": p["symbol"],
                "Qty": fmt_number(p["quantity"], 0),
                "Last": fmt_number(p["last"]),
                "Value": fmt_number(p["value"]),
                "Cash": "✓" if p["is_cash"] else "",
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

    def to_normalized(self) -> list[dict]:
        """Normalize option positions for aggregation (short = negative value ×100)."""
        return [_map_option(o) for o in self.options]

    def to_output(self) -> str:
        norm = self.to_normalized()
        if not norm:
            return "(no options)"
        rows = [
            {
                "Symbol": o["symbol"],
                "Underlying": o["underlying"],
                "Type": o["option_type"],
                "Strike": fmt_number(o["strike"]),
                "Exp": o.get("expiration") or "",
                "Qty": fmt_number(o["quantity"], 0),
                "Value": fmt_number(o["value"]),
            }
            for o in norm
        ]
        return list_table(rows)


# ═══════════════════════════════════════════════════════════════
# Endpoints (all read-only; brokerages are connected in the dashboard)
# ═══════════════════════════════════════════════════════════════

ACCOUNTS = Endpoint(
    "/accounts",
    response_model=AccountListResponse,
)

POSITIONS = Endpoint(
    "/accounts/{account_id}/positions",
    response_model=AccountPositionsResponse,
)

OPTIONS = Endpoint(
    "/accounts/{account_id}/options",
    response_model=AccountOptionsResponse,
)
