"""HY credit-spread regime classifier + slow-deterioration trap detector."""


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
