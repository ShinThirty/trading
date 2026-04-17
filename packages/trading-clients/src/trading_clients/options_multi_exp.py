"""Multi-expiration options strategy analysis.

Handles calendar spreads, diagonal spreads (PMCC), double diagonals, and reverse
calendars — strategies where legs have different expiration dates. Uses Black-Scholes
to estimate the far-dated leg's value at the near-term expiration.

Single-expiration strategies are handled by options.py.
"""

from datetime import date
from math import erf, log, sqrt

from trading_clients.options import _build_result, _compute_net_premium

# ---------------------------------------------------------------------------
# Black-Scholes-Merton pricer
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (exact, no scipy needed)."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _bsm_price(
    stock_price: float,
    strike: float,
    tte: float,
    iv: float,
    option_type: str,
    r: float = 0.0,
) -> float:
    """Black-Scholes option price. tte in years, r = annualized risk-free rate."""
    if tte <= 0 or iv <= 0:
        if option_type == "call":
            return max(stock_price - strike, 0.0)
        return max(strike - stock_price, 0.0)

    from math import exp

    sqrt_t = sqrt(tte)
    d1 = (log(stock_price / strike) + (r + 0.5 * iv * iv) * tte) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    discount = exp(-r * tte)

    if option_type == "call":
        return stock_price * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    return strike * discount * _norm_cdf(-d2) - stock_price * _norm_cdf(-d1)


# ---------------------------------------------------------------------------
# Multi-expiration strategy detection
# ---------------------------------------------------------------------------


def detect_multi_exp_strategy(legs: list[dict]) -> str:
    """Detect strategy name for legs spanning multiple expirations."""
    n = len(legs)
    expirations = sorted({lg["expiration"] for lg in legs})

    if len(expirations) != 2:
        return f"{n}-Leg Multi-Exp Strategy"

    near_exp, far_exp = expirations
    near_legs = [lg for lg in legs if lg["expiration"] == near_exp]
    far_legs = [lg for lg in legs if lg["expiration"] == far_exp]

    # Two-leg multi-expiration: calendar or diagonal
    if n == 2 and len(near_legs) == 1 and len(far_legs) == 1:
        nl, fl = near_legs[0], far_legs[0]

        # Must be same type (both calls or both puts)
        if nl["option_type"] != fl["option_type"]:
            return "2-Leg Multi-Exp Strategy"

        # Must be opposite sides
        if nl["side"] == fl["side"]:
            return "2-Leg Multi-Exp Strategy"

        same_strike = abs(nl["strike"] - fl["strike"]) < 0.01

        if same_strike:
            if nl["side"] == "sell":
                return "Calendar Spread"
            return "Reverse Calendar"
        else:
            if nl["side"] == "sell":
                return "Diagonal Spread"
            return "Reverse Diagonal"

    # Four-leg multi-expiration: double diagonal
    if n == 4 and len(near_legs) == 2 and len(far_legs) == 2:
        near_types = {lg["option_type"] for lg in near_legs}
        far_types = {lg["option_type"] for lg in far_legs}
        near_sides = {lg["side"] for lg in near_legs}
        far_sides = {lg["side"] for lg in far_legs}

        if (
            near_types == {"call", "put"}
            and far_types == {"call", "put"}
            and near_sides == {"sell"}
            and far_sides == {"buy"}
        ):
            return "Double Diagonal"

    return f"{n}-Leg Multi-Exp Strategy"


# ---------------------------------------------------------------------------
# Multi-expiration P&L evaluation
# ---------------------------------------------------------------------------


def _days_between(date_str_a: str, date_str_b: str) -> int:
    """Days from date_str_a to date_str_b (positive if b is later)."""
    a = date.fromisoformat(date_str_a)
    b = date.fromisoformat(date_str_b)
    return (b - a).days


def _evaluate_pnl_multi_exp(
    legs: list[dict],
    net_premium: float,
    price_low: float,
    price_high: float,
    near_exp: str,
    far_exp: str,
    risk_free_rate: float = 0.0,
    steps: int = 1000,
) -> dict:
    """Evaluate P&L at the near-term expiration for multi-expiration strategies.

    Near-term legs: valued at intrinsic (they're expiring).
    Far-term legs: valued at BSM theoretical price with remaining time to far expiration.

    Returns dict with: max_profit, max_loss, breakevens, risk_reward_ratio.
    """
    remaining_days = _days_between(near_exp, far_exp)
    remaining_years = remaining_days / 365.0

    step_size = (price_high - price_low) / steps
    pnl_points: list[tuple[float, float]] = []

    for i in range(steps + 1):
        price = price_low + i * step_size
        pnl = net_premium

        for leg in legs:
            qty = leg.get("quantity", 1)
            strike = leg["strike"]
            otype = leg["option_type"]

            if leg["expiration"] == near_exp:
                # Expiring leg: intrinsic value only
                if otype == "call":
                    value = max(price - strike, 0.0)
                else:
                    value = max(strike - price, 0.0)
            else:
                # Far-term leg: BSM value with remaining time
                iv = leg.get("iv") or 0.30
                value = _bsm_price(price, strike, remaining_years, iv, otype, risk_free_rate)

            if leg["side"] == "sell":
                pnl -= value * qty
            else:
                pnl += value * qty

        pnl_points.append((price, pnl * 100))

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


# ---------------------------------------------------------------------------
# Multi-expiration strategy analyzer
# ---------------------------------------------------------------------------


def analyze_multi_exp_strategy(
    legs: list[dict],
    stock_price: float,
    risk_free_rate: float = 0.0,
) -> dict:
    """Analyze a multi-expiration option strategy.

    Each leg dict must include 'expiration' (YYYY-MM-DD) in addition to the
    standard fields (strike, option_type, side, premium, delta, iv, quantity).
    risk_free_rate: annualized rate (e.g. 0.036 for 3.6%) for BSM pricing.

    Returns dict with: strategy_type, net_premium, max_profit, max_loss,
    breakevens, risk_reward_ratio, probability_of_profit, near_exp, far_exp.
    """
    if not legs:
        return {}

    expirations = sorted({lg["expiration"] for lg in legs})
    near_exp = expirations[0]
    far_exp = expirations[-1]

    strategy_type = detect_multi_exp_strategy(legs)
    net_premium = _compute_net_premium(legs)

    strikes = [lg["strike"] for lg in legs]
    margin = max(max(strikes) - min(strikes), stock_price * 0.2)
    price_low = max(0, min(strikes) - margin)
    price_high = max(strikes) + margin

    pnl = _evaluate_pnl_multi_exp(
        legs, net_premium, price_low, price_high, near_exp, far_exp, risk_free_rate
    )

    result = _build_result(strategy_type, legs, net_premium, pnl)
    result["near_exp"] = near_exp
    result["far_exp"] = far_exp
    return result
