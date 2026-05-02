"""Cross-account portfolio fetching helpers used by tradier/signals/webull tools.

Aggregates account summaries, positions, NLV, and CSP collateral across the
user's Webull accounts (and optional Fidelity CSV folder). Also exposes the
risk-free rate fetch since it conceptually pairs with portfolio-level math.
"""

from fastmcp import Context
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import fred as fred_ep
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    POSITIONS,
    AccountRequest,
    EmptyRequest,
)
from trading_clients.portfolio import AccountSummary, parse_fidelity_folder
from trading_clients.table_helpers import to_float_zero

from trading_mcp.helpers import _fred, _retry, _webull


async def _fetch_accounts(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> tuple[list, dict[str, str]]:
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

        cash_equiv_value = sum(p["value"] for p in positions if p.get("is_cash"))
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

    if fidelity_folder:
        try:
            summaries.extend(await parse_fidelity_folder(fidelity_folder))
        except Exception as e:
            errors["Fidelity"] = str(e)

    return summaries, errors


async def _fetch_all_positions(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> tuple[list[dict], list[str]]:
    webull = _webull(ctx)
    all_positions: list[dict] = []
    errors: list[str] = []

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", aid)
        try:
            pos_resp = await _retry(webull.get, POSITIONS, AccountRequest(aid))
            all_positions.extend(pos_resp.to_normalized())
        except Exception as e:
            errors.append(f"{label}: {e}")

    if fidelity_folder:
        for acct in await parse_fidelity_folder(fidelity_folder):
            all_positions.extend(acct.positions)

    return all_positions, errors


def _compute_csp_collateral(positions: list[dict]) -> float:
    total = 0.0
    for p in positions:
        if not p.get("is_option") or p.get("option_type") != "put":
            continue
        qty = p.get("quantity", 0)
        if qty >= 0:
            continue
        total += p.get("strike", 0) * CONTRACT_MULTIPLIER * abs(qty)
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


async def _fetch_total_nlv(ctx: Context, fidelity_folder: str | None = None) -> float:
    webull = _webull(ctx)
    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    total = 0.0
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        try:
            bal = await _retry(webull.get, BALANCE, AccountRequest(aid))
            total += to_float_zero(bal.net_liquidation)
        except Exception:
            continue

    if fidelity_folder:
        try:
            for acct in await parse_fidelity_folder(fidelity_folder):
                total += acct.nlv
        except Exception:
            pass

    return total
