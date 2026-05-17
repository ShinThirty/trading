"""Sentiment + CFTC positioning regime classifiers (contrarian polarity)."""


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
