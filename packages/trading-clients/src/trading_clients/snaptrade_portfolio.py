"""Aggregate SnapTrade account data into the shared AccountSummary shape.

SnapTrade (Personal API key) is the source for Fidelity/NetBenefits holdings,
replacing the old manual CSV export. Each connected INVESTMENT account contributes
its authoritative NLV (from the account balance) plus its stock and option
positions, normalized by the endpoint response models the same way the
Webull/Tradier fetchers normalize theirs. Zero-balance accounts are kept (so they
still show up) but skip the position/option fetches.
"""

import asyncio
from typing import Any

from trading_clients.endpoints import snaptrade as ep
from trading_clients.portfolio import AccountSummary
from trading_clients.snaptrade_client import SnapTradeClient


def _account_nlv(account: dict[str, Any]) -> float:
    total = (account.get("balance") or {}).get("total") or {}
    return float(total.get("amount") or 0.0)


def build_account_summary(
    account: dict[str, Any],
    positions: ep.AccountPositionsResponse,
    options: ep.AccountOptionsResponse,
) -> AccountSummary:
    """Compose one account's NLV + normalized positions into an AccountSummary.

    NLV is taken from SnapTrade's authoritative account balance; market value is
    the sum of non-cash positions and cash absorbs the remainder (settled cash +
    money-market), so nlv == cash + market_value exactly.
    """
    nlv = _account_nlv(account)
    mapped = positions.to_normalized() + options.to_normalized()
    market_value = sum(p.value for p in mapped if not p.is_cash)
    return AccountSummary(
        account_id=account.get("id") or "",
        label=account.get("name") or account.get("id") or "",
        broker=account.get("institution_name") or "SnapTrade",
        account_type=account.get("raw_type") or account.get("account_category") or "",
        nlv=nlv,
        cash=nlv - market_value,
        market_value=market_value,
        day_pnl=0.0,  # SnapTrade balances expose no clean day P&L
        unrealized_pnl=sum(p.pnl for p in mapped if not p.is_cash),
        positions=mapped,
    )


async def fetch_snaptrade_accounts(client: SnapTradeClient) -> list[AccountSummary]:
    """All connected INVESTMENT accounts as AccountSummary, positions included."""
    accounts = await client.get(ep.ACCOUNTS, ep.EmptyRequest())

    async def _one(account: dict[str, Any]) -> AccountSummary:
        if _account_nlv(account) == 0.0:
            return build_account_summary(
                account, ep.AccountPositionsResponse([]), ep.AccountOptionsResponse([])
            )
        aid = account.get("id") or ""
        positions, options = await asyncio.gather(
            client.get(ep.POSITIONS, ep.AccountPathRequest(aid)),
            client.get(ep.OPTIONS, ep.AccountPathRequest(aid)),
        )
        return build_account_summary(account, positions, options)

    return list(await asyncio.gather(*(_one(a) for a in accounts.investment_accounts())))


async def fetch_snaptrade_nlv(client: SnapTradeClient) -> float:
    """Total NLV across connected INVESTMENT accounts — balances only, no positions."""
    accounts = await client.get(ep.ACCOUNTS, ep.EmptyRequest())
    return sum(_account_nlv(a) for a in accounts.investment_accounts())
