"""Cross-account portfolio fetching helpers used by tradier/signals/webull tools.

Aggregates account summaries, positions, NLV, and CSP collateral across the
user's Webull, Tradier, TastyTrade, and SnapTrade (Fidelity/NetBenefits)
accounts. Also exposes the risk-free rate fetch since it conceptually pairs with
portfolio-level math.

Per the concurrency rule: providers are fetched concurrently with each other,
but accounts within a single provider are fetched sequentially (rate limits).
"""

import asyncio

from fastmcp import Context
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import fred as fred_ep
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    POSITIONS,
    AccountRequest,
    EmptyRequest,
)
from trading_clients.portfolio import AccountSummary, NormalizedPosition
from trading_clients.snaptrade_portfolio import fetch_snaptrade_accounts, fetch_snaptrade_nlv
from trading_clients.table_helpers import to_float_zero

from trading_mcp.helpers import (
    _fred,
    _optional_snaptrade,
    _optional_tastytrade,
    _optional_tradier,
    _retry,
    _webull,
)

# A single (summaries, errors) result from one provider's fetch.
ProviderResult = tuple[list[AccountSummary], dict[str, str]]


async def _fetch_webull_accounts(ctx: Context) -> ProviderResult:
    webull = _webull(ctx)
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    if not account_list.accounts:
        errors["Webull"] = "No accounts found"

    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", acct.get("account_type", aid))
        atype = acct.get("account_type", "")

        try:
            bal = await _retry(webull.get, BALANCE, AccountRequest(aid))
        except Exception as e:
            errors[label] = str(e)
            continue

        nlv = to_float_zero(bal.net_liquidation)
        cash = to_float_zero(bal.cash_balance)
        mv = to_float_zero(bal.market_value)

        try:
            pos_resp = await _retry(webull.get, POSITIONS, AccountRequest(aid))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        cash_equiv_value = sum(p.value for p in positions if p.is_cash)
        cash += cash_equiv_value
        mv -= cash_equiv_value

        summaries.append(
            AccountSummary(
                account_id=aid,
                label=label,
                broker="Webull",
                account_type=atype,
                nlv=nlv,
                cash=cash,
                market_value=mv,
                day_pnl=to_float_zero(bal.day_pnl),
                unrealized_pnl=to_float_zero(bal.unrealized_pnl),
                positions=positions,
            )
        )

    return summaries, errors


async def _enrich_tradier_positions(
    client, positions: list[NormalizedPosition], errors: dict[str, str], label: str
) -> float:
    """Tradier positions carry no price — fill last/value/pnl from one batched
    quote and return the account's day P&L (Σ quote change × signed qty × mult).

    Short P&L is sign-aware: Tradier reports cost_basis positive even for shorts,
    so pnl = sign(qty)·(|last·qty·mult| − cost_basis), not value − cost_basis.
    """
    if not positions:
        return 0.0
    symbols = sorted({p.symbol for p in positions if p.symbol})
    if not symbols:
        return 0.0
    try:
        q = await client.get(t.QUOTES, t.GetQuotesRequest(",".join(symbols), greeks=False))
    except Exception as e:
        errors[f"{label} (quotes)"] = str(e)
        return 0.0

    last_by = {quote.get("symbol", ""): to_float_zero(quote.get("last")) for quote in q.quotes}
    change_by = {quote.get("symbol", ""): to_float_zero(quote.get("change")) for quote in q.quotes}

    day_pnl = 0.0
    for p in positions:
        qty = p.quantity
        mult = CONTRACT_MULTIPLIER if p.is_option else 1
        last = last_by.get(p.symbol, 0.0)
        cost_basis = p.cost_basis
        sign = 1.0 if qty >= 0 else -1.0
        pnl = sign * (last * abs(qty) * mult - cost_basis)
        p.last = last
        p.value = last * qty * mult
        p.pnl = pnl
        p.pnl_pct = (pnl / abs(cost_basis) * 100) if cost_basis else 0.0
        day_pnl += change_by.get(p.symbol, 0.0) * qty * mult
    return day_pnl


async def _fetch_tradier_accounts(ctx: Context) -> ProviderResult:
    client = _optional_tradier(ctx)
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}
    if client is None:
        return summaries, errors

    try:
        profile = await client.get(t.PROFILE, t.EmptyRequest())
    except Exception as e:
        errors["Tradier"] = str(e)
        return summaries, errors

    for aid in profile.account_numbers():
        label = f"Tradier {aid}"
        try:
            bal = await _retry(client.get, t.BALANCES, t.AccountPathRequest(aid))
        except Exception as e:
            errors[label] = str(e)
            continue
        b = bal.data

        try:
            pos_resp = await _retry(client.get, t.POSITIONS, t.AccountPathRequest(aid))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        day_pnl = await _enrich_tradier_positions(client, positions, errors, label)

        summaries.append(
            AccountSummary(
                account_id=aid,
                label=label,
                broker="Tradier",
                account_type=b.get("account_type", ""),
                nlv=to_float_zero(b.get("total_equity")),
                cash=to_float_zero(b.get("total_cash")),
                market_value=to_float_zero(b.get("market_value")),
                day_pnl=day_pnl,
                unrealized_pnl=to_float_zero(b.get("open_pl")),
                positions=positions,
            )
        )

    return summaries, errors


