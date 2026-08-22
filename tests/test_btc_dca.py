"""btc_regime — ATH selection and the DCA sizing ladder it feeds (pure fns).

Guards the failure that motivated all_time_high: a daily bar series is capped
at 250 bars by the provider, so on a 7-day-a-week market it spans only ~8
months. A cycle top older than that is invisible, the "ATH" quietly becomes a
recent local high, and dca_sizing buys *less* the further price falls below the
real peak — the exact inverse of what the ladder is for.
"""

from trading_clients import btc_regime as btc

# The August-2026 reading that surfaced the bug. Daily closes reached back only
# to 2025-12-15 and topped out at the January-2026 local high; the true peak was
# October 2025, one full cycle high earlier.
SPOT = 78_526.32
TRUE_ATH = 126_244.81  # Oct-2025 monthly high
DAILY_WINDOW_MAX = 96_302.09  # best close inside the 250-bar daily window


def test_monthly_highs_outrank_the_daily_window() -> None:
    """The whole point: a top outside the daily window still wins."""
    ath = btc.all_time_high([TRUE_ATH, 110_000.0], [DAILY_WINDOW_MAX, 80_000.0], SPOT)
    assert ath == TRUE_ATH


def test_daily_closes_are_the_fallback_when_monthly_is_missing() -> None:
    """A failed monthly fetch degrades rather than dropping the row."""
    assert btc.all_time_high([], [DAILY_WINDOW_MAX, 80_000.0], SPOT) == DAILY_WINDOW_MAX


def test_no_bars_yields_no_ath() -> None:
    assert btc.all_time_high([], []) is None
    assert btc.all_time_high([], [], SPOT) is None


def test_ath_is_never_below_spot() -> None:
    """A high being set right now must not read as a drawdown."""
    assert btc.all_time_high([100_000.0], [], 130_000.0) == 130_000.0


def test_ath_ignores_bar_ordering() -> None:
    assert btc.all_time_high([90_000.0, TRUE_ATH, 60_000.0], []) == TRUE_ATH


def test_true_ath_lands_a_full_tier_below_the_windowed_one() -> None:
    """The regression, stated as the number that actually changed: -18% vs -38%."""
    windowed = btc.all_time_high([], [DAILY_WINDOW_MAX], SPOT)
    correct = btc.all_time_high([TRUE_ATH], [DAILY_WINDOW_MAX], SPOT)
    assert windowed is not None and correct is not None

    assert "$150/week" in btc.dca_sizing(SPOT, windowed)  # "recovering"
    assert "$200/week" in btc.dca_sizing(SPOT, correct)  # "deep discount"


def test_dca_ladder_tier_boundaries() -> None:
    """Thresholds are inclusive at the deeper tier: -30% buys the $200 rung."""
    ath = 100_000.0
    assert "$400/week" in btc.dca_sizing(50_000.0, ath)  # -50%, capitulation
    assert "$200/week" in btc.dca_sizing(70_000.0, ath)  # -30%, deep discount
    assert "$150/week" in btc.dca_sizing(85_000.0, ath)  # -15%, recovering
    assert "$100/week" in btc.dca_sizing(99_000.0, ath)  # -1%, near highs
    assert "$100/week" in btc.dca_sizing(ath, ath)  # at the high


def test_dca_sizing_survives_a_zero_ath() -> None:
    """Guards the div-by-zero path rather than leaving it to chance."""
    assert "$100/week" in btc.dca_sizing(SPOT, 0.0)
