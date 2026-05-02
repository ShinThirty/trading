import asyncio
import math
from datetime import date, timedelta

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import options as opts
from trading_clients.bsm import bsm_price
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table, to_float

from trading_mcp.helpers import (
    _conviction_data,
    _fetch_all_positions,
    _fetch_risk_free_rate,
    _fetch_total_nlv,
    _format_conviction,
    _tastytrade,
    _tradier,
)

mcp = FastMCP("signals-tools")


@mcp.tool()
async def get_conviction_metrics(ctx: Context, symbol: str) -> str:
    """Compute position sizing metrics from the decision framework: PEG ratio,
    drawdown %, operating margin trend, and recommended position size tier.

    Pulls P/E + ROE from Finnhub basic financials, quarterly revenue and operating
    income from SEC filings, and current price / 52W high from Tradier quotes.
    Returns all computed values in one call — replaces manual math across
    get_basic_financials + get_income_statement + get_quote.

    symbol: ticker symbol (e.g. 'ADBE').

    Requires [finnhub] and [tradier] sections in ~/.tradingrc.
    """
    d = await _conviction_data(ctx, symbol)

    data: dict[str, str] = {"Symbol": symbol}

    if d["price"]:
        data["Price"] = f"${d['price']:,.2f}"
    if d["high_52w"]:
        data["52W High"] = f"${d['high_52w']:,.2f}"
    if d["drawdown_pct"] is not None:
        data["Drawdown"] = f"{d['drawdown_pct']:+.1f}%"

    if d["pe"] is not None:
        data["P/E (TTM)"] = f"{d['pe']:.1f}"
    if d["roe"] is not None:
        data["ROE (TTM)"] = f"{d['roe']:.1f}%"
    if d["de"] is not None:
        data["Debt/Equity"] = f"{d['de']:.2f}"

    if d["current_q"] and d["prior_q"]:
        cr = d["current_q"].get("Revenue")
        pr = d["prior_q"].get("Revenue")
        data["Revenue (Current Q)"] = (
            f"${cr / 1e9:.2f}B" if cr and cr >= 1e9 else (f"${cr / 1e6:.0f}M" if cr else "N/A")
        )
        data["Revenue (Prior YoY Q)"] = (
            f"${pr / 1e9:.2f}B" if pr and pr >= 1e9 else (f"${pr / 1e6:.0f}M" if pr else "N/A")
        )
    if d["rev_growth"] is not None:
        data["Revenue Growth (YoY)"] = f"{d['rev_growth']:.1f}%"

    if d["margins"]:
        data["Operating Margin"] = " → ".join(f"{p[:7]} {m:.1f}%" for p, m in d["margins"])
    if d["margin_trend"]:
        data["Margin Trend"] = d["margin_trend"]

    if d["peg"] is not None and d["peg_valid"]:
        data["PEG"] = f"{d['peg']:.2f}"
    elif d["peg_note"]:
        data["PEG"] = d["peg_note"]

    _format_conviction(d, data)

    data["Position Size"] = d["size"]

    return kv_table(data)


@mcp.tool()
async def calculate_position_size(
    ctx: Context, symbol: str, total_assets: float, tier: str = "full"
) -> str:
    """Calculate share count for a position based on sizing tier and total portfolio
    assets. Uses the 10% / 5% / 2% concentration limit from the decision framework.

    Call this after get_conviction_metrics has determined the sizing tier and you are
    ready to deploy capital.

    The output share count is NOT rounded to 100-share lots. If CSP is the recommended
    strategy, tell the user to round up to the nearest 100 shares since each CSP
    contract covers 100 shares.

    symbol: ticker symbol (e.g. 'ADBE').
    total_assets: total portfolio value in the target account (e.g. 500000).
    tier: sizing tier from get_conviction_metrics — 'full', 'standard', or 'reduced'.
    """
    fracs = {"full": 0.10, "standard": 0.05, "reduced": 0.02}
    frac = fracs.get(tier.lower())
    if frac is None:
        return f"Invalid tier '{tier}' — use full, standard, or reduced"

    quote_resp = await _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if not price or price <= 0:
        return f"Could not get price for {symbol}"

    dollars = total_assets * frac
    shares = int(dollars / price)

    return kv_table(
        {
            "Symbol": symbol,
            "Price": f"${price:,.2f}",
            "Total Assets": f"${total_assets:,.0f}",
            "Tier": f"{tier.capitalize()} ({frac:.0%})",
            "Allocation": f"${dollars:,.0f}",
            "Shares": str(shares),
        }
    )


