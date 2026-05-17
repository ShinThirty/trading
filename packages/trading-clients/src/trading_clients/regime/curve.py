"""Yield curve and Fed-funds regime classifiers."""

from ._common import _fed_direction


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


def classify_curve_regime(
    dy_2y_bps: float | None,
    dy_10y_bps: float | None,
    dy_30y_bps: float | None,
    move_threshold_bps: float = 10.0,
) -> tuple[str, str]:
    """Classify yield-curve regime from 4-week tenor changes.

    Four canonical regimes based on whether yields are rising or falling and
    whether the long end (10Y/30Y avg) or the short end (2Y) is leading the
    move. The leading-tenor diagnostic is the load-bearing piece: a bear
    steepener (long end up faster than short end) is term-premium expansion
    or supply/inflation repricing; a bear flattener (short end leading) is
    Fed-path repricing.

    Five-tier output:
    - Bear Steepener: yields rising, long end (10Y/30Y) leading
    - Bear Flattener: yields rising, short end (2Y) leading
    - Bull Steepener: yields falling, short end (2Y) leading (Fed-cut priced)
    - Bull Flattener: yields falling, long end leading (recession/duration bid)
    - Quiet: |all moves| < threshold (no meaningful repricing)
    - Mixed: directions disagree across tenors (no coherent regime)

    All inputs are 4-week basis-point changes; threshold defaults to 10 bps.

    Returns (label, detail_string).
    """
    parts: list[str] = []
    if dy_2y_bps is not None:
        parts.append(f"2Y {dy_2y_bps:+.0f}")
    if dy_10y_bps is not None:
        parts.append(f"10Y {dy_10y_bps:+.0f}")
    if dy_30y_bps is not None:
        parts.append(f"30Y {dy_30y_bps:+.0f}")
    detail_changes = " | ".join(parts) + " bps (4w)" if parts else ""

    if dy_2y_bps is None or dy_10y_bps is None or dy_30y_bps is None:
        return "Unknown", detail_changes or "insufficient tenor data"

    # Apply the noise threshold uniformly: sub-threshold moves are treated as zero
    # for both Quiet detection and direction-agreement (Mixed) detection. Otherwise
    # a +3 bps 2Y noise gets called Bear Steepener while a -3 bps 2Y noise gets
    # called Mixed against the same long-end move.
    eff_2y = 0.0 if abs(dy_2y_bps) < move_threshold_bps else dy_2y_bps
    eff_10y = 0.0 if abs(dy_10y_bps) < move_threshold_bps else dy_10y_bps
    eff_30y = 0.0 if abs(dy_30y_bps) < move_threshold_bps else dy_30y_bps
    moves = (eff_2y, eff_10y, eff_30y)

    if all(m == 0 for m in moves):
        return "Quiet", detail_changes

    nonzero_signs = {1 if m > 0 else -1 for m in moves if m != 0}
    if len(nonzero_signs) > 1:
        return "Mixed", detail_changes

    # All meaningful (above-threshold) moves point the same direction.
    long_end_avg = (eff_10y + eff_30y) / 2
    rising = sum(moves) > 0
    long_leads = abs(long_end_avg) > abs(eff_2y)

    if rising and long_leads:
        return "Bear Steepener", f"{detail_changes} — long end leading (term premium / supply)"
    if rising and not long_leads:
        return "Bear Flattener", f"{detail_changes} — short end leading (Fed-path repricing)"
    if not rising and not long_leads:
        return "Bull Steepener", f"{detail_changes} — short end leading (cut priced)"
    return "Bull Flattener", f"{detail_changes} — long end leading (duration bid / recession)"


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
