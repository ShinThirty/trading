"""DTE-based threshold evaluation for option strike proximity."""

from option_monitor.monitor.positions import ShortOptionLeg


def evaluate(leg: ShortOptionLeg, underlying_price: float) -> str | None:
    """Evaluate whether a short option leg triggers an alert.

    Returns:
        "critical" — price is very close to or past the strike
        "warning"  — price is approaching the strike
        None       — no alert (resolved / safe)

    Thresholds widen as expiration approaches (gamma risk):

        DTE      Warning   Critical
        >14      3%        1% or ITM
        7-14     5%        3% or ITM
        <7       8%        5% or ITM

    Direction-aware:
        CALL — alert when price is rising toward/above strike
        PUT  — alert when price is falling toward/below strike
    """
    dte = leg.dte
    if dte < 0:
        return None  # expired, ignore

    # Select thresholds based on DTE
    if dte > 14:
        warn_pct, crit_pct = 0.03, 0.01
    elif dte >= 7:
        warn_pct, crit_pct = 0.05, 0.03
    else:
        warn_pct, crit_pct = 0.08, 0.05

    strike = leg.strike

    if leg.option_type == "CALL":
        # Covered call: alert when price rises toward strike
        proximity = (strike - underlying_price) / strike
        # proximity < 0 means ITM (price above strike)
    else:
        # CSP: alert when price falls toward strike
        proximity = (underlying_price - strike) / strike
        # proximity < 0 means ITM (price below strike)

    if proximity <= 0:
        return "critical"  # ITM
    if proximity <= crit_pct:
        return "critical"
    if proximity <= warn_pct:
        return "warning"
    return None