@mcp.tool()
async def calculate_hedge(
    ctx: Context,
    hedge_index: str = "SPY",
    expiration: str | None = None,
    strike: float | None = None,
    hedge_ratio: float = 1.0,
    delta_adjusted: bool = False,
    fidelity_folder: str | None = None,
    crisis_multiplier: float = 1.0,
) -> str:
    """Calculate put contracts needed to hedge the portfolio.

    Computes portfolio beta vs the hedge index from trailing 90-day returns,
    then sizes the hedge and prices it from the current option chain.

    hedge_index: 'SPY' or 'QQQ' (default 'SPY').
    expiration: option expiration (YYYY-MM-DD). Defaults to nearest monthly >=30 DTE.
    strike: put strike. Defaults to ~5% OTM.
    hedge_ratio: fraction to hedge, 0.0-1.0 (default 1.0 = 100%).
    delta_adjusted: if True, divide by put delta for continuous 1:1 hedging.
      Default False = tail-risk mode (sized for full payout when puts go ITM).
    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Includes Fidelity equity + NLV in the
      sizing math. Omit for Webull only.
    crisis_multiplier: amplify portfolio beta to account for correlation spikes
      during crashes (default 1.0 = trailing beta as-is). Recommended 1.25 for
      tail-risk hedges per docs/tail-hedge-playbook.md — tech betas inflate
      ~25% when a real selloff hits.

    Requires [webull] and [tradier] sections in ~/.tradingrc.
    """
    if hedge_index.upper() not in ("SPY", "QQQ"):
        return "hedge_index must be 'SPY' or 'QQQ'"
    hedge_index = hedge_index.upper()
    if crisis_multiplier <= 0:
        return "crisis_multiplier must be > 0"

    tradier = _tradier(ctx)

    positions_task = _fetch_all_positions(ctx, fidelity_folder)
    quote_task = tradier.get(t.QUOTES, t.GetQuotesRequest(hedge_index, greeks=False))
    exp_task = tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(hedge_index))
    bal_task = _fetch_total_nlv(ctx, fidelity_folder)

    (positions, _pos_errors), quote_resp, exp_resp, total_nlv = await asyncio.gather(
        positions_task, quote_task, exp_task, bal_task
    )

    index_price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if not index_price:
        return f"Could not get quote for {hedge_index}"

    equities = [
        p
        for p in positions
        if not p.get("is_option") and not p.get("is_cash") and p.get("value", 0) > 0
    ]
    if not equities:
        return "No equity positions found"

    total_equity = sum(p["value"] for p in equities)
    symbols = list({p["symbol"] for p in equities})

    if not expiration:
        target = date.today() + timedelta(days=30)
        for d in exp_resp.dates:
            if d >= target.isoformat():
                expiration = d
                break
        if not expiration:
            return "No suitable expiration found >=30 DTE"

    lookback_start = (date.today() - timedelta(days=120)).isoformat()
    history_tasks = {
        sym: tradier.get(t.HISTORY, t.GetHistoryRequest(sym, "daily", start=lookback_start))
        for sym in symbols + [hedge_index]
    }
    strikes_task = tradier.get(t.STRIKES, t.GetStrikesRequest(hedge_index, expiration))

    results = await asyncio.gather(*history_tasks.values(), strikes_task, return_exceptions=True)

    history_keys = list(history_tasks.keys())
    history_data: dict[str, list[dict]] = {}
    for i, key in enumerate(history_keys):
        r = results[i]
        if not isinstance(r, Exception) and hasattr(r, "days"):
            history_data[key] = r.days

    strikes_resp = results[-1]
    available_strikes = strikes_resp.strikes if not isinstance(strikes_resp, Exception) else []

    if not strike:
        target_strike = index_price * 0.95
        if available_strikes:
            strike = min(available_strikes, key=lambda s: abs(float(s) - target_strike))
            strike = float(strike)
        else:
            strike = round(target_strike)

    benchmark_bars = history_data.get(hedge_index, [])
    weighted_beta = 0.0
    beta_count = 0
    fallback_count = 0

    for p in equities:
        sym = p["symbol"]
        weight = p["value"] / total_equity
        sym_bars = history_data.get(sym, [])
        b = ta.beta(sym_bars, benchmark_bars)
        if b is not None:
            weighted_beta += weight * b
            beta_count += 1
        else:
            weighted_beta += weight * 1.0
            fallback_count += 1

    portfolio_beta = (total_equity / total_nlv) * weighted_beta if total_nlv > 0 else weighted_beta
    effective_beta = portfolio_beta * crisis_multiplier

    occ = opts.build_occ(hedge_index, expiration, "put", strike)
    try:
        put_resp = await tradier.get(t.QUOTES, t.GetQuotesRequest(occ, greeks=True))
        put_q = put_resp.quotes[0] if put_resp.quotes else {}
    except Exception:
        put_q = {}

    put_ask = put_q.get("ask", 0) or 0
    put_bid = put_q.get("bid", 0) or 0
    put_delta = put_q.get("greeks", {}).get("delta", "")
    put_iv = put_q.get("greeks", {}).get("mid_iv", "")

    notional = (total_nlv * effective_beta * hedge_ratio) / (index_price * CONTRACT_MULTIPLIER)
    if delta_adjusted and put_delta:
        contracts = round(notional / abs(float(put_delta)))
    else:
        # Round UP for tail-risk mode — undersizing is the costly direction
        contracts = math.ceil(notional)
    if contracts < 1:
        contracts = 1

    total_cost = put_ask * CONTRACT_MULTIPLIER * contracts
    cost_pct = (total_cost / total_nlv * 100) if total_nlv > 0 else 0
    drawdown_trigger = (1 - strike / index_price) * 100

    sizing_mode = "delta-adjusted (continuous)" if delta_adjusted else "notional (tail-risk)"

    beta_display = f"{portfolio_beta:.2f}"
    if crisis_multiplier != 1.0:
        beta_display += f" → {effective_beta:.2f} (crisis-adj {crisis_multiplier:.2f}x)"

    hedge_data = {
        "Portfolio Value": f"${total_nlv:,.0f}",
        "Equity Value": f"${total_equity:,.0f}",
        "Equity Symbols": f"{len(symbols)} ({beta_count} with beta, {fallback_count} fallback)",
        "Portfolio Beta": beta_display,
        "Hedge Ratio": f"{hedge_ratio:.0%}",
        "Sizing Mode": sizing_mode,
        "---": "---",
        "Hedge Index": f"{hedge_index} @ ${index_price:,.2f}",
        "Put Strike": f"${strike:,.2f} ({drawdown_trigger:.1f}% OTM)",
        "Expiration": expiration,
        "Contracts": str(contracts),
        "Put Bid / Ask": f"${put_bid:.2f} / ${put_ask:.2f}",
        "Total Cost": f"${total_cost:,.0f} ({cost_pct:.2f}% of portfolio)",
        "Put Delta": f"{put_delta}" if put_delta else "N/A",
        "Put IV": f"{float(put_iv) * 100:.1f}%" if put_iv else "N/A",
    }

    return kv_table(hedge_data)