async def _fetch_tastytrade_accounts(ctx: Context) -> ProviderResult:
    client = _optional_tastytrade(ctx)
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}
    if client is None:
        return summaries, errors

    try:
        accts = await client.get(tt.ACCOUNTS, tt.EmptyRequest())
    except Exception as e:
        errors["TastyTrade"] = str(e)
        return summaries, errors

    meta_by_num = {a.get("account-number", ""): a for a in accts.accounts}
    for num in accts.account_numbers():
        label = f"TastyTrade {num}"
        try:
            bal = await _retry(client.get, tt.BALANCES, tt.AccountPathRequest(num))
        except Exception as e:
            errors[label] = str(e)
            continue
        b = bal.data

        try:
            pos_resp = await _retry(client.get, tt.POSITIONS, tt.PositionsRequest(num))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        nlv = to_float_zero(b.get("net-liquidating-value"))
        cash = to_float_zero(b.get("cash-balance"))
        summaries.append(
            AccountSummary(
                account_id=num,
                label=label,
                broker="TastyTrade",
                account_type=meta_by_num.get(num, {}).get("account-type-name", ""),
                nlv=nlv,
                cash=cash,
                market_value=nlv - cash,
                day_pnl=0.0,  # TastyTrade balances expose no clean day P&L
                unrealized_pnl=sum(p.get("pnl", 0.0) for p in positions),
                positions=positions,
            )
        )

    return summaries, errors


async def _fetch_snaptrade_accounts(ctx: Context) -> ProviderResult:
    """Fidelity/NetBenefits accounts via SnapTrade (Personal API key)."""
    client = _optional_snaptrade(ctx)
    if client is None:
        return [], {}
    try:
        return await fetch_snaptrade_accounts(client), {}
    except Exception as e:
        return [], {"SnapTrade": str(e)}


async def _fetch_accounts(
    ctx: Context,
) -> tuple[list[AccountSummary], dict[str, str]]:
    """Aggregate account summaries across all configured brokers + SnapTrade.

    Providers run concurrently; accounts within a provider run sequentially.
    """
    results = await asyncio.gather(
        _fetch_webull_accounts(ctx),
        _fetch_tradier_accounts(ctx),
        _fetch_tastytrade_accounts(ctx),
        _fetch_snaptrade_accounts(ctx),
        return_exceptions=True,
    )

    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}
    for r in results:
        if isinstance(r, BaseException):
            errors[f"fetch ({type(r).__name__})"] = str(r)
            continue
        provider_summaries, provider_errors = r
        summaries.extend(provider_summaries)
        errors.update(provider_errors)

    return summaries, errors


async def _fetch_all_positions(
    ctx: Context,
) -> tuple[list[NormalizedPosition], list[str]]:
    """Flatten every normalized position across all brokers (for greeks/hedge).

    Reuses _fetch_accounts so Tradier positions arrive already quote-enriched.
    """
    summaries, errors = await _fetch_accounts(ctx)
    all_positions = [p for acct in summaries for p in acct.positions]
    return all_positions, [f"{k}: {v}" for k, v in errors.items()]


def _compute_csp_collateral(positions: list[NormalizedPosition]) -> float:
    total = 0.0
    for p in positions:
        if not p.is_option or p.option_type != "put":
            continue
        if p.quantity >= 0:
            continue
        total += p.strike * CONTRACT_MULTIPLIER * abs(p.quantity)
    return total


async def _fetch_risk_free_rate(ctx: Context) -> float:
    """Pull current Fed Funds rate from FRED for use as r in BSM pricing.

    Returns the rate as a decimal (e.g. 0.045 for 4.5%). Returns 0.0 on any
    failure (FRED not configured, network error, missing observation).

    Pairs conceptually with `trading_clients.bsm.bsm_price` — that function
    takes `r` as input; this function provides the live market value.
    """
    try:
        fred_client = _fred(ctx)
        obs = await fred_client.get(
            fred_ep.OBSERVATIONS, fred_ep.GetObservationsRequest("FEDFUNDS", 1)
        )
        if obs.observations:
            val = obs.observations[0].get("value")
            if val:
                return float(val) / 100.0
    except Exception:
        pass
    return 0.0


async def _fetch_total_nlv(ctx: Context) -> float:
    """Sum net liquidation value across all brokers + SnapTrade.

    Kept lightweight (balances only, no positions/quotes) so it can run
    concurrently with _fetch_all_positions without duplicating the heavy fetch.
    """
    total = 0.0

    webull = _webull(ctx)
    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    for acct in account_list.accounts:
        try:
            bal = await _retry(webull.get, BALANCE, AccountRequest(acct.get("account_id", "")))
            total += to_float_zero(bal.net_liquidation)
        except Exception:
            continue

    tradier = _optional_tradier(ctx)
    if tradier is not None:
        try:
            profile = await tradier.get(t.PROFILE, t.EmptyRequest())
            for aid in profile.account_numbers():
                bal = await _retry(tradier.get, t.BALANCES, t.AccountPathRequest(aid))
                total += to_float_zero(bal.data.get("total_equity"))
        except Exception:
            pass

    tasty = _optional_tastytrade(ctx)
    if tasty is not None:
        try:
            accts = await tasty.get(tt.ACCOUNTS, tt.EmptyRequest())
            for num in accts.account_numbers():
                bal = await _retry(tasty.get, tt.BALANCES, tt.AccountPathRequest(num))
                total += to_float_zero(bal.data.get("net-liquidating-value"))
        except Exception:
            pass

    snaptrade = _optional_snaptrade(ctx)
    if snaptrade is not None:
        try:
            total += await fetch_snaptrade_nlv(snaptrade)
        except Exception:
            pass

    return total
