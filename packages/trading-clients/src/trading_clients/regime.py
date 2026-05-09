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
    - Broadening: 0 warnings + ≥2 strengths (recovery has legs)
    - Healthy: 0 warnings + 0-1 strengths (clean or mildly bullish tape)
    - Mixed: ≥1 warning AND <2 warnings (genuine conflict — warnings present but
      not yet majority)
    - Narrowing: ≥2 warnings (divergences emerging, defensive rotation,
      or thin volume)
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
    elif warnings >= 1:
        label = "Mixed"
    elif strengths >= 2:
        label = "Broadening"
    else:
        label = "Healthy"

    return label, "; ".join(parts)


def classify_credit(
    current_oas: float | None,
    oas_history: list[float],
) -> tuple[str, str]:
    """Classify credit spread direction from HY OAS observations.

    Credit spreads (high-yield option-adjusted spread) widen sharply at the
    onset of crashes — typically 100-300 bps in the first weeks of stress.
    Uses 5-day delta as the speed signal.

    current_oas: latest HY OAS value (percent, not bps).
    oas_history: recent observations (newest-first, ~30 days).

    Returns (label, detail_string) where label is one of:
    - Widening: 5-day delta > +50 bps (active stress)
    - Stable: |5-day delta| <= 50 bps (normal range)
    - Tightening: 5-day delta < -50 bps (recovery / risk-on)
    """
    if current_oas is None or len(oas_history) < 6:
        return "Unknown", "credit data unavailable"

    # Newest-first; index 0 is current, index 5 is 5 trading days ago.
    # OAS is in percent; convert delta to bps for readability.
    oas_5d_ago = oas_history[5]
    delta_bps = (current_oas - oas_5d_ago) * 100

    if delta_bps > 50:
        label = "Widening"
    elif delta_bps < -50:
        label = "Tightening"
    else:
        label = "Stable"

    return label, f"HY OAS {current_oas:.2f}% (Δ5d {delta_bps:+.0f} bps)"


def detect_credit_trap(
    current_oas: float | None,
    oas_history: list[float],
) -> str | None:
    """Detect slow credit-spread deterioration trap.

    Companion to detect_uninversion_trap. Catches HY OAS grinding wider
    over weeks without single-day spikes that would trip the Widening
    label in classify_credit. Pattern: current OAS sits >100 bps above
    its rolling 1-month low, indicating sustained leak from a recent floor.

    Examples this catches that classify_credit misses:
    - 2022 H1: HY OAS drifted from ~3% to ~6% over months without
      single 5-day +50 bps spikes
    - 2007 H2: pre-crisis credit leak while equity still grinding up

    current_oas: latest HY OAS value (percent).
    oas_history: recent observations (newest-first), at least 22 days.

    Returns a warning string, or None if the trap is not active.
    """
    if current_oas is None or len(oas_history) < 22:
        return None

    # Newest-first; first 22 obs span the trailing month
    recent_low = min(oas_history[:22])
    rise_bps = (current_oas - recent_low) * 100

    if rise_bps > 100:
        return (
            f"Credit trap: HY OAS {current_oas:.2f}% has risen {rise_bps:+.0f} bps "
            f"from 1mo low ({recent_low:.2f}%) — slow deterioration"
        )
    return None


def classify_extended(
    rsi: float | None,
    sector_closes: dict[str, list[float]],
    spy_closes: list[float],
    rsi_threshold: float = 70.0,
    dispersion_threshold: float = 25.0,
    spy_5d_threshold: float = 3.0,
    sector_lookback: int = 30,
) -> tuple[bool, str]:
    """Detect 'Extended' Expansion sub-state.

    Companion to classify_tape_speed: that catches *crash* speed
    (-5% SPY in 5d); this catches *grinding-up* speed where mean-reversion
    risk is rising while the verdict still reads Expansion.

    Three signals; flag activates when 2+ fire:
    - RSI > 70 (overbought)
    - Sector dispersion > 25pp top-vs-bottom over 30d (crowded leadership)
    - SPY 5d return > +3% (parabolic tape)

    Returns (is_extended, detail_string listing fired signals).
    """
    fired: list[str] = []

    if rsi is not None and rsi > rsi_threshold:
        fired.append(f"RSI {rsi:.0f}")

    sector_returns = [
        r
        for r in (_pct_return(c, sector_lookback) for c in sector_closes.values())
        if r is not None
    ]
    if len(sector_returns) >= 6:
        dispersion = max(sector_returns) - min(sector_returns)
        if dispersion > dispersion_threshold:
            fired.append(f"sector spread {dispersion:.0f}pp")

    spy_5d = _pct_return(spy_closes, 5)
    if spy_5d is not None and spy_5d > spy_5d_threshold:
        fired.append(f"SPY 5d {spy_5d:+.1f}%")

    is_extended = len(fired) >= 2
    return is_extended, ", ".join(fired)


