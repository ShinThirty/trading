"""Brokerage account state: balances, positions, instruments, portfolio aggregates."""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients import options as opts
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import snaptrade as sn
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    INSTRUMENTS,
    POSITIONS,
    AccountRequest,
    EmptyRequest,
    GetInstrumentsRequest,
)
from trading_clients.portfolio import (
    PortfolioSummary,
    compact_portfolio_summary,
    compute_cluster_concentration,
    format_cluster_concentration,
    format_greeks_compact,
    format_greeks_detail,
    format_portfolio_summary,
)
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.helpers import _snaptrade, _tastytrade, _tradier, _webull, _write_temp_file
from trading_mcp.portfolio_fetching import (
    _compute_csp_collateral,
    _fetch_accounts,
    _fetch_all_positions,
)

mcp = FastMCP("account-tools")


@mcp.tool()
async def get_webull_balance(ctx: Context, account_id: str) -> str:
    """Get account balance: net liquidation, cash, buying power, market value, day P&L,
    unrealized P&L, margin info.

    account_id: Webull account ID (use get_webull_accounts to find it).
    """
    client = _webull(ctx)
    resp = await client.get(BALANCE, AccountRequest(client.ensure_account_id(account_id)))
    return resp.to_output()


@mcp.tool()
async def get_webull_positions(ctx: Context, account_id: str) -> str:
    """Get all current portfolio holdings including option positions with full leg details
    (strike, expiration, option type, strategy). Returns each position's symbol, type,
    quantity, cost, last price, and unrealized P&L.

    account_id: Webull account ID (use get_webull_accounts to find it).
    """
    client = _webull(ctx)
    resp = await client.get(POSITIONS, AccountRequest(client.ensure_account_id(account_id)))
    return resp.to_output()


@mcp.tool()
async def refresh_webull_token(ctx: Context) -> str:
    """Create a new Webull API access token and save it to ~/.tradingrc.

    Use this when Webull tools fail with 401 errors (token expired after 15 days
    of inactivity). After running this tool, the new token must be verified in the
    Webull App: Menu > Messages > OpenAPI Notifications.

    The token status will be PENDING until verified. Webull tools will fail until
    verification is complete.
    """
    client = _webull(ctx)
    token = await client._create_token()
    return (
        f"New token created: {token[:8]}...\n\n"
        "**Action required:** Verify this token in the Webull App:\n"
        "Menu > Messages > OpenAPI Notifications\n\n"
        "Token is PENDING until verified. Webull tools will fail until then."
    )


@mcp.tool()
async def get_webull_accounts(ctx: Context) -> str:
    """Get all Webull accounts linked to this API key.

    Returns Account ID, Type, and Label for each account.
    Use the 'Account ID' value as the account_id parameter for all other Webull tools.
    """
    return (await _webull(ctx).get(ACCOUNT_LIST, EmptyRequest())).to_output()


@mcp.tool()
async def get_webull_instruments(ctx: Context, symbols: str, category: str = "US_STOCK") -> str:
    """Look up instrument details for symbols: instrument_id, exchange, currency,
    and trading attributes (shortable, fractionable, marginable).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA'). Max 100.
    category: 'US_STOCK' (default) or 'US_ETF'.
    """
    resp = await _webull(ctx).get(INSTRUMENTS, GetInstrumentsRequest(symbols, category))
    return resp.to_output()


# ── Tradier (read-only) ─────────────────────────────────────────


@mcp.tool()
async def get_tradier_profile(ctx: Context) -> str:
    """List all Tradier accounts: account number, type (cash/margin), option
    level, day-trader flag, and status. Use the 'Account #' value as the
    account_id parameter for the other Tradier tools.
    """
    return (await _tradier(ctx).get(t.PROFILE, t.EmptyRequest())).to_output()


@mcp.tool()
async def get_tradier_balance(ctx: Context, account_id: str | None = None) -> str:
    """Get Tradier account balance: net liquidation (equity), total cash, market
    value, long/short market value, and open/close P&L.

    account_id: Tradier account number. Defaults to the configured Tradier
    account (use get_tradier_profile to list them).
    """
    client = _tradier(ctx)
    aid = client.resolve_account_id(account_id)
    return (await client.get(t.BALANCES, t.AccountPathRequest(aid))).to_output()


