"""Brokerage account state: balances, positions, instruments, portfolio aggregates."""

from fastmcp import Context, FastMCP
from trading_clients import options as opts
from trading_clients.endpoint import CONTRACT_MULTIPLIER
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

from trading_mcp.helpers import _tastytrade, _tradier, _webull, _write_temp_file
from trading_mcp.portfolio_fetching import (
    _compute_csp_collateral,
    _fetch_accounts,
    _fetch_all_positions,
)

mcp = FastMCP("account-tools")


@mcp.tool()
async def get_account_balance(ctx: Context, account_id: str) -> str:
    """Get account balance: net liquidation, cash, buying power, market value, day P&L,
    unrealized P&L, margin info.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    resp = await client.get(BALANCE, AccountRequest(client.ensure_account_id(account_id)))
    return resp.to_output()


@mcp.tool()
async def get_account_positions(ctx: Context, account_id: str) -> str:
    """Get all current portfolio holdings including option positions with full leg details
    (strike, expiration, option type, strategy). Returns each position's symbol, type,
    quantity, cost, last price, and unrealized P&L.

    account_id: Webull account ID (use get_app_subscriptions to find it).
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
async def get_app_subscriptions(ctx: Context) -> str:
    """Get all Webull accounts linked to this API key.

    Returns Account ID, Type, and Label for each account.
    Use the 'Account ID' value as the account_id parameter for all other Webull tools.
    """
    return (await _webull(ctx).get(ACCOUNT_LIST, EmptyRequest())).to_output()


@mcp.tool()
async def get_instruments(ctx: Context, symbols: str, category: str = "US_STOCK") -> str:
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


@mcp.tool()
async def get_portfolio_summary(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Get a consolidated view across ALL Webull accounts and optionally Fidelity.

    Iterates all Webull accounts (Roth IRA, Individual Cash, Margin, etc.),
    fetches balance and positions for each, and aggregates into one summary.
    Optionally includes Fidelity positions from exported CSVs.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit to show Webull only.

    Note: fetches Webull data sequentially to respect rate limits (~1 req/second).
    """
    summaries, errors = await _fetch_accounts(ctx, fidelity_folder)
    portfolio = PortfolioSummary(summaries, errors)
    full_output = format_portfolio_summary(portfolio)

    path = await _write_temp_file(full_output, ".md", "portfolio_")

    return compact_portfolio_summary(portfolio, path)


@mcp.tool()
async def get_cluster_concentration(
    ctx: Context,
    tickers: str,
    cap_pct: float = 35.0,
    fidelity_folder: str | None = None,
) -> str:
    """Aggregate a correlated cluster's long exposure as a % of total book NLV,
    measured against a target cap.

    Sums long equity market value + long option market value (capital at risk)
    for the given tickers across ALL Webull + Fidelity accounts, then reports the
    cluster's share of total net liquidation value, the cap dollar value at
    cap_pct, and the overage — how much to trim to get back under the cap.
    Short options (CSPs/CCs) are excluded: they are cash-secured premium, not
    deployed long exposure.

    Use to size a correlated-cluster cap (e.g. the AI-capex / circular-financing
    cluster) so a group of names that derate together is capped as one exposure.

    tickers: comma-separated cluster members (e.g. 'META,MU,AMZN,NVDA,AVGO,CRDO').
    cap_pct: ceiling as a percent of total book NLV (default 35.0).
    fidelity_folder: path to the Fidelity Positions CSV folder to include Fidelity
      accounts (e.g. '~/Downloads/fidelity'). Omit for Webull-only.
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    summaries, _ = await _fetch_accounts(ctx, fidelity_folder)
    cc = compute_cluster_concentration(summaries, ticker_list, cap_pct)
    return format_cluster_concentration(cc)


@mcp.tool()
async def get_csp_utilization(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Calculate CSP collateral utilization across all accounts.

    Shows total cash-secured put collateral vs available cash (including SGOV),
    utilization %, remaining capacity, and per-position detail. Use before
    writing new CSPs to check the 60% cash utilization limit.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit to show Webull only.
    """
    summaries, _ = await _fetch_accounts(ctx, fidelity_folder)

    csp_rows: list[dict[str, str]] = []
    total_collateral = 0.0
    total_cash = 0.0

    for acct in summaries:
        total_cash += acct.cash
        for p in acct.positions:
            if not p.get("is_option") or p.get("option_type") != "put":
                continue
            qty = p.get("quantity", 0)
            if qty >= 0:
                continue
            strike = p.get("strike", 0)
            contracts = abs(qty)
            collateral = strike * CONTRACT_MULTIPLIER * contracts
            total_collateral += collateral
            csp_rows.append(
                {
                    "Account": acct.label,
                    "Underlying": p.get("underlying", p.get("symbol", "")),
                    "Strike": fmt_number(strike),
                    "Exp": p.get("expiration", ""),
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
async def get_free_capital(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Calculate free (deployable) capital across all brokerage accounts.

    For each account shows total cash/money market, CSP collateral tied up,
    liquid holdings (SGOV), and resulting free capital.

    Free Capital = Cash/MM + Liquid Holdings - CSP Collateral

    Rules:
    - Short puts tie up collateral = strike x 100 per contract
    - Covered calls do NOT tie up additional collateral
    - Long options don't tie up collateral
    - SGOV (0-3 month treasury) is treated as liquid/deployable

    fidelity_folder: path to folder containing Fidelity Portfolio_Positions_*.csv
      files (e.g. '~/Downloads/fidelity'). Omit to show Webull only.
    """
    summaries, errors = await _fetch_accounts(ctx, fidelity_folder)

    rows: list[dict[str, str]] = []
    grand_cash = 0.0
    grand_collateral = 0.0
    grand_liquid = 0.0
    grand_free = 0.0

    for acct in summaries:
        acct_liquid = sum(
            p.get("value", 0.0)
            for p in acct.positions
            if p.get("is_cash") and p.get("symbol", "").upper() == "SGOV"
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
async def get_portfolio_greeks(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Get aggregate portfolio Greeks (delta, theta, gamma, vega) across all accounts.

    Fetches all option positions from Webull (and optionally Fidelity CSVs),
    constructs OCC symbols, batch-quotes Greeks from Tradier, and aggregates
    per-underlying and portfolio-wide.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit for Webull only.

    Requires [webull] and [tradier] sections in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    all_positions, errors = await _fetch_all_positions(ctx, fidelity_folder)

    option_positions = [p for p in all_positions if p.get("is_option")]
    if not option_positions:
        return "(no option positions found)"

    occ_set: set[str] = set()
    for p in option_positions:
        occ_set.add(opts.build_occ(p["underlying"], p["expiration"], p["option_type"], p["strike"]))

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
