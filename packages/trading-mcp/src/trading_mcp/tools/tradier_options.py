import asyncio
from datetime import date
from math import gcd

from fastmcp import Context, FastMCP
from trading_clients import options as opts
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.helpers import _tradier
from trading_mcp.portfolio_fetching import _fetch_risk_free_rate

mcp = FastMCP("tradier-options-tools")


@mcp.tool()
async def get_option_expirations(ctx: Context, symbol: str) -> str:
    """Get all available option expiration dates for an underlying symbol.
    Use this first to discover which expirations are available before fetching
    the full chain.

    symbol: underlying ticker symbol (e.g. 'AAPL', 'SPY', 'TSLA').
    Returns a list of expiration dates as strings (YYYY-MM-DD).

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))).to_output()


@mcp.tool()
async def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.STRIKES, t.GetStrikesRequest(symbol, expiration))).to_output()


@mcp.tool()
async def get_option_chain(
    ctx: Context,
    symbol: str,
    expiration: str,
    greeks: bool = True,
    strike_count: int = 15,
) -> str:
    """Get the option chain for an underlying symbol at a specific expiration.

    Returns calls and puts near the money with: bid/ask with sizes, last price,
    day change/%, volume, open interest, and optionally greeks (IV, delta, gamma,
    theta, vega, rho).

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    greeks: include greeks and IV per contract (default True).
    strike_count: number of strikes above and below ATM to include (default 15).
      Set to 0 for the full unfiltered chain.

    Typical workflow:
    1. get_option_expirations('AAPL') → list of dates
    2. get_option_chain('AAPL', '2026-04-17') → chain with greeks

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    quote_resp, resp = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks)),
    )
    last_price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if resp.options and strike_count > 0 and last_price:
        strikes = sorted({o["strike"] for o in resp.options})
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - last_price))
        lo = max(0, atm_idx - strike_count)
        hi = min(len(strikes), atm_idx + strike_count + 1)
        keep = set(strikes[lo:hi])
        resp.options = [o for o in resp.options if o["strike"] in keep]
    return resp.to_output()


@mcp.tool()
async def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.OPTION_LOOKUP, t.GetLookupRequest(underlying))).to_output()