def _parse_csv_floats(value: str | None, default: list[float]) -> list[float]:
    if not value:
        return default
    out: list[float] = []
    for part in value.split(","):
        s = part.strip()
        if s:
            try:
                out.append(float(s))
            except ValueError:
                continue
    return out or default


@mcp.tool()
async def project_option_grid(
    ctx: Context,
    contract_symbol: str | None = None,
    underlying: str | None = None,
    strike: float | None = None,
    expiration: str | None = None,
    option_type: str | None = None,
    as_of_date: str | None = None,
    spot_pct_changes: str | None = None,
    iv_levels: str | None = None,
    contracts: int | None = None,
    risk_free_rate: float | None = None,
) -> str:
    """Project an option's theoretical value across a grid of (spot price × IV) scenarios.

    Use case: tail-hedge management — see the full distribution of hedge value under
    different SPY drawdown + VIX-spike combinations to inform harvest/maintenance roll
    timing. Also useful for any what-if scenario modeling on existing option positions.

    Modes:
    - Pass `contract_symbol` (OCC, e.g. 'SPY260821P00540000') to auto-detect strike,
      expiration, and option_type. Current spot/IV pulled from get_quote.
    - Or pass `underlying` + `strike` + `expiration` + `option_type` manually.

    Optional params:
    - as_of_date: project to this date (YYYY-MM-DD; default: today). Use to model
      time decay — e.g., "what's this worth in 30 days if X happens?"
    - spot_pct_changes: comma-separated % changes (default: '-30,-25,-20,-15,-10,-5,0,5')
    - iv_levels: comma-separated IV % (default: '20,30,40,50,60,70')
    - contracts: position size — when set, output also shows aggregate $ P&L per cell
    - risk_free_rate: annualized rate (default: pulled from FRED FEDFUNDS series)

    Returns a markdown grid: rows = spot prices, columns = IV levels, cells = option
    value (and multiple from current value).

    Requires [tradier] section in ~/.tradingrc. FRED is optional (falls back to 0%).
    """
    # Resolve contract details
    if contract_symbol:
        try:
            underlying, expiration, option_type, strike = opts.parse_occ(contract_symbol)
        except Exception as e:
            return f"Could not parse contract_symbol '{contract_symbol}': {e}"
    if (
        underlying is None
        or strike is None
        or expiration is None
        or option_type is None
    ):
        return (
            "Specify either contract_symbol or all of: "
            "underlying, strike, expiration, option_type"
        )
    option_type = option_type.lower()

    if option_type not in ("call", "put"):
        return f"option_type must be 'call' or 'put', got '{option_type}'"

    tradier = _tradier(ctx)

    # Fetch current spot + current option state
    spot_task = tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False))
    occ = contract_symbol or opts.build_occ(underlying, expiration, option_type, strike)
    option_task = tradier.get(t.QUOTES, t.GetQuotesRequest(occ, greeks=True))
    rate_task = (
        asyncio.sleep(0, result=risk_free_rate)
        if risk_free_rate is not None
        else _fetch_risk_free_rate(ctx)
    )

    spot_resp, option_resp, rate = await asyncio.gather(
        spot_task, option_task, rate_task, return_exceptions=False
    )

    current_spot = spot_resp.quotes[0].get("last", 0) if spot_resp.quotes else 0
    if not current_spot:
        return f"Could not get current quote for {underlying}"

    current_option_q = option_resp.quotes[0] if option_resp.quotes else {}
    current_value = current_option_q.get("last", 0) or current_option_q.get("ask", 0) or 0
    current_iv_raw = current_option_q.get("greeks", {}).get("mid_iv", "")
    current_iv = float(current_iv_raw) if current_iv_raw else 0.0
    current_delta = current_option_q.get("greeks", {}).get("delta", "")

    # Compute DTE remaining at as_of_date
    if as_of_date:
        try:
            ref_date = date.fromisoformat(as_of_date)
        except ValueError:
            return f"Invalid as_of_date '{as_of_date}' (use YYYY-MM-DD)"
    else:
        ref_date = date.today()
    exp_date = date.fromisoformat(expiration)
    dte_remaining = (exp_date - ref_date).days

    if dte_remaining <= 0:
        return f"Option has expired (or expires today) as of {ref_date}"

    tte_years = dte_remaining / 365.0

    # Parse grid axes
    pct_changes = _parse_csv_floats(
        spot_pct_changes, [-30, -25, -20, -15, -10, -5, 0, 5]
    )
    ivs_pct = _parse_csv_floats(iv_levels, [20, 30, 40, 50, 60, 70])
    ivs_decimal = [iv / 100.0 for iv in ivs_pct]

    # Build header
    header_meta = {
        "Contract": occ,
        "Underlying": f"{underlying} @ ${current_spot:,.2f}",
        "Strike": f"${strike:,.2f} ({option_type})",
        "Expiration": expiration,
        "DTE remaining (as of grid date)": f"{dte_remaining} days",
        "Grid date": ref_date.isoformat(),
        "Current option value": f"${current_value:.2f}",
        "Current IV": f"{current_iv * 100:.1f}%" if current_iv else "N/A",
        "Current delta": str(current_delta) if current_delta else "N/A",
        "Risk-free rate": f"{rate * 100:.2f}% (FRED FEDFUNDS)"
        if risk_free_rate is None
        else f"{rate * 100:.2f}% (override)",
    }
    if contracts:
        header_meta["Contracts"] = str(contracts)

    # Build grid
    lines = [kv_table(header_meta), ""]

    iv_header = " | ".join(f"IV {iv:.0f}%" for iv in ivs_pct)
    lines.append(f"| Spot \\ IV | {iv_header} |")
    lines.append("| --- | " + " | ".join("---" for _ in ivs_pct) + " |")

    for pct in pct_changes:
        scen_spot = current_spot * (1 + pct / 100.0)
        if scen_spot <= 0:
            continue
        row_label = f"${scen_spot:,.0f} ({pct:+.0f}%)"
        cells: list[str] = []
        for iv in ivs_decimal:
            value = bsm_price(scen_spot, strike, tte_years, iv, option_type, rate)
            cell = f"${value:.2f}"
            if current_value > 0:
                multiple = value / current_value
                cell += f" ({multiple:.1f}x)"
            if contracts:
                pnl = (value - current_value) * contracts * CONTRACT_MULTIPLIER
                cell += f" / ${pnl:,.0f}"
            cells.append(cell)
        lines.append(f"| {row_label} | " + " | ".join(cells) + " |")

    if contracts:
        lines.append("")
        lines.append(
            "_Cell format: option_value (multiple_from_current) / position_pnl "
            f"for {contracts} contracts._"
        )
    else:
        lines.append("")
        lines.append("_Cell format: option_value (multiple_from_current). "
                     "Pass `contracts` to also see position P&L._")

    return "\n".join(lines)


