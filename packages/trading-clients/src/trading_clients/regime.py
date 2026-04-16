"""Market regime classification.

Pure functions that classify market conditions into simple labels
from pre-fetched data. No I/O — all data fetching happens in the
MCP server layer.
"""

RISK_ON_SECTORS = {"Technology", "Consumer Cyclical", "Communication Services"}
RISK_OFF_SECTORS = {"Utilities", "Consumer Defensive", "Real Estate"}


def parse_fred_value(observations: list[dict]) -> tuple[float | None, str]:
    """Extract the latest numeric value from FRED observations.

    FRED returns values as strings; '.' means data unavailable.
    Returns (value, date) tuple.
    """
    if not observations:
        return None, ""
    obs = observations[0]
    date = obs.get("date", "")
    val = obs.get("value", ".")
    if val == ".":
        return None, date
    try:
        return float(val), date
    except (ValueError, TypeError):
        return None, date


def classify_volatility(vix: float, vix3m: float | None = None) -> tuple[str, str]:
    """Classify VIX level into a regime label.

    Uses absolute thresholds with a backwardation override: if VIX > VIX3M
    (term structure inverted), the market is in active panic regardless of
    absolute level — override to Crisis.

    Returns (label, detail_string).
    """
    backwardation = vix3m is not None and vix > vix3m

    if backwardation:
        label = "Crisis"
        detail = f"VIX {vix:.1f} > VIX3M {vix3m:.1f} (backwardation)"
    elif vix >= 35:
        label = "Crisis"
        detail = f"VIX {vix:.1f}"
    elif vix >= 25:
        label = "Elevated"
        detail = f"VIX {vix:.1f}"
    elif vix >= 15:
        label = "Normal"
        detail = f"VIX {vix:.1f}"
    else:
        label = "Low"
        detail = f"VIX {vix:.1f}"

    return label, detail


def classify_trend(
    price: float,
    rsi: float | None,
    sma50: float | None,
    sma200: float | None,
) -> tuple[str, str]:
    """Classify SPY price trend from technicals.

    Primary: price vs SMA50 vs SMA200 alignment.
    Fallback (SMA200 unavailable): RSI + price vs SMA50.

    Returns (label, detail_string).
    """
    parts: list[str] = []
    if rsi is not None:
        parts.append(f"RSI {rsi:.0f}")

    if sma50 is not None and sma200 is not None:
        above_50 = price > sma50
        above_200 = price > sma200
        sma50_above_200 = sma50 > sma200

        parts.append(f"{'above' if above_50 else 'below'} 50 SMA")
        parts.append(f"{'above' if above_200 else 'below'} 200 SMA")
        detail = f"SPY {', '.join(parts)}"

        if above_50 and sma50_above_200:
            return "Uptrend", detail
        if not above_50 and not sma50_above_200:
            return "Downtrend", detail
        return "Sideways", detail

    # Fallback: RSI + SMA50 only
    if sma50 is not None and rsi is not None:
        above_50 = price > sma50
        parts.append(f"{'above' if above_50 else 'below'} 50 SMA")
        detail = f"SPY {', '.join(parts)}"

        if rsi > 50 and above_50:
            return "Uptrend", detail
        if rsi < 50 and not above_50:
            return "Downtrend", detail
        return "Sideways", detail

    detail = f"SPY {', '.join(parts)}" if parts else "SPY (insufficient data)"
    return "Sideways", detail


def _fed_direction(fed_funds: float | None, prev_fed_funds: float | None) -> str:
    """Determine Fed funds direction from two consecutive observations."""
    if fed_funds is None or prev_fed_funds is None:
        return "unknown"
    if fed_funds > prev_fed_funds:
        return "rising"
    if fed_funds < prev_fed_funds:
        return "falling"
    return "stable"


def classify_macro(
    yield_spread: float | None,
    fed_funds: float | None,
    prev_fed_funds: float | None,
) -> tuple[str, str]:
    """Classify macro environment from yield curve and fed funds.

    Yield curve shape is the primary signal. Fed funds direction is
    shown in the detail string for context.

    Returns (label, detail_string).
    """
    if yield_spread is None:
        return "Unknown", "yield curve data unavailable"

    # Yield curve classification
    if yield_spread > 1.0:
        label = "Steep"
    elif yield_spread > 0.0:
        label = "Flat"
    else:
        label = "Inverted"

    detail = f"10Y-2Y: {yield_spread:+.2f}%"

    # Fed funds direction
    if fed_funds is not None:
        direction = _fed_direction(fed_funds, prev_fed_funds)
        if direction != "unknown":
            detail += f", Fed funds {fed_funds:.2f}% {direction}"
        else:
            detail += f", Fed funds {fed_funds:.2f}%"

    return label, detail


