"""Black-Scholes-Merton option pricing.

Pure math module — no I/O, no API calls. Used for hypothetical option valuation
in scenario analysis (e.g. tail-hedge `project_option_grid`) and for valuing
the far-dated leg of multi-expiration strategies (calendar/diagonal spreads).

For risk-free rate retrieval to feed `bsm_price`, see `trading_mcp.helpers.
_fetch_risk_free_rate` — that function lives in the trading-mcp package because
it requires the FRED client (Context-dependent), but conceptually pairs with
this module.

Reference: Hull, *Options, Futures, and Other Derivatives*, Ch. 14.
"""

from math import erf, exp, log, sqrt


def norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (exact, no scipy needed)."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def bsm_price(
    stock_price: float,
    strike: float,
    tte: float,
    iv: float,
    option_type: str,
    r: float = 0.0,
) -> float:
    """Black-Scholes-Merton option price.

    stock_price: current underlying price
    strike: option strike price
    tte: time to expiration in years (e.g. 30 days = 30/365)
    iv: implied volatility as decimal (e.g. 0.30 for 30%)
    option_type: 'call' or 'put'
    r: annualized risk-free rate as decimal (e.g. 0.045 for 4.5%)

    Returns the theoretical option price. If tte or iv is non-positive,
    returns intrinsic value.
    """
    if tte <= 0 or iv <= 0:
        if option_type == "call":
            return max(stock_price - strike, 0.0)
        return max(strike - stock_price, 0.0)

    sqrt_t = sqrt(tte)
    d1 = (log(stock_price / strike) + (r + 0.5 * iv * iv) * tte) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    discount = exp(-r * tte)

    if option_type == "call":
        return stock_price * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    return strike * discount * norm_cdf(-d2) - stock_price * norm_cdf(-d1)


def lognormal_cdf(
    price: float,
    stock_price: float,
    tte: float,
    iv: float,
    r: float = 0.0,
) -> float:
    """Risk-neutral P(S_T <= price) under lognormal terminal distribution.

    Uses log(S_T/S_0) ~ N((r - σ²/2)T, σ²T). Returns 0 for non-positive price.

    When evaluated at price == strike, this is equivalent to N(-d2) from BSM:
    the risk-neutral probability that the option finishes ITM (for a put).
    Generalizes to any price level for breakeven-based PoP calculations.
    """
    if price <= 0:
        return 0.0
    if tte <= 0 or iv <= 0:
        return 1.0 if stock_price <= price else 0.0
    d2 = (log(stock_price / price) + (r - 0.5 * iv * iv) * tte) / (iv * sqrt(tte))
    return norm_cdf(-d2)