def classify_tape_speed(
    spy_closes: list[float],
    vix_closes: list[float],
) -> tuple[str, str]:
    """Classify tape speed from SPY return magnitude and VIX rate-of-change.

    Crashes deliver vol expansion + speed together. A -5% SPY move or a
    +50% VIX surge over 5 days indicates tape-speed regime shift toward
    crash territory.

    spy_closes: SPY daily closes (oldest-first), at least 6 bars.
    vix_closes: VIX daily closes (oldest-first), at least 6 bars.

    Returns (label, detail_string) where label is one of:
    - Fast: SPY 5d return < -5% OR VIX 5d %change > +50%
    - Normal: otherwise
    """
    parts: list[str] = []
    spy_fast = False
    vix_fast = False

    if len(spy_closes) >= 6:
        spy_5d_ret = (spy_closes[-1] - spy_closes[-6]) / spy_closes[-6] * 100
        parts.append(f"SPY 5d {spy_5d_ret:+.1f}%")
        if spy_5d_ret < -5.0:
            spy_fast = True

    if len(vix_closes) >= 6:
        vix_5d_chg = (vix_closes[-1] - vix_closes[-6]) / vix_closes[-6] * 100
        parts.append(f"VIX Δ5d {vix_5d_chg:+.0f}%")
        if vix_5d_chg > 50.0:
            vix_fast = True

    if not parts:
        return "Unknown", "insufficient data"

    label = "Fast" if (spy_fast or vix_fast) else "Normal"
    return label, ", ".join(parts)


def classify_sentiment(
    cboe_equity_pc: float | None,
    naaim_exposure: float | None,
    aaii_spread: float | None,
) -> tuple[str, str]:
    """Classify retail/active-manager sentiment as a contrarian signal.

    Three sources, each with an extreme threshold in both directions:

    - CBOE equity p/c (daily): >0.85 = puts dominate (fear), <0.55 = calls
      dominate (greed). Typical mid-cycle reading is 0.6-0.8.
    - NAAIM exposure (weekly): <40 = active managers defensive, >85 = leveraged
      long. Range is -200 to +200; most readings sit 30-90.
    - AAII bull-bear spread (weekly): <-10 = bears outnumber bulls (capitulation
      tilt), >+15 = crowded long. Long-term mean is roughly 0.

    Five-tier output, contrarian polarity (extreme greed = bearish for forward
    returns, extreme fear = bullish):
    - Capitulation: all 3 fearful extremes — strongest bullish contrarian
    - Fearful: 2+ fearful extremes
    - Stretched: 2+ greedy extremes
    - Greedy: all 3 greedy extremes — strongest bearish contrarian
    - Neutral: otherwise (or insufficient data)

    Returns (label, detail_string).
    """
    fearful = 0
    greedy = 0
    parts: list[str] = []

    if cboe_equity_pc is not None:
        if cboe_equity_pc > 0.85:
            fearful += 1
        elif cboe_equity_pc < 0.55:
            greedy += 1
        parts.append(f"p/c {cboe_equity_pc:.2f}")

    if naaim_exposure is not None:
        if naaim_exposure < 40:
            fearful += 1
        elif naaim_exposure > 85:
            greedy += 1
        parts.append(f"NAAIM {naaim_exposure:.0f}")

    if aaii_spread is not None:
        if aaii_spread < -10:
            fearful += 1
        elif aaii_spread > 15:
            greedy += 1
        parts.append(f"AAII {aaii_spread:+.1f}")

    available = sum(1 for v in (cboe_equity_pc, naaim_exposure, aaii_spread) if v is not None)
    if available == 0:
        return "Unknown", "no sentiment sources available"

    if fearful == 3:
        label = "Capitulation"
    elif fearful >= 2:
        label = "Fearful"
    elif greedy == 3:
        label = "Greedy"
    elif greedy >= 2:
        label = "Stretched"
    else:
        label = "Neutral"

    coverage = f"{available}/3 sources"
    return label, f"{', '.join(parts)} ({coverage})"


