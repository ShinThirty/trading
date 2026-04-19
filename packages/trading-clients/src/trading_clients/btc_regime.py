"""Bitcoin macro regime classification.

Pure functions that classify macroeconomic conditions into BTC-specific
signal labels. No I/O — all data fetching happens in the MCP server layer.

BTC has no fundamentals (no earnings, revenue, margins), so entry signals
are purely macro-driven: monetary policy, liquidity, dollar strength,
real rates, risk appetite, and halving cycle position.
"""

from datetime import date

HALVING_DATE = date(2024, 4, 19)
NEXT_HALVING_EST = date(2028, 4, 17)


def classify_liquidity(m2_values: list[tuple[str, float]]) -> tuple[str, str]:
    """Classify M2 money supply growth rate.

    M2 expansion is historically the strongest macro driver for BTC.
    BTC tends to lag M2 expansion by 3-6 months.

    m2_values: list of (date, value) tuples, newest first. Weekly data.
    """
    if len(m2_values) < 2:
        return "Unknown", "insufficient M2 data"

    current = m2_values[0][1]

    if len(m2_values) >= 52:
        year_ago = m2_values[51][1]
        yoy_growth = (current - year_ago) / year_ago * 100
    else:
        oldest = m2_values[-1][1]
        periods = len(m2_values) - 1
        if oldest == 0 or periods == 0:
            return "Unknown", "insufficient M2 data"
        growth = (current - oldest) / oldest * 100
        yoy_growth = growth * (52 / periods)

    detail = f"M2 ${current / 1000:.1f}T, YoY {yoy_growth:+.1f}%"

    if len(m2_values) >= 13:
        three_mo_ago = m2_values[12][1]
        if three_mo_ago > 0:
            recent_growth = (current - three_mo_ago) / three_mo_ago * 100
            recent_ann = recent_growth * 4
            accel = "accelerating" if recent_ann > yoy_growth else "decelerating"
            detail += f", 3mo ann. {recent_ann:+.1f}% ({accel})"

    if yoy_growth > 5:
        return "Expanding", detail
    if yoy_growth > 0:
        return "Slow Growth", detail
    return "Contracting", detail


def classify_monetary_policy(
    fed_funds: float | None, prev_fed_funds: float | None
) -> tuple[str, str]:
    """Classify Fed monetary policy direction.

    Easing cycles are historically bullish for BTC.
    """
    if fed_funds is None:
        return "Unknown", "no Fed funds data"
    if prev_fed_funds is None:
        return "Unknown", f"Fed funds {fed_funds:.2f}% (no prior reading)"

    if fed_funds < prev_fed_funds:
        label = "Easing"
        detail = f"Fed funds {fed_funds:.2f}%, cut from {prev_fed_funds:.2f}%"
    elif fed_funds > prev_fed_funds:
        label = "Tightening"
        detail = f"Fed funds {fed_funds:.2f}%, hiked from {prev_fed_funds:.2f}%"
    else:
        label = "Holding"
        detail = f"Fed funds {fed_funds:.2f}%, unchanged"

    return label, detail


def classify_dollar(dxy_values: list[tuple[str, float]]) -> tuple[str, str]:
    """Classify USD trend from DXY.

    Weak dollar is bullish for BTC (inverse correlation).
    Uses 20-day and 60-day trends.

    dxy_values: list of (date, value) tuples, newest first. Daily data.
    """
    if len(dxy_values) < 2:
        return "Unknown", "insufficient DXY data"

    current = dxy_values[0][1]

    lookback_20 = min(20, len(dxy_values) - 1)
    val_20d_ago = dxy_values[lookback_20][1]
    change_20d = (current - val_20d_ago) / val_20d_ago * 100

    detail = f"DXY {current:.1f}, 20d {change_20d:+.1f}%"

    if len(dxy_values) > 60:
        val_60d_ago = dxy_values[60][1]
        change_60d = (current - val_60d_ago) / val_60d_ago * 100
        detail += f", 60d {change_60d:+.1f}%"

    if change_20d < -1.5:
        return "Weakening", detail
    if change_20d > 1.5:
        return "Strengthening", detail
    return "Stable", detail