@mcp.tool()
async def get_entry_signals(ctx: Context, symbol: str) -> str:
    """Aggregate conviction, IV, and momentum signals for a stock and detect
    circuit breakers from the decision framework (Steps 1-2).

    Combines get_conviction_metrics + get_iv_metrics + get_technical_indicators
    into one call. Automatically flags triggered circuit breakers:
    - Value Trap: RSI <30 but margins compressing
    - Justified Rally: RSI >70 but margins expanding (mirror of Value Trap)
    - Price Dislocation: downtrend but revenue accelerating + ROE >25%
    - Deteriorating Rally: uptrend but revenue declining (mirror of Price Dislocation)
    - FOMO Trap: near ATH + RSI >70 + PEG >3.0
    - Capitulation Bargain: near 52W low + RSI <30 + PEG <1 + margins ok (mirror of FOMO Trap)
    - Front-Run Catalyst: stock rallied >8% in prior 2 weeks (intent-aware)
    - Pre-Priced Selloff: stock dropped >8% in prior 2 weeks (intent-aware)

    Scores four quantitative conviction factors (ROE, Growth, Margins, Cash Flow)
    into Bullish/Moderate/Neutral/Negative tiers. When 2+ factors score Negative,
    conviction is Negative and routes to the bearish framework.

    symbol: ticker symbol (e.g. 'ULTA').

    Requires [finnhub], [tradier], and [tastytrade] sections in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    tastytrade = _tastytrade(ctx)

    conv_task = _conviction_data(ctx, symbol)
    iv_task = tastytrade.get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbol))
    hist_task = tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily"))

    conv_r, iv_r, hist_r = await asyncio.gather(
        conv_task, iv_task, hist_task, return_exceptions=True
    )

    d = conv_r if not isinstance(conv_r, BaseException) else {}
    iv_resp = None if isinstance(iv_r, BaseException) else iv_r
    hist_resp = None if isinstance(hist_r, BaseException) else hist_r

    price = d.get("price")
    drawdown_pct = d.get("drawdown_pct")
    pe = d.get("pe")
    roe = d.get("roe")
    de = d.get("de")
    rev_growth = d.get("rev_growth")
    margins = d.get("margins", [])
    margin_trend = d.get("margin_trend")
    peg = d.get("peg")
    peg_valid = d.get("peg_valid", False)
    size = d.get("size", "Unknown")

    iv_item = iv_resp.items[0] if iv_resp and iv_resp.items else {}
    iv_rank_raw = to_float(iv_item.get("tw-implied-volatility-index-rank"))
    iv_rank = iv_rank_raw * 100 if iv_rank_raw is not None else None
    iv_30d = to_float(iv_item.get("implied-volatility-30-day"))
    hv_30d = to_float(iv_item.get("historical-volatility-30-day"))
    iv_hv = to_float(iv_item.get("iv-hv-30-day-difference"))
    earnings = iv_item.get("earnings", {})
    earnings_date = earnings.get("expected-report-date") if isinstance(earnings, dict) else None
    liq = iv_item.get("liquidity-rating")

    bars = hist_resp.days if hist_resp else []
    closes = [float(b["close"]) for b in bars] if bars else []

    rsi_val = None
    sma50_val = None
    sma200_val = None
    above_sma50 = None
    above_sma200 = None
    rally_2w_pct = None

    if closes:
        rsi_vals = ta.rsi(closes)
        rsi_val = rsi_vals[-1] if rsi_vals else None

        sma50_vals = ta.sma(closes, 50)
        sma50_val = sma50_vals[-1]
        if sma50_val is not None and price:
            above_sma50 = price > sma50_val

        sma200_vals = ta.sma(closes, 200)
        sma200_val = sma200_vals[-1]
        if sma200_val is not None and price:
            above_sma200 = price > sma200_val

        if len(closes) >= 10:
            price_2w_ago = closes[-10]
            if price_2w_ago > 0:
                rally_2w_pct = (closes[-1] - price_2w_ago) / price_2w_ago * 100

    breakers: list[str] = []

    if rsi_val is not None and rsi_val < 30 and margin_trend == "Compressing":
        breakers.append("Value Trap — RSI <30 but margins compressing. Hard stop.")

    if rsi_val is not None and rsi_val > 70 and margin_trend == "Expanding":
        breakers.append(
            "Justified Rally — RSI >70 but margins expanding. "
            "Overbought is justified by improving fundamentals. Don't short this."
        )

    in_downtrend = above_sma50 is False and above_sma200 is False
    if in_downtrend and rev_growth is not None and rev_growth > 0 and roe is not None and roe > 25:
        breakers.append(
            "Price Dislocation — downtrend but revenue accelerating + ROE >25%. "
            "Proceed with Hybrid (CSP-heavy) entry."
        )

    in_uptrend = above_sma50 is True and above_sma200 is True
    if in_uptrend and rev_growth is not None and rev_growth < 0:
        breakers.append(
            "Deteriorating Rally — uptrend but revenue declining. "
            "Technicals mask weakening fundamentals. Bearish setup."
        )

    near_ath = drawdown_pct is not None and drawdown_pct > -5
    if near_ath and rsi_val is not None and rsi_val > 70 and peg is not None and peg > 3.0:
        breakers.append("FOMO Trap — near ATH + RSI >70 + PEG >3. Reduced tier only.")

    near_52w_low = drawdown_pct is not None and drawdown_pct < -40
    if (
        near_52w_low
        and rsi_val is not None
        and rsi_val < 30
        and peg is not None
        and peg > 0
        and peg < 1.0
        and margin_trend != "Compressing"
    ):
        breakers.append(
            "Capitulation Bargain — near 52W low + RSI <30 + PEG <1 + margins not compressing. "
            "Genuine bargain, not a value trap. High-conviction accumulate."
        )

    if rally_2w_pct is not None and rally_2w_pct > 8 and earnings_date:
        breakers.append(
            f"Front-Run Catalyst — rallied {rally_2w_pct:.1f}% in 2 weeks into "
            f"{earnings_date} earnings. Bullish: wait for post-catalyst reaction. "
            f"Bearish: rally provides higher entry for puts/bear spreads."
        )

    if rally_2w_pct is not None and rally_2w_pct < -8 and earnings_date:
        breakers.append(
            f"Pre-Priced Selloff — dropped {rally_2w_pct:.1f}% in 2 weeks into "
            f"{earnings_date} earnings. Bearish: wait for post-catalyst reaction "
            f"(downside may be priced in). "
            f"Bullish: selloff provides cheaper entry for shares/CSPs."
        )

    data: dict[str, str] = {"Symbol": symbol}

    if price:
        data["Price"] = f"${price:,.2f}"
    if drawdown_pct is not None:
        data["Drawdown"] = f"{drawdown_pct:+.1f}%"

    if roe is not None:
        roe_str = f"{roe:.1f}%"
        if de is not None and de > 3:
            roe_str += f" (D/E {de:.1f} — leverage-inflated)"
        data["ROE"] = roe_str
    if pe is not None:
        data["P/E"] = f"{pe:.1f}"
    if rev_growth is not None:
        data["Revenue Growth (YoY)"] = f"{rev_growth:.1f}%"
    if margins:
        data["Op Margin"] = " → ".join(f"{p[:7]} {m:.1f}%" for p, m in margins)
    if margin_trend:
        data["Margin Trend"] = margin_trend
    if peg is not None and peg_valid:
        data["PEG"] = f"{peg:.2f}"

    _format_conviction(d, data)

    data["Size Tier"] = size

    if iv_rank is not None:
        data["IV Rank"] = f"{iv_rank:.0f}%"
    if iv_hv is not None:
        data["IV-HV"] = f"{iv_hv:+.1f}%"
    if iv_30d is not None:
        data["IV 30d"] = f"{iv_30d:.1f}%"
    if hv_30d is not None:
        data["HV 30d"] = f"{hv_30d:.1f}%"
    if earnings_date:
        data["Earnings"] = earnings_date
    if liq is not None:
        data["Liquidity"] = str(liq)

    if rsi_val is not None:
        level = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"
        data["RSI(14)"] = f"{rsi_val:.1f} ({level})"
    if sma50_val is not None:
        rel = "above" if above_sma50 else "below"
        data["SMA(50)"] = f"{sma50_val:.2f} (price {rel})"
    if sma200_val is not None:
        rel = "above" if above_sma200 else "below"
        data["SMA(200)"] = f"{sma200_val:.2f} (price {rel})"
    if rally_2w_pct is not None:
        data["2W Rally"] = f"{rally_2w_pct:+.1f}%"

    if breakers:
        data["Circuit Breakers"] = " | ".join(breakers)
    else:
        data["Circuit Breakers"] = "None"

    return kv_table(data)
