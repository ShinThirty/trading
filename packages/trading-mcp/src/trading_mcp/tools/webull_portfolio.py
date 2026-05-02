from datetime import date, timedelta

from fastmcp import Context, FastMCP
from trading_clients import options as opts
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ORDER_HISTORY,
    POSITIONS,
    AccountRequest,
    GetOrderHistoryRequest,
)
from trading_clients.portfolio import (
    PortfolioSummary,
    compact_portfolio_summary,
    format_greeks_compact,
    format_greeks_detail,
    format_portfolio_summary,
)
from trading_clients.table_helpers import fmt_number, kv_table, list_table, to_float_zero

from trading_mcp.helpers import _retry, _tradier, _webull, _write_temp_file
from trading_mcp.portfolio_fetching import (
    _compute_csp_collateral,
    _fetch_accounts,
    _fetch_all_positions,
)

mcp = FastMCP("webull-portfolio-tools")


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
async def get_cc_coverage(
    ctx: Context,
    account_id: str,
) -> str:
    """Calculate covered call coverage ratio per underlying in a Webull account.

    For each stock position with short calls, shows total shares, covered shares,
    uncovered shares, and coverage %. Use before writing new CCs to decide how
    many contracts to sell.

    Coverage guidance from the decision framework:
    - 0-25%: High conviction hold (minimal income, max upside)
    - 50-75%: Growth with income (balanced)
    - 75-100%: Exit/neutral (max income, capped upside)

    account_id: Webull account ID.
    """
    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    pos_resp = await _retry(_webull(ctx).get, POSITIONS, AccountRequest(aid))
    positions = pos_resp.to_normalized()

    shares_by_sym: dict[str, float] = {}
    calls_by_sym: dict[str, list[dict]] = {}

    for p in positions:
        if p.get("is_cash"):
            continue
        if p.get("is_option"):
            if p.get("option_type") == "call" and p.get("quantity", 0) < 0:
                sym = p.get("underlying", "")
                calls_by_sym.setdefault(sym, []).append(p)
        else:
            sym = p.get("symbol", "")
            qty = p.get("quantity", 0)
            if qty > 0:
                shares_by_sym[sym] = shares_by_sym.get(sym, 0) + qty

    all_syms = sorted(set(shares_by_sym) | set(calls_by_sym))
    if not all_syms:
        return "(no stock or short call positions found)"

    cc_rows: list[dict[str, str]] = []
    for sym in all_syms:
        total_shares = shares_by_sym.get(sym, 0)
        calls = calls_by_sym.get(sym, [])
        covered_contracts = sum(abs(c.get("quantity", 0)) for c in calls)
        covered_shares = covered_contracts * CONTRACT_MULTIPLIER
        uncovered = max(0, total_shares - covered_shares)
        coverage_pct = (covered_shares / total_shares * 100) if total_shares > 0 else 0

        if coverage_pct == 0:
            label = "None"
        elif coverage_pct <= 25:
            label = "High conviction"
        elif coverage_pct <= 50:
            label = "Moderate"
        elif coverage_pct <= 75:
            label = "Growth + income"
        else:
            label = "Exit/neutral"

        row: dict[str, str] = {
            "Symbol": sym,
            "Shares": fmt_number(total_shares, 0),
            "Covered": fmt_number(covered_shares, 0),
            "Uncovered": fmt_number(uncovered, 0),
            "Coverage": f"{coverage_pct:.0f}%",
            "Label": label,
        }

        if calls:
            call_details = ", ".join(
                f"${fmt_number(c.get('strike'))} {c.get('expiration', '')}" for c in calls
            )
            row["Calls"] = call_details

        cc_rows.append(row)

    return f"## CC Coverage Ratio\n\n{list_table(cc_rows)}"


@mcp.tool()
async def get_cc_chain_pnl(
    ctx: Context,
    account_id: str,
    symbol: str,
    option_type: str = "call",
    start_date: str | None = None,
) -> str:
    """Calculate the running P&L of a covered call or CSP roll chain.

    Traces all filled option orders for a symbol, sums credits (SELL) and
    debits (BUY), and shows the chain P&L. Useful before rolling to see
    whether the chain is profitable or underwater.

    account_id: Webull account ID.
    symbol: underlying ticker (e.g. 'AMZN').
    option_type: 'call' for covered calls, 'put' for CSPs (default 'call').
    start_date: earliest date to search (YYYY-MM-DD). Defaults to 90 days ago.
    """
    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    if not start_date:
        start_date = (date.today().replace(day=1) - timedelta(days=90)).isoformat()

    response = await client.get(
        ORDER_HISTORY,
        GetOrderHistoryRequest(
            aid, page_size=100, start_date=start_date, end_date=date.today().isoformat()
        ),
    )

    opt_type = option_type.lower()
    chain_orders: list[dict] = []
    for combo in response.combos:
        for o in combo.get("orders", []):
            if o.get("status") != "FILLED":
                continue
            if o.get("instrument_type") != "OPTION":
                continue
            if (o.get("symbol") or "").upper() != symbol.upper():
                continue
            order_legs = o.get("legs", [])
            if not order_legs:
                continue
            leg = order_legs[0]
            if (leg.get("option_type") or "").lower() != opt_type:
                continue
            chain_orders.append(o)

    if not chain_orders:
        return f"(no filled {opt_type} orders for {symbol} since {start_date})"

    chain_orders.sort(key=lambda o: o.get("filled_time_at") or o.get("place_time_at") or "")

    chain_rows: list[dict[str, str]] = []
    total_credit = 0.0
    total_debit = 0.0

    for o in chain_orders:
        side = o.get("side", "")
        qty = to_float_zero(o.get("filled_quantity"))
        price = to_float_zero(o.get("filled_price"))
        amount = price * qty * CONTRACT_MULTIPLIER
        leg = o.get("legs", [{}])[0]

        if side == "SELL":
            total_credit += amount
        else:
            total_debit += amount

        chain_rows.append(
            {
                "Date": (o.get("filled_time_at") or o.get("place_time_at") or "")[:10],
                "Side": side,
                "Strike": fmt_number(leg.get("strike_price")),
                "Exp": leg.get("option_expire_date", ""),
                "Qty": fmt_number(qty, 0),
                "Fill": fmt_number(price),
                "Amount": f"{'+' if side == 'SELL' else '-'}${fmt_number(amount)}",
            }
        )

    chain_pnl = total_credit - total_debit
    pnl_sign = "+" if chain_pnl >= 0 else ""

    type_label = "Covered Call" if opt_type == "call" else "CSP"
    summary = kv_table(
        {
            "Symbol": symbol.upper(),
            "Chain Type": type_label,
            "Total Credits (SELL)": f"+${fmt_number(total_credit)}",
            "Total Debits (BUY)": f"-${fmt_number(total_debit)}",
            "Chain P&L": f"{pnl_sign}${fmt_number(chain_pnl)}",
            "Orders": str(len(chain_orders)),
        }
    )

    sections = [f"## {symbol.upper()} {type_label} Chain P&L\n\n{summary}"]
    sections.append(f"\n### Order History\n\n{list_table(chain_rows)}")

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
