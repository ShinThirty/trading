"""Options analytics computations.

Functions for expected move, historical volatility, and strategy P&L analysis.
Operates on option chain dicts (from Tradier) and OHLCV bar data.
"""

from math import log, sqrt


def historical_volatility(closes: list[float], period: int = 20) -> float | None:
    """Annualized historical volatility from daily closing prices.

    Computes standard deviation of daily log returns, annualized by √252.
    Returns None if insufficient data.
    """
    if len(closes) < period + 1:
        return None
    recent = closes[-(period + 1) :]
    log_returns = [log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    return sqrt(variance) * sqrt(252)


def find_atm_options(chain: list[dict], stock_price: float) -> tuple[dict | None, dict | None]:
    """Find the ATM call and put closest to the current stock price."""
    calls = [o for o in chain if o.get("option_type") == "call"]
    puts = [o for o in chain if o.get("option_type") == "put"]
    atm_call = min(calls, key=lambda o: abs(o["strike"] - stock_price)) if calls else None
    atm_put = min(puts, key=lambda o: abs(o["strike"] - stock_price)) if puts else None
    return atm_call, atm_put


def mid_price(option: dict) -> float:
    """Compute mid price from bid/ask."""
    bid = option.get("bid") or 0
    ask = option.get("ask") or 0
    if bid and ask:
        return (bid + ask) / 2
    return option.get("last") or 0


def expected_move(chain: list[dict], stock_price: float) -> dict[str, float | None]:
    """Compute expected move from ATM straddle price.

    Returns dict with: straddle_price, expected_move, expected_move_pct,
    atm_iv, atm_call_strike, atm_put_strike.
    """
    atm_call, atm_put = find_atm_options(chain, stock_price)
    if not atm_call or not atm_put:
        return {
            "straddle_price": None,
            "expected_move": None,
            "expected_move_pct": None,
            "atm_iv": None,
            "atm_call_strike": None,
            "atm_put_strike": None,
        }

    call_mid = mid_price(atm_call)
    put_mid = mid_price(atm_put)
    straddle = call_mid + put_mid

    call_greeks = atm_call.get("greeks") or {}
    put_greeks = atm_put.get("greeks") or {}
    call_iv = call_greeks.get("mid_iv")
    put_iv = put_greeks.get("mid_iv")
    atm_iv = None
    if call_iv and put_iv:
        atm_iv = (call_iv + put_iv) / 2
    elif call_iv:
        atm_iv = call_iv
    elif put_iv:
        atm_iv = put_iv

    return {
        "straddle_price": straddle,
        "expected_move": straddle,
        "expected_move_pct": (straddle / stock_price * 100) if stock_price else None,
        "atm_iv": atm_iv,
        "atm_call_strike": atm_call["strike"],
        "atm_put_strike": atm_put["strike"],
    }


# ---------------------------------------------------------------------------
# Strategy detection
# ---------------------------------------------------------------------------


def detect_strategy(legs: list[dict], equity_position: dict | None = None) -> str:
    """Detect option strategy name from leg structure and equity position."""
    n = len(legs)

    # Multi-expiration strategies: route to dedicated detection
    expirations = {lg.get("expiration") for lg in legs if lg.get("expiration")}
    if len(expirations) > 1:
        from trading_clients.options_multi_exp import detect_multi_exp_strategy

        return detect_multi_exp_strategy(legs)

    # Equity-aware strategies (checked first)
    if equity_position is not None:
        short_calls = [lg for lg in legs if lg["side"] == "sell" and lg["option_type"] == "call"]
        long_puts = [lg for lg in legs if lg["side"] == "buy" and lg["option_type"] == "put"]
        if short_calls and long_puts and n == 2:
            return "Collar"
        if short_calls and n == 1:
            return "Covered Call"
        if long_puts and n == 1:
            return "Protective Put"

    # Single-leg
    if n == 1:
        side = legs[0]["side"]
        otype = legs[0]["option_type"]
        if side == "sell" and otype == "put":
            return "Cash-Secured Put"
        if side == "sell" and otype == "call":
            return "Short Call"
        if side == "buy" and otype == "call":
            return "Long Call"
        if side == "buy" and otype == "put":
            return "Long Put"

    # Two-leg strategies
    if n == 2:
        types = {lg["option_type"] for lg in legs}
        sides = {lg["side"] for lg in legs}
        qtys = [lg.get("quantity", 1) for lg in legs]

        # Ratio spread / backspread: same type, different quantities
        if len(types) == 1 and len(sides) == 2 and qtys[0] != qtys[1]:
            short_qty = sum(lg.get("quantity", 1) for lg in legs if lg["side"] == "sell")
            long_qty = sum(lg.get("quantity", 1) for lg in legs if lg["side"] == "buy")
            if short_qty > long_qty:
                return "Ratio Spread"
            return "Backspread"

        # Vertical spreads: same type, different sides, equal quantities
        if len(types) == 1 and len(sides) == 2:
            short = [lg for lg in legs if lg["side"] == "sell"][0]
            long = [lg for lg in legs if lg["side"] == "buy"][0]
            if types == {"put"}:
                if short["strike"] > long["strike"]:
                    return "Bull Put Spread"
                return "Bear Put Spread"
            if types == {"call"}:
                if short["strike"] > long["strike"]:
                    return "Bull Call Spread"
                return "Bear Call Spread"

        # Straddle / strangle: different types, same side
        if types == {"call", "put"} and len(sides) == 1:
            strikes = {lg["strike"] for lg in legs}
            if len(strikes) == 1:
                return "Straddle" if sides == {"buy"} else "Short Straddle"
            return "Strangle" if sides == {"buy"} else "Short Strangle"

    # Three-leg: butterfly
    if n == 3:
        types = {lg["option_type"] for lg in legs}
        if len(types) == 1:
            sorted_legs = sorted(legs, key=lambda lg: lg["strike"])
            sides = [lg["side"] for lg in sorted_legs]
            low_qty = sorted_legs[0].get("quantity", 1)
            mid_qty = sorted_legs[1].get("quantity", 1)
            high_qty = sorted_legs[2].get("quantity", 1)
            if mid_qty == low_qty + high_qty:
                if sides == ["buy", "sell", "buy"]:
                    return "Butterfly"
                if sides == ["sell", "buy", "sell"]:
                    return "Short Butterfly"

    # Four-leg strategies
    if n == 4:
        types = [lg["option_type"] for lg in legs]
        call_count = types.count("call")
        put_count = types.count("put")
        short_count = sum(1 for lg in legs if lg["side"] == "sell")

        if call_count == 2 and put_count == 2 and short_count == 2:
            # Iron condor vs iron butterfly: 3 unique strikes = iron butterfly
            strikes = {lg["strike"] for lg in legs}
            if len(strikes) == 3:
                return "Iron Butterfly"
            return "Iron Condor"

        # Condor: all same type, 4 different strikes, sell inner 2
        if len({lg["option_type"] for lg in legs}) == 1:
            sorted_legs = sorted(legs, key=lambda lg: lg["strike"])
            sides = [lg["side"] for lg in sorted_legs]
            if sides == ["buy", "sell", "sell", "buy"]:
                return "Condor"

    return f"{n}-Leg Strategy"


# ---------------------------------------------------------------------------
# Shared P&L evaluation engine
# ---------------------------------------------------------------------------


def _compute_net_premium(legs: list[dict]) -> float:
    """Compute net premium from legs. Positive = credit, negative = debit."""
    net = 0.0
    for leg in legs:
        qty = leg.get("quantity", 1)
        premium = leg["premium"]
        if leg["side"] == "sell":
            net += premium * qty
        else:
            net -= premium * qty
    return net


def _evaluate_pnl(
    legs: list[dict],
    net_premium: float,
    price_low: float,
    price_high: float,
    equity_position: dict | None = None,
    steps: int = 1000,
) -> dict:
    """Evaluate P&L at price points across a range.

    Returns dict with: max_profit, max_loss, breakevens, risk_reward_ratio.
    """
    step_size = (price_high - price_low) / steps
    pnl_points: list[tuple[float, float]] = []

    eq_shares = equity_position["shares"] if equity_position else 0
    eq_cost = equity_position["cost_basis"] if equity_position else 0.0

    for i in range(steps + 1):
        price = price_low + i * step_size
        pnl = net_premium
        for leg in legs:
            qty = leg.get("quantity", 1)
            strike = leg["strike"]
            if leg["option_type"] == "call":
                intrinsic = max(price - strike, 0)
            else:
                intrinsic = max(strike - price, 0)
            if leg["side"] == "sell":
                pnl -= intrinsic * qty
            else:
                pnl += intrinsic * qty
        contract_pnl = pnl * 100
        if equity_position:
            contract_pnl += (price - eq_cost) * eq_shares
        pnl_points.append((price, contract_pnl))

    max_profit = max(p[1] for p in pnl_points)
    max_loss = min(p[1] for p in pnl_points)

    # Breakeven points (where P&L crosses zero)
    breakevens: list[float] = []
    for i in range(len(pnl_points) - 1):
        p1, pnl1 = pnl_points[i]
        p2, pnl2 = pnl_points[i + 1]
        if (pnl1 <= 0 <= pnl2) or (pnl2 <= 0 <= pnl1):
            if pnl2 != pnl1:
                be = p1 + (0 - pnl1) * (p2 - p1) / (pnl2 - pnl1)
                breakevens.append(round(be, 2))

    risk_reward = None
    if max_loss < 0 and max_profit > 0:
        risk_reward = abs(max_profit / max_loss)

    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "risk_reward_ratio": risk_reward,
    }


