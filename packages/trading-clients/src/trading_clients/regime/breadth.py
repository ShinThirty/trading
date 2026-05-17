"""Market-internals breadth classifier (SPY/IWM/XLY/XLU/volume/RSP)."""


def _divergence_signal(
    div: float,
    *,
    warn_below: float,
    strength_above: float,
    warn_msg: str,
    strength_msg: str,
    neutral_msg: str,
    **fmt_args: object,
) -> tuple[str, int, int]:
    """Bin a relative-performance divergence into warning / strength / neutral.

    Messages are .format()'d with `div` (signed), `abs` (absolute value),
    and any extra kwargs (e.g. `lookback`). Returns (display_part,
    warnings_delta, strengths_delta).
    """
    fmt = {"div": div, "abs": abs(div), **fmt_args}
    if div < warn_below:
        return warn_msg.format(**fmt), 1, 0
    if div > strength_above:
        return strength_msg.format(**fmt), 0, 1
    return neutral_msg.format(**fmt), 0, 0


def classify_breadth(
    spy_closes: list[float],
    iwm_closes: list[float],
    spy_volumes: list[float],
    xlu_closes: list[float],
    xly_closes: list[float],
    lookback: int = 20,
    rsp_closes: list[float] | None = None,
) -> tuple[str, str]:
    """Classify market breadth from internals.

    Four sub-signals (rsp optional for backward-compat / historical backfill):
    1. SPY vs IWM relative performance (large-cap vs small-cap divergence)
    2. XLU vs XLY relative performance (defensive vs cyclical rotation)
    3. SPY volume trend (participation quality)
    4. SPY vs RSP equal-weight divergence (megacap concentration — catches the
       2000 / late-2024 pattern that IWM/small-cap misses)

    All close lists are oldest-first, at least lookback+1 bars.
    spy_volumes: daily volume for the same period as spy_closes.
    rsp_closes: S&P 500 equal-weight ETF closes; pass None to skip the
    concentration sub-signal (RSP launched April 2003, so backfills earlier
    than that should omit it).

    Returns (label, detail_string) where label is one of:
    - Broadening: 0 warnings + ≥2 strengths (recovery has legs)
    - Healthy: 0 warnings + 0-1 strengths (clean or mildly bullish tape)
    - Mixed: ≥1 warning AND <2 warnings (genuine conflict — warnings present but
      not yet majority)
    - Narrowing: ≥2 warnings (divergences emerging, defensive rotation,
      megacap concentration, or thin volume)
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

    parts: list[str] = []
    warnings = 0
    strengths = 0

    # Signal 1: SPY vs IWM divergence (positive = IWM leads / strength).
    part, w, s = _divergence_signal(
        iwm_ret - spy_ret,
        warn_below=-3.0,
        strength_above=3.0,
        warn_msg="IWM lagging SPY by {abs:.1f}pp ({lookback}d)",
        strength_msg="IWM leading SPY by {div:.1f}pp ({lookback}d)",
        neutral_msg="SPY/IWM aligned ({div:+.1f}pp)",
        lookback=lookback,
    )
    parts.append(part)
    warnings += w
    strengths += s

    # Signal 2: XLY vs XLU rotation (positive = cyclicals lead / strength).
    part, w, s = _divergence_signal(
        xly_ret - xlu_ret,
        warn_below=-2.0,
        strength_above=2.0,
        warn_msg="defensive rotation XLU beating XLY by {abs:.1f}pp",
        strength_msg="cyclicals leading XLY over XLU by {div:.1f}pp",
        neutral_msg="XLY/XLU neutral ({div:+.1f}pp)",
    )
    parts.append(part)
    warnings += w
    strengths += s

    # Signal 3: Volume trend — compare recent 5-day avg to 20-day avg.
    # (Different shape from the divergence signals — volume ratio, not pp gap.)
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

    # Signal 4: SPY vs RSP equal-weight concentration (optional). Sign flipped
    # vs raw spy-minus-rsp so that negative = megacap concentration = warning,
    # consistent with signals 1 and 2.
    if rsp_closes is not None and len(rsp_closes) >= lookback + 1:
        rsp_ret = (rsp_closes[-1] - rsp_closes[-1 - lookback]) / rsp_closes[-1 - lookback] * 100
        part, w, s = _divergence_signal(
            rsp_ret - spy_ret,
            warn_below=-2.5,
            strength_above=1.5,
            warn_msg="megacap concentration SPY beating RSP by {abs:.1f}pp ({lookback}d)",
            strength_msg="broadening RSP leading SPY by {div:.1f}pp ({lookback}d)",
            neutral_msg="SPY/RSP aligned ({div:+.1f}pp)",
            lookback=lookback,
        )
        parts.append(part)
        warnings += w
        strengths += s

    if warnings >= 2:
        label = "Narrowing"
    elif warnings >= 1:
        label = "Mixed"
    elif strengths >= 2:
        label = "Broadening"
    else:
        label = "Healthy"

    return label, "; ".join(parts)