@mcp.tool()
async def get_tradier_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get Tradier positions: symbol, quantity, cost basis, acquisition date
    (option legs parsed into underlying/strike/expiration).

    Tradier's positions endpoint returns no live price, so market value and P&L
    are not shown here — use get_portfolio_summary for valued, P&L-enriched
    positions across all brokers.

    account_id: Tradier account number. Defaults to the configured account.
    """
    client = _tradier(ctx)
    aid = client.resolve_account_id(account_id)
    return (await client.get(t.POSITIONS, t.AccountPathRequest(aid))).to_output()


@mcp.tool()
async def get_tradier_orders(
    ctx: Context, account_id: str | None = None, status: str = "open"
) -> str:
    """Get Tradier orders (read-only).

    status: 'open' (default — working orders: open/pending/partially_filled),
    'all', or a specific Tradier status (filled, canceled, rejected, expired).
    account_id: Tradier account number. Defaults to the configured account.
    """
    client = _tradier(ctx)
    aid = client.resolve_account_id(account_id)
    resp = await client.get(t.ORDERS, t.AccountPathRequest(aid))
    return resp.filter_by_status(status).to_output()


# ── TastyTrade (read-only) ──────────────────────────────────────


async def _resolve_tastytrade_account(client, account_number: str | None) -> str:
    """Resolve a TastyTrade account number: use the given one, else the sole
    account, else raise listing the choices."""
    if account_number:
        return account_number
    accts = await client.get(tt.ACCOUNTS, tt.EmptyRequest())
    nums = accts.account_numbers()
    if len(nums) == 1:
        return nums[0]
    if not nums:
        raise RuntimeError("No TastyTrade accounts found.")
    raise RuntimeError(
        f"Multiple TastyTrade accounts found ({', '.join(nums)}). Pass account_number to pick one."
    )


@mcp.tool()
async def get_tastytrade_accounts(ctx: Context) -> str:
    """List all TastyTrade accounts: account number, nickname, type, margin/cash.
    Use the 'Account #' value as the account_number parameter for the other
    TastyTrade tools.
    """
    return (await _tastytrade(ctx).get(tt.ACCOUNTS, tt.EmptyRequest())).to_output()


@mcp.tool()
async def get_tastytrade_balance(ctx: Context, account_number: str | None = None) -> str:
    """Get TastyTrade account balance: net liquidating value, cash balance,
    cash available to withdraw, equity/derivative buying power.

    account_number: TastyTrade account number. Omit to use the sole account
    (use get_tastytrade_accounts to list them).
    """
    client = _tastytrade(ctx)
    num = await _resolve_tastytrade_account(client, account_number)
    return (await client.get(tt.BALANCES, tt.AccountPathRequest(num))).to_output()


@mcp.tool()
async def get_tastytrade_positions(ctx: Context, account_number: str | None = None) -> str:
    """Get TastyTrade positions with live marks: quantity, cost, mark, market
    value, and unrealized P&L per position (option legs parsed).

    account_number: TastyTrade account number. Omit to use the sole account.
    """
    client = _tastytrade(ctx)
    num = await _resolve_tastytrade_account(client, account_number)
    return (await client.get(tt.POSITIONS, tt.PositionsRequest(num))).to_output()


@mcp.tool()
async def get_tastytrade_orders(
    ctx: Context, account_number: str | None = None, status: str = "open"
) -> str:
    """Get TastyTrade orders (read-only).

    status: 'open' (default — working orders: Received/Routed/Live/etc.), 'all',
    or a specific TastyTrade status (Filled, Cancelled, Expired, Rejected).
    account_number: TastyTrade account number. Omit to use the sole account.
    """
    client = _tastytrade(ctx)
    num = await _resolve_tastytrade_account(client, account_number)
    resp = await client.get(tt.ORDERS, tt.AccountPathRequest(num))
    return resp.filter_by_status(status).to_output()


# ── SnapTrade (read-only; Fidelity/NetBenefits via Akoya) ───────


def _snaptrade_label(account: dict) -> str:
    """'Institution · Name' header for a SnapTrade account section."""
    name = account.get("name") or account.get("id") or ""
    inst = account.get("institution_name") or ""
    return f"{inst} · {name}" if inst else name


async def _snaptrade_targets(client, account_id: str | None) -> list[dict]:
    """Accounts a scoped SnapTrade tool runs over: the one named by id, else every
    connected investment account (SnapTrade has no single 'default' account)."""
    accts = (await client.get(sn.ACCOUNTS, sn.EmptyRequest())).investment_accounts()
    if account_id:
        picked = [a for a in accts if a.get("id") == account_id]
        if not picked:
            raise RuntimeError(f"No SnapTrade investment account with id {account_id!r}.")
        return picked
    return accts


@mcp.tool()
async def get_snaptrade_accounts(ctx: Context) -> str:
    """List all SnapTrade-connected brokerage accounts (Fidelity/NetBenefits via
    Akoya): institution, name, type, NLV, and the account id. Use the 'ID' value
    as the account_id parameter for the other SnapTrade tools (or omit it there to
    span every account).
    """
    return (await _snaptrade(ctx).get(sn.ACCOUNTS, sn.EmptyRequest())).to_output()


@mcp.tool()
async def get_snaptrade_balances(ctx: Context, account_id: str | None = None) -> str:
    """Get SnapTrade cash + buying power per currency (money-market funds are
    included in cash). Authoritative cash, unlike the aggregation's derived plug.

    account_id: a SnapTrade account id (use get_snaptrade_accounts). Omit to show
    every connected investment account.
    """
    client = _snaptrade(ctx)
    targets = await _snaptrade_targets(client, account_id)
    results = await asyncio.gather(
        *(client.get(sn.BALANCES, sn.AccountPathRequest(a.get("id") or "")) for a in targets)
    )
    sections = [f"## {_snaptrade_label(a)}\n\n{r.to_output()}" for a, r in zip(targets, results)]
    return "\n\n".join(sections) if sections else "(no accounts)"


@mcp.tool()
async def get_snaptrade_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get SnapTrade stock/fund + option positions per account (option legs parsed
    into underlying/type/strike; money-market flagged as cash).

    Positioned market value/P&L come straight from the brokerage feed — use
    get_portfolio_summary for the cross-broker consolidated view.

    account_id: a SnapTrade account id (use get_snaptrade_accounts). Omit to show
    every connected investment account.
    """
    client = _snaptrade(ctx)
    targets = await _snaptrade_targets(client, account_id)

    async def _one(account: dict) -> str:
        aid = account.get("id") or ""
        positions, options = await asyncio.gather(
            client.get(sn.POSITIONS, sn.AccountPathRequest(aid)),
            client.get(sn.OPTIONS, sn.AccountPathRequest(aid)),
        )
        body = positions.to_output()
        opt_out = options.to_output()
        if opt_out != "(no options)":
            body += f"\n\nOptions:\n{opt_out}"
        return f"## {_snaptrade_label(account)}\n\n{body}"

    sections = await asyncio.gather(*(_one(a) for a in targets))
    return "\n\n".join(sections) if sections else "(no accounts)"


