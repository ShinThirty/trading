"""VIX-based regime classifiers: absolute vol level and 5-day tape speed."""


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