def classify_positioning(
    contract_zs: dict[str, float | None],
    extreme_threshold: float = 1.5,
) -> tuple[str, str]:
    """Classify CFTC COT speculator positioning across a curated contract set.

    Each entry is the latest 52-week z-score on net spec positioning for a
    contract (SPX, NDX, VIX, 10Y, Gold, WTI). Extremes are contrarian signals:
    crowded long = vulnerable to a flush; crowded short = squeeze risk.

    Threshold: |z| >= 1.5 counts as an extreme.

    Five-tier output:
    - Crowded Long: 2+ contracts at z >= 2.0 (strong bearish-forward signal)
    - Stretched Long: 1+ extremes, all long-tilted
    - Crowded Short: 2+ contracts at z <= -2.0 (strong bullish-forward signal)
    - Stretched Short: 1+ extremes, all short-tilted
    - Mixed: long AND short extremes simultaneously
    - Neutral: no extremes (or insufficient data)

    Returns (label, detail_string).
    """
    available = {k: v for k, v in contract_zs.items() if v is not None}
    if not available:
        return "Unknown", "no COT data"

    long_extreme: list[tuple[str, float]] = []
    short_extreme: list[tuple[str, float]] = []
    for k, z in available.items():
        if z >= extreme_threshold:
            long_extreme.append((k, z))
        elif z <= -extreme_threshold:
            short_extreme.append((k, z))

    crowded_long = sum(1 for _, z in long_extreme if z >= 2.0)
    crowded_short = sum(1 for _, z in short_extreme if z <= -2.0)

    detail_parts: list[str] = []
    if long_extreme:
        detail_parts.append("long: " + ", ".join(f"{k} {z:+.2f}" for k, z in long_extreme))
    if short_extreme:
        detail_parts.append("short: " + ", ".join(f"{k} {z:+.2f}" for k, z in short_extreme))
    detail = (
        "; ".join(detail_parts)
        if detail_parts
        else (
            f"all neutral ({len(available)}/6 contracts, max |z| "
            f"{max(abs(z) for z in available.values()):.2f})"
        )
    )

    if long_extreme and short_extreme:
        label = "Mixed"
    elif crowded_long >= 2:
        label = "Crowded Long"
    elif long_extreme:
        label = "Stretched Long"
    elif crowded_short >= 2:
        label = "Crowded Short"
    elif short_extreme:
        label = "Stretched Short"
    else:
        label = "Neutral"

    return label, detail


def classify_policy(
    outcomes: list[tuple[str, float]],
    hold_threshold: float = 0.70,
    move_threshold: float = 0.50,
    bias_threshold: float = 0.25,
) -> tuple[str, str]:
    """Classify what the prediction market has priced in for the next FOMC.

    Polymarket FOMC events expose binary YES/NO contracts on each possible
    decision: "No change", "25 bps decrease", "50+ bps decrease", "25 bps
    increase", "50+ bps increase". The yes-price on each is the implied
    probability. We bucket those into hold / cut / hike and label the
    consensus tilt.

    outcomes: list of (label, implied_prob) from a Polymarket FOMC event.
        Labels are matched case-insensitively for "no change", "decrease",
        "increase". Anything that doesn't match is ignored.
    hold_threshold: P(hold) above this → "Hold Priced"
    move_threshold: P(cut) or P(hike) above this → "Cut/Hike Priced"
    bias_threshold: minimum spread between cut and hike before declaring a bias

    Six-tier output:
      - Hold Priced — high consensus on no change (low surprise risk on direction)
      - Cut Priced — easing already priced (hawk surprise = downside)
      - Hike Priced — tightening already priced (dove surprise = upside)
      - Cut Bias — leaning dovish but not consensus
      - Hike Bias — leaning hawkish but not consensus
      - Uncertain — split, no clear lean

    Returns (label, detail_string).
    """
    if not outcomes:
        return "Unknown", "no FOMC market available"

    p_hold = 0.0
    p_cut = 0.0
    p_hike = 0.0
    matched = 0
    for label, prob in outcomes:
        s = label.lower().strip()
        if "no change" in s or s in {"hold", "unchanged"}:
            p_hold += prob
            matched += 1
        elif "decrease" in s or "cut" in s:
            p_cut += prob
            matched += 1
        elif "increase" in s or "hike" in s:
            p_hike += prob
            matched += 1

    if matched == 0:
        return "Unknown", "no recognized FOMC outcome labels"

    detail = f"hold {p_hold * 100:.0f}% / cut {p_cut * 100:.0f}% / hike {p_hike * 100:.0f}%"

    if p_hold >= hold_threshold:
        return "Hold Priced", detail
    if p_cut >= move_threshold:
        return "Cut Priced", detail
    if p_hike >= move_threshold:
        return "Hike Priced", detail
    if p_cut - p_hike >= bias_threshold:
        return "Cut Bias", detail
    if p_hike - p_cut >= bias_threshold:
        return "Hike Bias", detail
    return "Uncertain", detail


