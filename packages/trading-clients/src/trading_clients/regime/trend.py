"""SPY trend and 'extended' sub-state classifiers."""

from ._common import _pct_return


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
