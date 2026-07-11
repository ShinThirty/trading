"""Map SnapTrade API responses into the shared AccountSummary shape.

SnapTrade (Personal API key) is the source for Fidelity/NetBenefits holdings,
replacing the old manual CSV export. list_accounts gives one row per connected
account (with an authoritative NLV); each non-empty INVESTMENT account's stock
and option positions are pulled and mapped into AccountSummary.positions the
same way the Webull/Tradier fetchers do (short options keep negative quantity;
money-market holdings are flagged is_cash).
"""

import asyncio
import re
from typing import Any

from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.portfolio import AccountSummary
from trading_clients.snaptrade_client import SnapTradeClient

# Only aggregate brokerage/retirement accounts — skip credit cards etc. (LOC).
_INVESTMENT_CATEGORY = "INVESTMENT"
# OCC option ticker tail: YYMMDD + C/P + 8-digit strike (e.g. "…260710P00027500").
_OCC_TYPE_RE = re.compile(r"\d{6}([CP])\d{8}")


def _account_nlv(account: dict[str, Any]) -> float:
    total = (account.get("balance") or {}).get("total") or {}
    return float(total.get("amount") or 0.0)


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


def build_account_summary(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    option_positions: list[dict[str, Any]],
) -> AccountSummary:
    """Compose one account's NLV + mapped positions into an AccountSummary.

    NLV is taken from SnapTrade's authoritative account balance; market value is
    the sum of non-cash positions and cash absorbs the remainder (settled cash +
    money-market), so nlv == cash + market_value exactly.
    """
    nlv = _account_nlv(account)
    mapped = [_map_position(p) for p in positions] + [_map_option(o) for o in option_positions]
    market_value = sum(p["value"] for p in mapped if not p["is_cash"])
    return AccountSummary(
        account_id=account.get("id") or "",
        label=account.get("name") or account.get("id") or "",
        broker=account.get("institution_name") or "SnapTrade",
        account_type=account.get("raw_type") or account.get("account_category") or "",
        nlv=nlv,
        cash=nlv - market_value,
        market_value=market_value,
        day_pnl=0.0,  # SnapTrade balances expose no clean day P&L
        unrealized_pnl=sum(p["pnl"] for p in mapped if not p["is_cash"]),
        positions=mapped,
    )


async def fetch_snaptrade_accounts(client: SnapTradeClient) -> list[AccountSummary]:
    """All connected INVESTMENT accounts as AccountSummary, positions included.

    Zero-balance accounts are included (so they still show up) but skip the
    positions/options calls — they contribute nothing to NLV or exposure.
    """
    accounts = await client.list_accounts()
    investment = [a for a in accounts if a.get("account_category") == _INVESTMENT_CATEGORY]

    async def _one(account: dict[str, Any]) -> AccountSummary:
        if _account_nlv(account) == 0.0:
            return build_account_summary(account, [], [])
        aid = account.get("id") or ""
        positions, options = await asyncio.gather(
            client.get_positions(aid),
            client.get_option_positions(aid),
        )
        return build_account_summary(account, positions, options)

    return list(await asyncio.gather(*(_one(a) for a in investment)))


async def fetch_snaptrade_nlv(client: SnapTradeClient) -> float:
    """Total NLV across connected INVESTMENT accounts — balances only, no positions."""
    accounts = await client.list_accounts()
    return sum(
        _account_nlv(a) for a in accounts if a.get("account_category") == _INVESTMENT_CATEGORY
    )