def synthesize_verdict(
    volatility: str | None,
    trend: str | None,
    breadth: str | None,
    macro: str | None,
    sectors: str | None,
    credit: str | None,
    speed: str | None,
    warnings: set[str],
) -> tuple[str, str]:
    """Synthesize a single regime verdict from dimensional labels + warnings.

    Priority-ordered decision tree — first match wins. Verdict drives portfolio
    sizing and accumulation timing. Only Crash Active gates the structural
    hedge program's Trigger 2 (harvest tranches); other verdicts inform
    position-level decisions, not hedge actions.

    warnings: set of warning identifiers, e.g. {"uninversion_trap", "semi_divergence"}.

    Returns (verdict, evidence_string).
    """
    # 1. Crash Active — volatility Crisis is decisive
    if volatility == "Crisis":
        return "Crash Active", "Volatility = Crisis"

    # 2. Pre-Crash Watch — leading indicators ahead of vol expansion
    if volatility == "Elevated" and (speed == "Fast" or credit == "Widening"):
        triggers: list[str] = []
        if speed == "Fast":
            triggers.append("tape Fast")
        if credit == "Widening":
            triggers.append("credit Widening")
        return "Pre-Crash Watch", f"Vol Elevated + {' + '.join(triggers)}"
    if volatility == "Normal" and speed == "Fast" and credit == "Widening":
        return "Pre-Crash Watch", "Vol Normal but tape Fast + credit Widening"

    # 3. Recovery — vol coming off elevated with broadening + risk-on
    if volatility == "Elevated" and breadth == "Broadening" and sectors == "Risk-On":
        return "Recovery", "Vol Elevated + Broadening breadth + Risk-On"

    # 4. Bear Setup — structural deterioration without vol Crisis
    bear_score = 0
    bear_parts: list[str] = []
    if trend == "Downtrend":
        bear_score += 1
        bear_parts.append("Downtrend")
    if breadth == "Narrowing":
        bear_score += 1
        bear_parts.append("Narrowing")
    if sectors == "Risk-Off":
        bear_score += 1
        bear_parts.append("Risk-Off")
    if "uninversion_trap" in warnings:
        bear_score += 2
        bear_parts.append("un-inversion trap")
    if "semi_divergence" in warnings:
        bear_score += 1
        bear_parts.append("semi divergence")
    if "credit_trap" in warnings:
        bear_score += 1
        bear_parts.append("credit trap")
    if bear_score >= 3:
        return "Bear Setup", f"{' + '.join(bear_parts)} (score {bear_score}/7)"

    # 5. Late Cycle — warnings emerging but trend still up
    late_score = 0
    late_parts: list[str] = []
    if macro == "Inverted":
        late_score += 1
        late_parts.append("Inverted")
    if breadth == "Narrowing":
        late_score += 1
        late_parts.append("Narrowing")
    if sectors in ("Rotation", "Risk-Off"):
        late_score += 1
        late_parts.append(str(sectors))
    if "uninversion_trap" in warnings:
        late_score += 2
        late_parts.append("un-inversion trap")
    if "credit_trap" in warnings:
        late_score += 1
        late_parts.append("credit trap")
    if late_score >= 2 and trend in ("Uptrend", "Sideways"):
        return "Late Cycle", f"{' + '.join(late_parts)} (score {late_score}/6, trend {trend})"

    # 6. Expansion — clean bull
    if trend == "Uptrend" and breadth in ("Healthy", "Broadening") and sectors == "Risk-On":
        return "Expansion", f"Uptrend + {breadth} breadth + Risk-On"

    # 7. Mixed — fallback when signals don't cohere
    return "Mixed", "signals don't cohere"