def detect_uninversion_trap(
    spread_history: list[float],
    current_spread: float | None,
    fed_funds: float | None,
    prev_fed_funds: float | None,
) -> str | None:
    """Detect the yield curve un-inversion trap.

    The recession signal is the inversion. The recession itself typically
    arrives when the curve un-inverts — the Fed cuts the short end,
    steepening the curve rapidly. If the curve was recently inverted and
    is now steepening while the Fed is cutting, this is maximum danger.

    spread_history: recent T10Y2Y daily values (newest first), ~6 months.
    current_spread: latest T10Y2Y value.
    fed_funds / prev_fed_funds: for direction detection.

    Returns a warning string, or None if the trap is not active.
    """
    if current_spread is None or not spread_history:
        return None

    # Was the curve inverted at any point in the history?
    inverted_values = [v for v in spread_history if v <= 0.0]
    if not inverted_values:
        return None

    # How long ago? Find the most recent inverted observation index
    # (history is newest-first, so index = how many observations ago)
    months_ago = None
    for i, v in enumerate(spread_history):
        if v <= 0.0:
            # ~21 trading days per month
            months_ago = round(i / 21)
            break

    direction = _fed_direction(fed_funds, prev_fed_funds)

    if current_spread > 1.0 and direction == "falling":
        ago = f"{months_ago}mo ago" if months_ago else "recently"
        return (
            f"UN-INVERSION TRAP: curve was inverted {ago}, "
            f"now Steep ({current_spread:+.2f}%) with falling rates — maximum danger"
        )

    if current_spread > 0.0 and direction == "falling":
        ago = f"{months_ago}mo ago" if months_ago else "recently"
        return (
            f"Un-inversion watch: curve was inverted {ago}, "
            f"now {current_spread:+.2f}% with falling rates — "
            f"monitor for acceleration toward Steep (>1.0%)"
        )

    return None


def classify_sectors(sectors: list[dict]) -> tuple[str, str]:
    """Classify sector performance into risk-on/off.

    Compares average performance of high-beta sectors (Tech, Consumer
    Cyclical, Comm Services) vs defensive sectors (Utilities, Consumer
    Defensive, Real Estate).

    Returns (label, detail_string).
    """
    if not sectors:
        return "Unknown", "no sector data"

    risk_on_vals: list[float] = []
    risk_off_vals: list[float] = []

    for s in sectors:
        name = s.get("sector", "")
        change = s.get("averageChange")
        if change is None:
            continue
        change = float(change)
        if name in RISK_ON_SECTORS:
            risk_on_vals.append(change)
        elif name in RISK_OFF_SECTORS:
            risk_off_vals.append(change)

    if not risk_on_vals or not risk_off_vals:
        return "Unknown", "insufficient sector data"

    risk_on_avg = sum(risk_on_vals) / len(risk_on_vals)
    risk_off_avg = sum(risk_off_vals) / len(risk_off_vals)

    # Build detail: top 2 and bottom 2 sectors
    ranked = sorted(sectors, key=lambda s: float(s.get("averageChange", 0)), reverse=True)
    top = ranked[:2]
    bottom = ranked[-2:]
    top_str = ", ".join(
        f"{_short_sector(s.get('sector', ''))} {float(s.get('averageChange', 0)):+.1f}%"
        for s in top
    )
    bottom_str = ", ".join(
        f"{_short_sector(s.get('sector', ''))} {float(s.get('averageChange', 0)):+.1f}%"
        for s in bottom
    )
    detail = f"{top_str}; {bottom_str}"

    if risk_on_avg > risk_off_avg and risk_on_avg > 0:
        return "Risk-On", detail
    if risk_off_avg > risk_on_avg and risk_off_avg > 0:
        return "Risk-Off", detail
    return "Rotation", detail


def detect_semi_divergence(
    smh_closes: list[float],
    spy_closes: list[float],
    lookback: int = 20,
) -> str | None:
    """Detect semiconductor divergence from broad market.

    Big Tech (AAPL, MSFT) can mask semi weakness, producing a false
    Risk-On signal while semis are rolling over. Compare SMH vs SPY
    relative performance over the lookback period.

    smh_closes / spy_closes: daily closes (oldest first), at least
    lookback+1 bars.

    Returns a warning string, or None if no divergence.
    """
    if len(smh_closes) < lookback + 1 or len(spy_closes) < lookback + 1:
        return None

    smh_return = (smh_closes[-1] - smh_closes[-1 - lookback]) / smh_closes[-1 - lookback] * 100
    spy_return = (spy_closes[-1] - spy_closes[-1 - lookback]) / spy_closes[-1 - lookback] * 100
    divergence = smh_return - spy_return

    # Flag if SMH underperforms SPY by more than 3% over the lookback period
    if divergence < -3.0:
        return (
            f"Semi divergence: SMH {smh_return:+.1f}% vs SPY {spy_return:+.1f}% "
            f"({lookback}d) — cycle may be turning despite Risk-On sector label"
        )

    return None


def _short_sector(name: str) -> str:
    """Shorten sector names for compact display."""
    abbreviations = {
        "Technology": "Tech",
        "Consumer Cyclical": "Cons Cycl",
        "Communication Services": "Comm Svcs",
        "Consumer Defensive": "Cons Def",
        "Financial Services": "Financials",
        "Real Estate": "Real Est",
        "Basic Materials": "Materials",
        "Industrials": "Industrials",
        "Healthcare": "Healthcare",
        "Utilities": "Utilities",
        "Energy": "Energy",
    }
    return abbreviations.get(name, name)