def classify_real_rates(dgs10: float | None, cpi_yoy: float | None) -> tuple[str, str]:
    """Classify real interest rate environment.

    Negative or falling real rates are bullish for BTC (fiat loses value).
    """
    if dgs10 is None:
        return "Unknown", "no 10Y yield data"
    if cpi_yoy is None:
        return "Unknown", f"10Y yield {dgs10:.2f}% (no CPI data)"

    real_rate = dgs10 - cpi_yoy

    detail = f"10Y {dgs10:.2f}% − CPI {cpi_yoy:.1f}% = {real_rate:+.2f}% real"

    if real_rate < 0:
        return "Negative", detail
    if real_rate < 1.0:
        return "Low", detail
    return "High", detail


def classify_risk_appetite(vix: float | None) -> tuple[str, str]:
    """Classify risk appetite from VIX.

    Low VIX = risk-on, generally bullish for BTC.
    Crisis VIX = mixed (liquidation cascades vs flight to hard assets).
    """
    if vix is None:
        return "Unknown", "no VIX data"

    if vix >= 35:
        return "Crisis", f"VIX {vix:.1f}"
    if vix >= 25:
        return "Fearful", f"VIX {vix:.1f}"
    if vix >= 15:
        return "Neutral", f"VIX {vix:.1f}"
    return "Risk-On", f"VIX {vix:.1f}"


def classify_halving_cycle(as_of: date | None = None) -> tuple[str, str]:
    """Classify position in Bitcoin's ~4-year halving cycle.

    Historically:
    - 0-6mo post-halving: Accumulation (supply shock building)
    - 6-12mo: Early bull (breakout typically begins)
    - 12-18mo: Peak bull (historically strongest gains)
    - 18-24mo: Distribution / peak zone (caution)
    - 24+mo: Late cycle / bear (drawdown + recovery)
    """
    if as_of is None:
        as_of = date.today()

    days_since = (as_of - HALVING_DATE).days
    months_since = days_since / 30.44
    days_to_next = (NEXT_HALVING_EST - as_of).days

    if months_since < 6:
        label = "Accumulation"
        phase = "0-6mo post-halving, supply shock building"
    elif months_since < 12:
        label = "Early Bull"
        phase = "6-12mo post-halving, breakout typically begins"
    elif months_since < 18:
        label = "Peak Bull"
        phase = "12-18mo post-halving, historically strongest gains"
    elif months_since < 24:
        label = "Distribution"
        phase = "18-24mo post-halving, caution — peak zone"
    else:
        label = "Late Cycle"
        phase = "24+mo post-halving, cycle maturing"

    detail = f"{phase} ({months_since:.0f}mo since halving, ~{days_to_next}d to next)"
    return label, detail


BULLISH_LABELS: dict[str, set[str]] = {
    "Liquidity": {"Expanding"},
    "Monetary Policy": {"Easing"},
    "Dollar": {"Weakening"},
    "Real Rates": {"Negative", "Low"},
    "Risk Appetite": {"Risk-On", "Neutral"},
    "Halving Cycle": {"Early Bull", "Peak Bull"},
}

BEARISH_LABELS: dict[str, set[str]] = {
    "Liquidity": {"Contracting"},
    "Monetary Policy": {"Tightening"},
    "Dollar": {"Strengthening"},
    "Real Rates": {"High"},
    "Risk Appetite": {"Crisis"},
    "Halving Cycle": {"Distribution", "Late Cycle"},
}


def macro_scorecard(labels: dict[str, str]) -> str:
    """Produce a composite BTC macro assessment from individual signal labels.

    Returns a favorability string with bullish/bearish counts.
    """
    bullish = 0
    bearish = 0
    total = 0

    for name, label in labels.items():
        if name not in BULLISH_LABELS:
            continue
        total += 1
        if label in BULLISH_LABELS.get(name, set()):
            bullish += 1
        if label in BEARISH_LABELS.get(name, set()):
            bearish += 1

    if total == 0:
        return "Insufficient data"

    ratio = bullish / total

    if ratio >= 0.8:
        return f"Strongly Favorable ({bullish}/{total} bullish)"
    if ratio >= 0.6:
        return f"Favorable ({bullish}/{total} bullish)"
    if ratio >= 0.4:
        return f"Mixed ({bullish}/{total} bullish, {bearish}/{total} bearish)"
    if ratio >= 0.2:
        return f"Unfavorable ({bearish}/{total} bearish)"
    return f"Strongly Unfavorable ({bearish}/{total} bearish)"