@mcp.tool()
async def get_snaptrade_activities(
    ctx: Context,
    account_id: str | None = None,
    activity_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> str:
    """Get SnapTrade transaction history — fills, dividends, interest, option
    assignment/expiration, contributions/withdrawals, transfers. SnapTrade exposes
    no order-status read, so this is the record of what actually settled.

    account_id: a SnapTrade account id (use get_snaptrade_accounts). Omit to span
    every connected investment account.
    activity_type: comma-separated filter, e.g. 'DIVIDEND,INTEREST' or 'BUY,SELL'.
    start_date / end_date: inclusive YYYY-MM-DD bounds (default: full history).
    limit: max rows per account (default 100, max 1000).
    """
    client = _snaptrade(ctx)
    targets = await _snaptrade_targets(client, account_id)
    results = await asyncio.gather(
        *(
            client.get(
                sn.ACTIVITIES,
                sn.AccountActivitiesRequest(
                    a.get("id") or "",
                    limit=limit,
                    start_date=start_date,
                    end_date=end_date,
                    type=activity_type,
                ),
            )
            for a in targets
        )
    )
    sections = [f"## {_snaptrade_label(a)}\n\n{r.to_output()}" for a, r in zip(targets, results)]
    return "\n\n".join(sections) if sections else "(no accounts)"


@mcp.tool()
async def get_portfolio_summary(ctx: Context) -> str:
    """Get a consolidated view across ALL Webull, Tradier, TastyTrade, and
    Fidelity accounts.

    Iterates all Webull accounts (Roth IRA, Individual Cash, Margin, etc.),
    fetches balance and positions for each, and aggregates into one summary.
    Fidelity/NetBenefits accounts are included automatically via SnapTrade when
    [snaptrade] is configured (connect brokerages in the SnapTrade dashboard).

    Note: fetches Webull data sequentially to respect rate limits (~1 req/second).
    """
    summaries, errors = await _fetch_accounts(ctx)
    portfolio = PortfolioSummary(summaries, errors)
    full_output = format_portfolio_summary(portfolio)

    path = await _write_temp_file(full_output, ".md", "portfolio_")

    return compact_portfolio_summary(portfolio, path)


@mcp.tool()
async def get_cluster_concentration(
    ctx: Context,
    tickers: str,
    cap_pct: float = 35.0,
) -> str:
    """Aggregate a correlated cluster's long exposure as a % of total book NLV,
    measured against a target cap.

    Sums long equity market value + long option market value (capital at risk)
    for the given tickers across ALL Webull + Fidelity accounts, then reports the
    cluster's share of total net liquidation value, the cap dollar value at
    cap_pct, and the overage — how much to trim to get back under the cap.
    Short options (CSPs/CCs) are excluded: they are cash-secured premium, not
    deployed long exposure. Fidelity/NetBenefits accounts are included
    automatically via SnapTrade when [snaptrade] is configured.

    Use to size a correlated-cluster cap (e.g. the AI-capex / circular-financing
    cluster) so a group of names that derate together is capped as one exposure.

    tickers: comma-separated cluster members (e.g. 'META,MU,AMZN,NVDA,AVGO,CRDO').
    cap_pct: ceiling as a percent of total book NLV (default 35.0).
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    summaries, _ = await _fetch_accounts(ctx)
    cc = compute_cluster_concentration(summaries, ticker_list, cap_pct)
    return format_cluster_concentration(cc)


@mcp.tool()
async def get_csp_utilization(ctx: Context) -> str:
    """Calculate CSP collateral utilization across all accounts.

    Shows total cash-secured put collateral vs available cash (including SGOV),
    utilization %, remaining capacity, and per-position detail. Use before
    writing new CSPs to check the 60% cash utilization limit. Fidelity accounts
    are included automatically via SnapTrade when [snaptrade] is configured.
    """
    summaries, _ = await _fetch_accounts(ctx)

    csp_rows: list[dict[str, str]] = []
    total_collateral = 0.0
    total_cash = 0.0

    for acct in summaries:
        total_cash += acct.cash
        for p in acct.positions:
            if not p.is_option or p.option_type != "put":
                continue
            if p.quantity >= 0:
                continue
            contracts = abs(p.quantity)
            collateral = p.strike * CONTRACT_MULTIPLIER * contracts
            total_collateral += collateral
            csp_rows.append(
                {
                    "Account": acct.label,
                    "Underlying": p.underlying or p.symbol,
                    "Strike": fmt_number(p.strike),
                    "Exp": p.expiration or "",
                    "Qty": fmt_number(contracts, 0),
                    "Collateral": fmt_number(collateral),
                }
            )

    utilization = (total_collateral / total_cash * 100) if total_cash > 0 else 0
    remaining = total_cash - total_collateral
    status = "OVER LIMIT" if utilization > 60 else "OK"

    summary = kv_table(
        {
            "Total Cash (incl. SGOV)": f"${fmt_number(total_cash)}",
            "Total CSP Collateral": f"${fmt_number(total_collateral)}",
            "Utilization": f"{utilization:.1f}% ({status} — limit 60%)",
            "Remaining Capacity": f"${fmt_number(remaining)}",
        }
    )

    sections = [f"## CSP Collateral Utilization\n\n{summary}"]
    if csp_rows:
        sections.append(f"\n### Open CSPs ({len(csp_rows)} positions)\n")
        sections.append(list_table(csp_rows))
    else:
        sections.append("\nNo open CSP positions found.")

    return "\n".join(sections)


@mcp.tool()
async def get_free_capital(ctx: Context) -> str:
    """Calculate free (deployable) capital across all brokerage accounts.

    For each account shows total cash/money market, CSP collateral tied up,
    liquid holdings (SGOV), and resulting free capital.

    Free Capital = Cash/MM + Liquid Holdings - CSP Collateral

    Rules:
    - Short puts tie up collateral = strike x 100 per contract
    - Covered calls do NOT tie up additional collateral
    - Long options don't tie up collateral
    - SGOV (0-3 month treasury) is treated as liquid/deployable

    Fidelity accounts are included automatically via SnapTrade when [snaptrade]
    is configured.
    """
    summaries, errors = await _fetch_accounts(ctx)

    rows: list[dict[str, str]] = []
    grand_cash = 0.0
    grand_collateral = 0.0
    grand_liquid = 0.0
    grand_free = 0.0

    for acct in summaries:
        acct_liquid = sum(
            p.value for p in acct.positions if p.is_cash and p.symbol.upper() == "SGOV"
        )
        acct_cash_mm = acct.cash - acct_liquid
        acct_collateral = _compute_csp_collateral(acct.positions)
        acct_free = acct.cash - acct_collateral

        rows.append(
            {
                "Account": acct.label,
                "Broker": acct.broker,
                "Cash/MM": f"${fmt_number(acct_cash_mm)}",
                "SGOV": f"${fmt_number(acct_liquid)}",
                "CSP Collateral": f"${fmt_number(acct_collateral)}",
                "Free Capital": f"${fmt_number(acct_free)}",
            }
        )

        grand_cash += acct_cash_mm
        grand_collateral += acct_collateral
        grand_liquid += acct_liquid
        grand_free += acct_free

    rows.append(
        {
            "Account": "**Total**",
            "Broker": "",
            "Cash/MM": f"**${fmt_number(grand_cash)}**",
            "SGOV": f"**${fmt_number(grand_liquid)}**",
            "CSP Collateral": f"**${fmt_number(grand_collateral)}**",
            "Free Capital": f"**${fmt_number(grand_free)}**",
        }
    )

    total_available = grand_cash + grand_liquid
    utilization = (grand_collateral / total_available * 100) if total_available > 0 else 0

    summary = kv_table(
        {
            "Total Available (Cash + SGOV)": f"${fmt_number(total_available)}",
            "Total CSP Collateral": f"${fmt_number(grand_collateral)}",
            "Total Free Capital": f"${fmt_number(grand_free)}",
            "Collateral Utilization": f"{utilization:.1f}%",
        }
    )

    sections = [f"## Free Capital\n\n{summary}"]
    sections.append(f"\n### Per Account\n\n{list_table(rows)}")

    if errors:
        sections.append("\n### Errors")
        for label, err in errors.items():
            sections.append(f"- {label}: {err}")

    return "\n".join(sections)


@mcp.tool()
async def get_portfolio_greeks(ctx: Context) -> str:
    """Get aggregate portfolio Greeks (delta, theta, gamma, vega) across all accounts.

    Fetches all option positions from Webull (and Fidelity via SnapTrade when
    configured), constructs OCC symbols, batch-quotes Greeks from Tradier, and
    aggregates per-underlying and portfolio-wide.

    Requires [webull] and [tradier] sections in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    all_positions, errors = await _fetch_all_positions(ctx)

    option_positions = [p for p in all_positions if p.is_option]
    if not option_positions:
        return "(no option positions found)"

    occ_set: set[str] = set()
    for p in option_positions:
        occ_set.add(opts.build_occ(p.underlying, p.expiration or "", p.option_type, p.strike))

    greeks_by_symbol: dict[str, dict] = {}
    quote_resp = await tradier.get(t.QUOTES, t.GetQuotesRequest(",".join(occ_set), greeks=True))
    for q in quote_resp.quotes:
        greeks_data = q.get("greeks") or {}
        if greeks_data:
            greeks_by_symbol[q.get("symbol", "")] = greeks_data

    result = opts.aggregate_greeks(all_positions, greeks_by_symbol)

    detail = format_greeks_detail(result["totals"], result["by_underlying"])
    path = await _write_temp_file(detail, ".md", "greeks_")

    output = format_greeks_compact(result["totals"], len(option_positions), path)
    if errors:
        output += "\nErrors: " + "; ".join(errors)
    return output