def _estimate_probability_of_profit(legs: list[dict]) -> float | None:
    """Approximate probability of profit from delta."""
    short_legs = [lg for lg in legs if lg["side"] == "sell"]

    if len(legs) == 1:
        leg = legs[0]
        delta = leg.get("delta")
        if delta is None:
            return None
        if leg["side"] == "sell":
            return 1 - abs(delta)
        return abs(delta)

    if short_legs and all(lg.get("delta") is not None for lg in short_legs):
        probs = []
        for leg in short_legs:
            probs.append(1 - abs(leg["delta"]))
        return sum(probs) / len(probs)

    return None


# ---------------------------------------------------------------------------
# Per-strategy analysis functions
# ---------------------------------------------------------------------------


def _build_result(
    strategy_type: str,
    legs: list[dict],
    net_premium: float,
    pnl: dict,
    **extras: float | None,
) -> dict:
    """Build the standard result dict returned by strategy_analysis()."""
    result = {
        "strategy_type": strategy_type,
        "net_premium": net_premium,
        "net_premium_total": net_premium * 100,
        "max_profit": pnl["max_profit"],
        "max_loss": pnl["max_loss"],
        "breakevens": pnl["breakevens"],
        "risk_reward_ratio": pnl["risk_reward_ratio"],
        "probability_of_profit": _estimate_probability_of_profit(legs),
    }
    for k, v in extras.items():
        if v is not None:
            result[k] = v
    return result


