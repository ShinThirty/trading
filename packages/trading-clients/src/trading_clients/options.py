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


def find_atm_options(
    chain: list[dict], stock_price: float
) -> tuple[dict | None, dict | None]:
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


def expected_move(
    chain: list[dict], stock_price: float
) -> dict[str, float | None]:
    """Compute expected move from ATM straddle price.

    Returns dict with: straddle_price, expected_move, expected_move_pct,
    atm_iv, atm_call_strike, atm_put_strike.
    """
    atm_call, atm_put = find_atm_options(chain, stock_price)
    if not atm_call or not atm_put:
        return {"straddle_price": None, "expected_move": None, "expected_move_pct": None,
                "atm_iv": None, "atm_call_strike": None, "atm_put_strike": None}

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


def strategy_analysis(
    legs: list[dict], stock_price: float
) -> dict:
    """Analyze a multi-leg option strategy.

    Each leg dict should have:
      - strike: float
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - premium: float (mid price per share)
      - delta: float (optional, for probability estimation)
      - quantity: int (number of contracts, default 1)

    Returns dict with: net_premium, max_profit, max_loss, breakevens,
    risk_reward_ratio, probability_of_profit, strategy_type.
    """
    if not legs:
        return {}

    # Compute net premium (positive = credit, negative = debit)
    net_premium = 0.0
    for leg in legs:
        qty = leg.get("quantity", 1)
        premium = leg["premium"]
        if leg["side"] == "sell":
            net_premium += premium * qty
        else:
            net_premium -= premium * qty

    # Determine price range for P&L evaluation
    strikes = [leg["strike"] for leg in legs]
    min_strike = min(strikes)
    max_strike = max(strikes)
    margin = max(max_strike - min_strike, stock_price * 0.3)
    price_low = max(0, min(min_strike, stock_price) - margin)
    price_high = max(max_strike, stock_price) + margin

    # Evaluate P&L at many price points
    steps = 1000
    step_size = (price_high - price_low) / steps
    pnl_points: list[tuple[float, float]] = []

    for i in range(steps + 1):
        price = price_low + i * step_size
        pnl = net_premium  # start with premium received/paid
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
        pnl_points.append((price, pnl * 100))  # per-share → per-contract

    # Max profit and loss
    max_profit = max(p[1] for p in pnl_points)
    max_loss = min(p[1] for p in pnl_points)

    # Find breakeven points (where P&L crosses zero)
    breakevens: list[float] = []
    for i in range(len(pnl_points) - 1):
        p1, pnl1 = pnl_points[i]
        p2, pnl2 = pnl_points[i + 1]
        if (pnl1 <= 0 <= pnl2) or (pnl2 <= 0 <= pnl1):
            # Linear interpolation
            if pnl2 != pnl1:
                be = p1 + (0 - pnl1) * (p2 - p1) / (pnl2 - pnl1)
                breakevens.append(round(be, 2))

    # Risk/reward ratio
    risk_reward = None
    if max_loss < 0 and max_profit > 0:
        risk_reward = abs(max_profit / max_loss)

    # Probability of profit (approximate from delta)
    prob_profit = _estimate_probability_of_profit(legs)

    # Detect strategy type
    strategy_type = _detect_strategy(legs)

    return {
        "strategy_type": strategy_type,
        "net_premium": net_premium,
        "net_premium_total": net_premium * 100,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "risk_reward_ratio": risk_reward,
        "probability_of_profit": prob_profit,
    }


def _estimate_probability_of_profit(legs: list[dict]) -> float | None:
    """Approximate probability of profit from delta."""
    # For single short option: P(profit) ≈ 1 - |delta|
    # For single long option: P(profit) ≈ |delta|
    # For spreads: use the short leg's delta as approximation
    short_legs = [lg for lg in legs if lg["side"] == "sell"]

    if len(legs) == 1:
        leg = legs[0]
        delta = leg.get("delta")
        if delta is None:
            return None
        if leg["side"] == "sell":
            return 1 - abs(delta)
        return abs(delta)

    # For credit spreads: approximate from short leg delta
    if short_legs and all(lg.get("delta") is not None for lg in short_legs):
        probs = []
        for leg in short_legs:
            probs.append(1 - abs(leg["delta"]))
        return sum(probs) / len(probs)

    return None


def _detect_strategy(legs: list[dict]) -> str:
    """Detect common option strategy names from leg structure."""
    n = len(legs)
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

    if n == 2:
        types = {lg["option_type"] for lg in legs}
        sides = {lg["side"] for lg in legs}
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
        if types == {"call", "put"} and len(sides) == 1:
            strikes = {lg["strike"] for lg in legs}
            if len(strikes) == 1:
                return "Straddle" if sides == {"buy"} else "Short Straddle"
            return "Strangle" if sides == {"buy"} else "Short Strangle"

    if n == 4:
        types = [lg["option_type"] for lg in legs]
        if types.count("call") == 2 and types.count("put") == 2:
            short_count = sum(1 for lg in legs if lg["side"] == "sell")
            if short_count == 2:
                return "Iron Condor"

    return f"{n}-Leg Strategy"
