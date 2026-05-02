"""Market regime classification.

Pure functions that classify market conditions into simple labels
from pre-fetched data. No I/O — all data fetching happens in the
MCP server layer.
"""

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Tech",
    "XLF": "Fins",
    "XLE": "Energy",
    "XLV": "Health",
    "XLC": "Comm",
    "XLI": "Indust",
    "XLB": "Matls",
    "XLRE": "RE",
    "XLP": "Staples",
    "XLY": "Discret",
    "XLU": "Utils",
}

RISK_ON_ETFS = {"XLK", "XLY", "XLC"}
RISK_OFF_ETFS = {"XLU", "XLP", "XLRE"}


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


def _pct_return(closes: list[float], lookback: int) -> float | None:
    """Compute percentage return over a lookback period (trading days)."""
    if len(closes) < lookback + 1:
        return None
    return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback] * 100


def classify_sector_rotation(
    sector_closes: dict[str, list[float]],
    windows: tuple[int, ...] = (30, 60, 90),
) -> tuple[str, str]:
    """Classify sector rotation from multi-timeframe ETF performance.

    Computes returns at multiple lookback windows for each SPDR sector ETF,
    ranks sectors, detects leadership shifts, and classifies risk appetite.

    sector_closes: {ETF_symbol: daily_closes_oldest_first} for sector ETFs.
    windows: lookback periods in trading days (default 30, 60, 90).

    Returns (label, detail_string) where label is Risk-On / Rotation / Risk-Off.
    """
    short_window = windows[0]
    long_window = windows[-1]

    returns: dict[int, dict[str, float]] = {}
    for w in windows:
        w_rets: dict[str, float] = {}
        for sym, closes in sector_closes.items():
            ret = _pct_return(closes, w)
            if ret is not None:
                w_rets[sym] = ret
        returns[w] = w_rets

    short_rets = returns.get(short_window, {})
    if len(short_rets) < 6:
        return "Unknown", "insufficient sector data"

    risk_on_vals = [short_rets[s] for s in RISK_ON_ETFS if s in short_rets]
    risk_off_vals = [short_rets[s] for s in RISK_OFF_ETFS if s in short_rets]
    risk_on_avg = sum(risk_on_vals) / len(risk_on_vals) if risk_on_vals else 0
    risk_off_avg = sum(risk_off_vals) / len(risk_off_vals) if risk_off_vals else 0

    if risk_on_avg > risk_off_avg and risk_on_avg > 0:
        label = "Risk-On"
    elif risk_off_avg > risk_on_avg and risk_off_avg > 0:
        label = "Risk-Off"
    else:
        label = "Rotation"

    ranked = sorted(short_rets.items(), key=lambda x: x[1], reverse=True)
    top3 = ranked[:3]
    bottom3 = ranked[-3:]

    name = SECTOR_ETFS.get
    top_str = ", ".join(f"{name(s, s)} {r:+.1f}%" for s, r in top3)
    bot_str = ", ".join(f"{name(s, s)} {r:+.1f}%" for s, r in bottom3)
    detail = f"{short_window}d leaders: {top_str}; laggards: {bot_str}"

    long_rets = returns.get(long_window, {})
    if len(long_rets) >= 6:
        ranked_long = sorted(long_rets.items(), key=lambda x: x[1], reverse=True)
        long_ranks = {sym: i + 1 for i, (sym, _) in enumerate(ranked_long)}
        short_ranks = {sym: i + 1 for i, (sym, _) in enumerate(ranked)}

        shifts = []
        for sym in sector_closes:
            if sym in long_ranks and sym in short_ranks:
                delta = long_ranks[sym] - short_ranks[sym]
                if delta >= 4:
                    shifts.append(
                        f"{name(sym, sym)} emerging (#{long_ranks[sym]}→#{short_ranks[sym]})"
                    )
                elif delta <= -4:
                    shifts.append(
                        f"{name(sym, sym)} fading (#{long_ranks[sym]}→#{short_ranks[sym]})"
                    )

        if shifts:
            detail += f"; shifts ({long_window}d→{short_window}d): {', '.join(shifts)}"

    return label, detail


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