def _analyze_equity_strategy(
    strategy_type: str,
    legs: list[dict],
    stock_price: float,
    equity_position: dict,
) -> dict:
    """Analyze strategies with an equity position (Covered Call, Protective Put, Collar)."""
    net_premium = _compute_net_premium(legs)
    strikes = [lg["strike"] for lg in legs]

    has_short_call = any(lg["side"] == "sell" and lg["option_type"] == "call" for lg in legs)
    has_long_put = any(lg["side"] == "buy" and lg["option_type"] == "put" for lg in legs)

    # Downside: stock can go to zero unless protected by a long put
    price_low = 0.0 if not has_long_put else max(0, min(strikes) - stock_price * 0.1)

    # Upside: capped if short call present, otherwise extends
    if has_short_call:
        price_high = max(strikes) + stock_price * 0.5
    else:
        price_high = stock_price * 2

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high, equity_position)

    # Covered call extras
    extras: dict[str, float | None] = {}
    if strategy_type == "Covered Call":
        cost_basis = equity_position["cost_basis"]
        if cost_basis > 0:
            short_call = [
                lg for lg in legs if lg["side"] == "sell" and lg["option_type"] == "call"
            ][0]
            strike = short_call["strike"]
            premium = short_call["premium"]  # per-share, not scaled by qty
            extras["if_called_return"] = (strike - cost_basis + premium) / cost_basis
            extras["static_return"] = premium / cost_basis

    return _build_result(strategy_type, legs, net_premium, pnl, **extras)