@mcp.tool()
async def get_expected_move(ctx: Context, symbol: str, expiration: str) -> str:
    """Compute the expected move for a stock at a given option expiration.

    Shows the ATM straddle price (expected 1-sigma move), implied volatility,
    historical volatility, and IV/HV ratio. Useful for sizing positions and
    evaluating whether options are cheap or expensive.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: option expiration date (YYYY-MM-DD, from get_option_expirations).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    quote, chain, history = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks=True)),
        tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily")),
    )

    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    if not chain.options:
        return f"(no option chain for {symbol} at {expiration})"

    em = opts.expected_move(chain.options, stock_price)

    closes = [float(b["close"]) for b in history.days] if history.days else []
    hv20 = opts.historical_volatility(closes, 20)
    hv50 = opts.historical_volatility(closes, 50)

    data: dict[str, str] = {"Stock Price": fmt_number(stock_price)}
    data["Expiration"] = expiration

    if em["straddle_price"] is not None:
        straddle = em["straddle_price"]
        data["ATM Straddle"] = fmt_number(straddle)
        data["Expected Move"] = f"±${fmt_number(straddle)} ({fmt_number(em['expected_move_pct'])}%)"
        data["Expected Range"] = (
            f"${fmt_number(stock_price - straddle)} — ${fmt_number(stock_price + straddle)}"
        )
        data["ATM Strikes"] = f"Call {em['atm_call_strike']}, Put {em['atm_put_strike']}"

    if em["atm_iv"] is not None:
        data["Implied Volatility"] = f"{em['atm_iv'] * 100:.1f}%"

    if hv20 is not None:
        data["Historical Vol (20d)"] = f"{hv20 * 100:.1f}%"
    if hv50 is not None:
        data["Historical Vol (50d)"] = f"{hv50 * 100:.1f}%"

    if em["atm_iv"] is not None and hv20 is not None and hv20 > 0:
        ratio = em["atm_iv"] / hv20
        label = "rich" if ratio > 1.2 else "cheap" if ratio < 0.8 else "fair"
        data["IV/HV Ratio"] = f"{ratio:.2f} ({label})"

    return f"## {symbol} Expected Move ({expiration})\n\n{kv_table(data)}"


@mcp.tool()
async def analyze_option_strategy(
    ctx: Context,
    symbol: str,
    legs: list[dict],
    shares: int | None = None,
    cost_basis: float | None = None,
) -> str:
    """Analyze an option strategy's risk/reward profile.

    Computes max profit, max loss, breakeven points, probability of profit,
    and risk/reward ratio for any single or multi-leg option strategy.

    Supports both single-expiration strategies (verticals, iron condors, etc.) and
    multi-expiration strategies (calendar spreads, diagonal spreads, PMCC, double
    diagonals). For multi-expiration, uses Black-Scholes to value the far-dated leg
    at the near-term expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    legs: list of leg dicts, each with:
      - strike: strike price (e.g. 250)
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - quantity: number of contracts (default 1)
      - expiration: option expiration date (YYYY-MM-DD)
    shares: number of shares held (e.g. 100 for covered call). Omit for option-only.
    cost_basis: per-share cost basis (e.g. 150.00). Required when shares is provided.

    Premiums and deltas are auto-fetched from the live option chain.

    Common strategies:
      CSP: [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"}]
      Bull put spread:
           [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"},
            {"strike": 240, "option_type": "put", "side": "buy",
             "expiration": "2026-06-18"}]
      Calendar spread:
           [{"strike": 100, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"},
            {"strike": 100, "option_type": "call", "side": "buy",
             "expiration": "2026-06-18"}]
      Diagonal / PMCC:
           [{"strike": 90, "option_type": "call", "side": "buy",
             "expiration": "2027-01-15"},
            {"strike": 110, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"}]

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    for i, leg in enumerate(legs):
        if "expiration" not in leg:
            return f"(leg {i + 1} missing required 'expiration' field)"

    equity_position = None
    if shares is not None or cost_basis is not None:
        if shares is None or cost_basis is None:
            return "(both shares and cost_basis are required together)"
        if shares <= 0:
            return "(shares must be positive)"
        if cost_basis <= 0:
            return "(cost_basis must be positive)"
        equity_position = {"shares": shares, "cost_basis": cost_basis}

    quote = await tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    unique_exps = sorted({leg["expiration"] for leg in legs})
    chains: dict[str, list[dict]] = {}
    for exp_date in unique_exps:
        chain = await tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp_date, greeks=True))
        if not chain.options:
            return f"(no option chain for {symbol} at {exp_date})"
        chains[exp_date] = chain.options

    enriched_legs = []
    for leg in legs:
        strike = float(leg["strike"])
        otype = leg["option_type"]
        leg_exp = leg["expiration"]
        chain_options = chains[leg_exp]
        matches = [
            o
            for o in chain_options
            if o.get("option_type") == otype and abs(o["strike"] - strike) < 0.01
        ]
        if not matches:
            return f"(no {otype} at strike {strike} for {leg_exp})"
        opt = matches[0]
        greeks_data = opt.get("greeks") or {}
        enriched_legs.append(
            {
                "strike": strike,
                "option_type": otype,
                "side": leg["side"],
                "quantity": leg.get("quantity", 1),
                "premium": opts.mid_price(opt),
                "delta": greeks_data.get("delta"),
                "iv": greeks_data.get("mid_iv"),
                "bid": opt.get("bid"),
                "ask": opt.get("ask"),
                "spread_pct": opts.bid_ask_spread_pct(opt),
                "occ_symbol": opt.get("symbol", ""),
                "expiration": leg_exp,
            }
        )

    is_multi_exp = len(unique_exps) > 1
    if is_multi_exp:
        from trading_clients.options_multi_exp import analyze_multi_exp_strategy

        risk_free_rate = await _fetch_risk_free_rate(ctx)
        result = analyze_multi_exp_strategy(enriched_legs, stock_price, risk_free_rate)
    else:
        result = opts.strategy_analysis(enriched_legs, stock_price, equity_position)

    leg_rows = []
    if equity_position:
        leg_rows.append(
            {
                "Side": "LONG",
                "Type": "EQUITY",
                "Strike": "",
                "Exp": "",
                "Bid": "",
                "Ask": "",
                "Mid": fmt_number(stock_price),
                "Delta": "1.000",
                "IV": "",
                "Qty": str(equity_position["shares"]),
            }
        )
    for el in enriched_legs:
        row: dict[str, str] = {
            "Side": el["side"].upper(),
            "Type": el["option_type"].upper(),
            "Strike": fmt_number(el["strike"]),
        }
        if is_multi_exp:
            row["Exp"] = el["expiration"]
        row["Bid"] = fmt_number(el["bid"])
        row["Ask"] = fmt_number(el["ask"])
        row["Mid"] = fmt_number(el["premium"])
        sp = el.get("spread_pct")
        row["Spread"] = f"{sp:.0f}%" if sp is not None else ""
        row["Delta"] = fmt_number(el["delta"], 3) if el["delta"] else ""
        row["IV"] = f"{el['iv'] * 100:.1f}%" if el["iv"] else ""
        row["Qty"] = str(el["quantity"])
        leg_rows.append(row)

    data: dict[str, str] = {
        "Strategy": result.get("strategy_type", ""),
        "Stock Price": fmt_number(stock_price),
    }
    dte: int | None = None
    if is_multi_exp:
        data["Near Expiration"] = result.get("near_exp", unique_exps[0])
        data["Far Expiration"] = result.get("far_exp", unique_exps[-1])
    else:
        data["Expiration"] = unique_exps[0]
        try:
            dte = (date.fromisoformat(unique_exps[0]) - date.today()).days
            if dte >= 0:
                data["DTE"] = str(dte)
        except ValueError:
            dte = None

    if equity_position:
        data["Cost Basis"] = fmt_number(equity_position["cost_basis"])
        data["Shares"] = str(equity_position["shares"])

    net = result["net_premium"]
    leg_qtys = [el.get("quantity", 1) for el in enriched_legs]
    units = gcd(*leg_qtys) if leg_qtys else 1
    per_share = net / units
    total = net * CONTRACT_MULTIPLIER
    if net >= 0:
        data["Net Credit"] = f"${fmt_number(per_share)} per share (${fmt_number(total)} total)"
    else:
        data["Net Debit"] = (
            f"${fmt_number(abs(per_share))} per share (${fmt_number(abs(total))} total)"
        )

    data["Max Profit"] = f"${fmt_number(result['max_profit'])}"
    data["Max Loss"] = f"${fmt_number(result['max_loss'])}"

    strategy_type = result.get("strategy_type", "")
    if strategy_type in opts.CREDIT_SPREAD_STRATEGIES and net > 0:
        strikes = sorted({el["strike"] for el in enriched_legs})
        if len(strikes) >= 2:
            if strategy_type in ("Iron Condor", "Iron Butterfly"):
                width = (strikes[-1] - strikes[-2] + strikes[1] - strikes[0]) / 2
            else:
                width = strikes[-1] - strikes[0]
            if width > 0:
                ratio = per_share / width * 100
                data["Credit/Width"] = f"{ratio:.0f}%"

    if not is_multi_exp and net > 0 and dte is not None and dte > 0:
        capital_at_risk: float | None = None
        if strategy_type == "Cash-Secured Put":
            capital_at_risk = sum(
                el["strike"] * el["quantity"] * CONTRACT_MULTIPLIER
                for el in enriched_legs
                if el["side"] == "sell" and el["option_type"] == "put"
            )
        elif strategy_type in opts.CREDIT_SPREAD_STRATEGIES:
            capital_at_risk = abs(result["max_loss"])
        if capital_at_risk and capital_at_risk > 0:
            total_credit = result["max_profit"]
            ann_yld = total_credit / capital_at_risk * 365 / dte * 100
            data["Ann Yield"] = f"{ann_yld:.1f}%"

    if result["breakevens"]:
        data["Breakeven"] = ", ".join(f"${fmt_number(b)}" for b in result["breakevens"])

    if result["risk_reward_ratio"] is not None:
        data["Risk/Reward"] = f"{result['risk_reward_ratio']:.2f}"

    # Lognormal PoP and EV are computed together to share the risk-free rate
    # fetch. PoP is upgraded from delta-based to lognormal-derived where
    # applicable; EV is only meaningful for the credit/debit strategies in
    # opts.EV_STRATEGIES. Falls back to the delta-based PoP from
    # strategy_analysis when lognormal can't be computed.
    lognormal_pop_value: float | None = None
    ev_result: tuple[float, float] | None = None
    if not is_multi_exp and dte is not None and dte > 0:
        rfr = await _fetch_risk_free_rate(ctx)
        if result["breakevens"]:
            lognormal_pop_value = opts.lognormal_pop(
                strategy_type=strategy_type,
                breakevens=result["breakevens"],
                enriched_legs=enriched_legs,
                stock_price=stock_price,
                dte=dte,
                risk_free_rate=rfr,
            )
        if strategy_type in opts.EV_STRATEGIES:
            ev_result = opts.lognormal_ev(
                enriched_legs=enriched_legs,
                strategy_type=strategy_type,
                stock_price=stock_price,
                max_loss=result["max_loss"],
                dte=dte,
                risk_free_rate=rfr,
            )

    pop_value = (
        lognormal_pop_value if lognormal_pop_value is not None else result["probability_of_profit"]
    )
    if pop_value is not None:
        data["P(Profit)"] = f"{pop_value * 100:.0f}%"

    if ev_result is not None:
        expected_pnl, ev_pct = ev_result
        data["Expected Value"] = f"${fmt_number(expected_pnl)}"
        data["EV / $"] = f"{ev_pct:+.2f}%"

    if result.get("if_called_return") is not None:
        data["If-Called Return"] = f"{result['if_called_return'] * 100:.2f}%"
    if result.get("static_return") is not None:
        data["Static Return"] = f"{result['static_return'] * 100:.2f}%"

    if is_multi_exp:
        rfr_pct = f"{risk_free_rate * 100:.2f}%"
        data["Note"] = (
            f"P&L evaluated at near expiration using Black-Scholes (r={rfr_pct}) for far-dated legs"
        )

    wide_spread_legs = [el for el in enriched_legs if (el.get("spread_pct") or 0) > 10]

    sections = [
        f"## {symbol} {result.get('strategy_type', 'Strategy')} Analysis",
        "",
        "### Legs",
        list_table(leg_rows),
        "",
        "### Summary",
        kv_table(data),
    ]
    if wide_spread_legs:
        warnings = []
        for el in wide_spread_legs:
            warnings.append(
                f"- {el['option_type'].upper()} {fmt_number(el['strike'])} {el['expiration']}"
                f": {el['spread_pct']:.0f}% spread (bid {fmt_number(el['bid'])}"
                f" / ask {fmt_number(el['ask'])})"
            )
        sections.extend(
            [
                "",
                "### Liquidity Warning",
                "Wide bid-ask spread (>10% of ask) — mid price may be unreliable:",
                *warnings,
            ]
        )
    return "\n".join(sections)


@mcp.tool()
async def analyze_roll(
    ctx: Context,
    current_symbol: str,
    target_expiration: str,
    target_strike: float | None = None,
    quantity: int = 1,
    chain_credits: float | None = None,
) -> str:
    """Analyze rolling an option position to a new expiration and/or strike.

    Computes cost to close, premium for new position, net credit/debit, DTE change,
    and greek comparison. Designed for covered calls and CSPs that need regular rolling.

    When the roll is a net debit, runs a debit budget analysis with two gates:
    Gate 1 (chain budget): debit must not exceed 50% of accumulated chain credits.
    Gate 2 (vs assignment): debit must be less than the intrinsic value lost at assignment.

    current_symbol: OCC option symbol of current position
      (e.g. 'SMH260501C00410000'). Use get_account_positions to find it,
      or get_option_lookup to construct it.
    target_expiration: expiration date for the new position (YYYY-MM-DD).
      Use get_option_expirations to find available dates.
    target_strike: strike price for new position. Omit to keep same strike
      (horizontal roll). Change for diagonal rolls (roll up/down).
    quantity: number of contracts being rolled (default 1).
    chain_credits: total accumulated chain credits in dollars (from get_cc_chain_pnl).
      Required for Gate 1 debit budget check on net-debit rolls.

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    try:
        underlying, current_exp, option_type, current_strike = opts.parse_occ(current_symbol)
    except (IndexError, ValueError):
        return f"(invalid OCC symbol: {current_symbol})"

    if target_strike is None:
        target_strike = current_strike

    cur_resp, stock_resp, chain = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(current_symbol, greeks=True)),
        tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(underlying, target_expiration, greeks=True)),
    )

    if not cur_resp.quotes:
        return f"(no quote for {current_symbol})"

    stock_price = 0.0
    if stock_resp.quotes:
        stock_price = float(
            stock_resp.quotes[0].get("last") or stock_resp.quotes[0].get("close", 0)
        )

    if not chain.options:
        return f"(no option chain for {underlying} at {target_expiration})"

    matches = [
        o
        for o in chain.options
        if o.get("option_type") == option_type and abs(o["strike"] - target_strike) < 0.01
    ]
    if not matches:
        typed = [o for o in chain.options if o.get("option_type") == option_type]
        if not typed:
            return f"(no {option_type} options at {target_expiration})"
        matches = [min(typed, key=lambda o: abs(o["strike"] - target_strike))]
    new_opt = matches[0]
    actual_strike = new_opt["strike"]

    per_contract_chain = chain_credits / (quantity * CONTRACT_MULTIPLIER) if chain_credits else None
    r = opts.roll_analysis(
        cur_resp.quotes[0],
        new_opt,
        stock_price,
        current_exp,
        target_expiration,
        current_strike,
        actual_strike,
        option_type=option_type,
        chain_credits=per_contract_chain,
    )

    type_label = option_type.upper()
    title = (
        f"## {underlying} Roll: "
        f"{current_exp} {type_label[0]}{current_strike:g} → "
        f"{target_expiration} {type_label[0]}{actual_strike:g}"
    )

    cur_data: dict[str, str] = {
        "Symbol": current_symbol,
        "Type": type_label,
        "Strike": fmt_number(current_strike),
        "Expiration": current_exp,
        "DTE": str(r["cur_dte"]),
        "Bid": fmt_number(r["cur_bid"]),
        "Ask": fmt_number(r["cur_ask"]),
    }
    new_data: dict[str, str] = {
        "Symbol": new_opt.get("symbol", ""),
        "Type": type_label,
        "Strike": fmt_number(actual_strike),
        "Expiration": target_expiration,
        "DTE": str(r["new_dte"]),
        "Bid": fmt_number(r["new_bid"]),
        "Ask": fmt_number(r["new_ask"]),
    }
    for label, d, prefix in [
        ("cur", cur_data, "cur_"),
        ("new", new_data, "new_"),
    ]:
        if r.get(f"{prefix}delta") is not None:
            d["Delta"] = fmt_number(r[f"{prefix}delta"], 4)
        if r.get(f"{prefix}theta") is not None:
            d["Theta"] = fmt_number(r[f"{prefix}theta"], 4)
        if r.get(f"{prefix}mid_iv") is not None:
            d["IV"] = f"{r[f'{prefix}mid_iv'] * 100:.1f}%"

    net = r["net"]
    net_total = net * quantity * CONTRACT_MULTIPLIER
    roll_data: dict[str, str] = {
        "Stock Price": fmt_number(stock_price),
        "Roll Type": r["roll_type"],
        "Cost to Close": f"${fmt_number(r['close_cost'])} (buy at ask)",
        "New Premium": f"${fmt_number(r['open_premium'])} (sell at bid)",
    }
    if net >= 0:
        roll_data["Net Credit"] = f"${fmt_number(net)}/sh (${fmt_number(net_total)} total)"
    else:
        roll_data["Net Debit"] = f"${fmt_number(abs(net))}/sh (${fmt_number(abs(net_total))} total)"
    roll_data["DTE Change"] = (
        f"{r['cur_dte']} → {r['new_dte']} (+{r['new_dte'] - r['cur_dte']} days)"
    )

    for key, label in [("delta", "Delta"), ("theta", "Theta")]:
        if r.get(f"cur_{key}") is not None:
            diff = r[f"new_{key}"] - r[f"cur_{key}"]
            sign = "+" if diff >= 0 else ""
            roll_data[f"{label} Change"] = (
                f"{fmt_number(r[f'cur_{key}'], 4)} → "
                f"{fmt_number(r[f'new_{key}'], 4)} ({sign}{fmt_number(diff, 4)})"
            )
    if r.get("cur_mid_iv") is not None:
        iv_diff = (r["new_mid_iv"] - r["cur_mid_iv"]) * 100
        sign = "+" if iv_diff >= 0 else ""
        roll_data["IV Change"] = (
            f"{r['cur_mid_iv'] * 100:.1f}% → {r['new_mid_iv'] * 100:.1f}% ({sign}{iv_diff:.1f}%)"
        )

    sections = [
        title,
        "",
        "### Current Position",
        kv_table(cur_data),
        "",
        "### New Position",
        kv_table(new_data),
        "",
        "### Roll Summary",
        kv_table(roll_data),
    ]

    if net < 0:
        debit = abs(net)
        debit_total = debit * quantity * CONTRACT_MULTIPLIER
        assignment_cost = r["assignment_cost"]
        assignment_total = assignment_cost * quantity * CONTRACT_MULTIPLIER
        budget_data: dict[str, str] = {}

        if chain_credits is not None:
            budget = chain_credits * 0.5
            budget_data["Chain Credits"] = f"${fmt_number(chain_credits)}"
            budget_data["Debit Budget (50%)"] = f"${fmt_number(budget)}"
            budget_data["Roll Debit"] = f"${fmt_number(debit_total)}"
            gate1 = r.get("gate1_pass", False)
            budget_data["Gate 1: Chain Budget"] = (
                "PASS — debit within budget" if gate1 else "FAIL — debit exceeds 50% of chain"
            )
        else:
            budget_data["Chain Credits"] = "(not provided — run get_cc_chain_pnl)"
            budget_data["Gate 1: Chain Budget"] = "SKIP — no chain data"

        type_label_lower = "called away" if option_type == "call" else "assigned"
        budget_data["Assignment Cost"] = (
            f"${fmt_number(assignment_total)} "
            f"(${fmt_number(assignment_cost)}/sh if {type_label_lower})"
        )
        budget_data["Roll Debit"] = f"${fmt_number(debit_total)}"
        gate2 = r.get("gate2_pass", False)
        if assignment_cost <= 0:
            budget_data["Gate 2: vs Assignment"] = "N/A — option is OTM, no assignment risk"
        else:
            budget_data["Gate 2: vs Assignment"] = (
                "PASS — debit < assignment cost"
                if gate2
                else f"FAIL — cheaper to let {type_label_lower}"
            )

        g1 = r.get("gate1_pass")
        g2 = r.get("gate2_pass", False)
        if g1 is None:
            verdict = "PARTIAL — provide chain_credits to complete analysis" if g2 else "FAIL"
        elif g1 and g2:
            verdict = "PASS — debit roll justified"
        else:
            verdict = "FAIL — let assign or accept the cap"
        budget_data["Verdict"] = verdict

        sections.append("")
        sections.append("### Debit Roll Analysis")
        sections.append(kv_table(budget_data))

    return "\n".join(sections)