def classify_breadth(
    spy_closes: list[float],
    iwm_closes: list[float],
    spy_volumes: list[float],
    xlu_closes: list[float],
    xly_closes: list[float],
    lookback: int = 20,
) -> tuple[str, str]:
    """Classify market breadth from internals.

    Three sub-signals:
    1. SPY vs IWM relative performance (large-cap vs small-cap divergence)
    2. XLU vs XLY relative performance (defensive vs cyclical rotation)
    3. SPY volume trend (participation quality)

    All close lists are oldest-first, at least lookback+1 bars.
    spy_volumes: daily volume for the same period as spy_closes.

    Returns (label, detail_string) where label is one of:
    - Broadening: small caps leading, cyclicals leading, heavy volume (recovery has legs)
    - Healthy: broad participation, no divergences
    - Mixed: conflicting signals
    - Narrowing: divergences emerging, defensive rotation, or thin volume
    """
    if (
        len(spy_closes) < lookback + 1
        or len(iwm_closes) < lookback + 1
        or len(xlu_closes) < lookback + 1
        or len(xly_closes) < lookback + 1
    ):
        return "Unknown", "insufficient data"

    spy_ret = (spy_closes[-1] - spy_closes[-1 - lookback]) / spy_closes[-1 - lookback] * 100
    iwm_ret = (iwm_closes[-1] - iwm_closes[-1 - lookback]) / iwm_closes[-1 - lookback] * 100
    xlu_ret = (xlu_closes[-1] - xlu_closes[-1 - lookback]) / xlu_closes[-1 - lookback] * 100
    xly_ret = (xly_closes[-1] - xly_closes[-1 - lookback]) / xly_closes[-1 - lookback] * 100

    spy_iwm_div = iwm_ret - spy_ret
    xly_xlu_div = xly_ret - xlu_ret

    parts: list[str] = []
    warnings = 0
    strengths = 0

    # Signal 1: SPY vs IWM divergence
    if spy_iwm_div < -3.0:
        parts.append(f"IWM lagging SPY by {abs(spy_iwm_div):.1f}pp ({lookback}d)")
        warnings += 1
    elif spy_iwm_div > 3.0:
        parts.append(f"IWM leading SPY by {spy_iwm_div:.1f}pp ({lookback}d)")
        strengths += 1
    else:
        parts.append(f"SPY/IWM aligned ({spy_iwm_div:+.1f}pp)")

    # Signal 2: XLY vs XLU rotation
    if xly_xlu_div < -2.0:
        parts.append(f"defensive rotation XLU beating XLY by {abs(xly_xlu_div):.1f}pp")
        warnings += 1
    elif xly_xlu_div > 2.0:
        parts.append(f"cyclicals leading XLY over XLU by {xly_xlu_div:.1f}pp")
        strengths += 1
    else:
        parts.append(f"XLY/XLU neutral ({xly_xlu_div:+.1f}pp)")

    # Signal 3: Volume trend — compare recent 5-day avg to 20-day avg
    if len(spy_volumes) >= lookback:
        recent_vol = spy_volumes[-lookback:]
        avg_20d = sum(recent_vol) / len(recent_vol)
        avg_5d = sum(spy_volumes[-5:]) / 5
        vol_ratio = avg_5d / avg_20d if avg_20d > 0 else 1.0
        if vol_ratio < 0.75:
            parts.append(f"thin volume (5d avg {vol_ratio:.0%} of 20d)")
            warnings += 1
        elif vol_ratio > 1.25:
            parts.append(f"heavy volume (5d avg {vol_ratio:.0%} of 20d)")
            strengths += 1
        else:
            parts.append(f"normal volume ({vol_ratio:.0%} of 20d avg)")

    if warnings >= 2:
        label = "Narrowing"
    elif strengths >= 2:
        label = "Broadening"
    elif warnings == 0 and strengths == 0:
        label = "Healthy"
    else:
        label = "Mixed"

    return label, "; ".join(parts)