def _analyze_defined_risk(
    strategy_type: str,
    legs: list[dict],
    stock_price: float,
) -> dict:
    """Analyze defined-risk strategies (verticals, iron condors, butterflies, condors)."""
    net_premium = _compute_net_premium(legs)
    strikes = [lg["strike"] for lg in legs]
    margin = max(max(strikes) - min(strikes), stock_price * 0.1)
    price_low = max(0, min(strikes) - margin)
    price_high = max(strikes) + margin

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


def _analyze_undefined_risk(
    strategy_type: str,
    legs: list[dict],
    stock_price: float,
) -> dict:
    """Analyze undefined-risk strategies (CSP, naked call, short straddle/strangle, ratio)."""
    net_premium = _compute_net_premium(legs)

    has_short_put = any(lg["side"] == "sell" and lg["option_type"] == "put" for lg in legs)
    has_short_call = any(lg["side"] == "sell" and lg["option_type"] == "call" for lg in legs)
    strikes = [lg["strike"] for lg in legs]

    price_low = 0.0 if has_short_put else max(0, min(strikes) - stock_price * 0.1)
    price_high = max(strikes) + stock_price if has_short_call else max(strikes) + stock_price * 0.1

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


def _analyze_long_only(
    strategy_type: str,
    legs: list[dict],
    stock_price: float,
) -> dict:
    """Analyze long-only strategies (long call/put, straddle/strangle, backspread)."""
    net_premium = _compute_net_premium(legs)

    has_long_put = any(lg["side"] == "buy" and lg["option_type"] == "put" for lg in legs)
    has_long_call = any(lg["side"] == "buy" and lg["option_type"] == "call" for lg in legs)
    strikes = [lg["strike"] for lg in legs]

    price_low = 0.0 if has_long_put else max(0, min(strikes) - stock_price * 0.1)
    price_high = max(strikes) + stock_price if has_long_call else max(strikes) + stock_price * 0.1

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Strategy type → analysis category
_EQUITY_STRATEGIES = {"Covered Call", "Protective Put", "Collar"}
_DEFINED_RISK_STRATEGIES = {
    "Bull Put Spread",
    "Bear Put Spread",
    "Bull Call Spread",
    "Bear Call Spread",
    "Iron Condor",
    "Iron Butterfly",
    "Butterfly",
    "Short Butterfly",
    "Condor",
}
_UNDEFINED_RISK_STRATEGIES = {
    "Cash-Secured Put",
    "Short Call",
    "Short Straddle",
    "Short Strangle",
    "Ratio Spread",
}
_LONG_ONLY_STRATEGIES = {
    "Long Call",
    "Long Put",
    "Straddle",
    "Strangle",
    "Backspread",
}


def strategy_analysis(
    legs: list[dict],
    stock_price: float,
    equity_position: dict | None = None,
) -> dict:
    """Analyze a multi-leg option strategy.

    Each leg dict should have:
      - strike: float
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - premium: float (mid price per share)
      - delta: float (optional, for probability estimation)
      - quantity: int (number of contracts, default 1)

    equity_position: optional dict with 'shares' (int) and 'cost_basis' (float)
    for strategies involving stock (covered call, protective put, collar).

    Returns dict with: net_premium, max_profit, max_loss, breakevens,
    risk_reward_ratio, probability_of_profit, strategy_type,
    plus strategy-specific extras (e.g. if_called_return, static_return).
    """
    if not legs:
        return {}

    strategy_type = detect_strategy(legs, equity_position)

    if strategy_type in _EQUITY_STRATEGIES and equity_position:
        return _analyze_equity_strategy(strategy_type, legs, stock_price, equity_position)
    if strategy_type in _DEFINED_RISK_STRATEGIES:
        return _analyze_defined_risk(strategy_type, legs, stock_price)
    if strategy_type in _UNDEFINED_RISK_STRATEGIES:
        return _analyze_undefined_risk(strategy_type, legs, stock_price)
    if strategy_type in _LONG_ONLY_STRATEGIES:
        return _analyze_long_only(strategy_type, legs, stock_price)

    # Fallback for unrecognized strategies
    return _analyze_undefined_risk(strategy_type, legs, stock_price)
