"""vrp — variance risk premium math (pure fns).

Pins the realized-variance estimator against synthetic data of known vol, the
ex-post window alignment, the overlapping-sample honesty counter, and the
up-move artifact guard that keeps a one-way rally from reading as cheap options.
"""

import math
import random

from pytest import approx
from trading_clients import vrp


def _gbm(vol: float, n: int, seed: int = 42, start: float = 100.0) -> list[float]:
    """Daily closes from a GBM with a known annualized vol."""
    rng = random.Random(seed)
    d = vol / math.sqrt(vrp.TRADING_DAYS)
    closes = [start]
    for _ in range(n):
        closes.append(closes[-1] * math.exp(rng.gauss(0, d)))
    return closes


def test_realized_vol_recovers_known_vol() -> None:
    closes = _gbm(0.25, 1500)
    # 252-day window averages out most of the sampling noise.
    assert vrp.realized_vol(closes, 252) == approx(0.25, abs=0.03)
    assert math.sqrt(vrp.ewma_variance(closes)) == approx(0.25, abs=0.05)


def test_realized_variance_needs_enough_bars() -> None:
    assert vrp.realized_variance([100.0] * 10, 21) is None
    assert vrp.ewma_variance([100.0] * 10) is None


def test_flat_prices_have_zero_variance() -> None:
    assert vrp.realized_variance([100.0] * 30, 21) == approx(0.0)


def test_ewma_series_matches_scalar_at_the_last_bar() -> None:
    closes = _gbm(0.30, 400, seed=7)
    series = vrp.ewma_variance_series(closes)
    assert series[-1] == approx(vrp.ewma_variance(closes))
    # Seed window is unknowable, so those entries stay None.
    assert series[0] is None
    assert series[20] is None
    assert series[21] is not None


def test_snapshot_vrp_arithmetic() -> None:
    closes = _gbm(0.20, 800, seed=3)
    snap = vrp.vrp_snapshot("TEST", 0.30, closes)
    rv = snap.rv_forecast
    assert snap.ratio == approx(0.30 / rv)
    assert snap.vrp_vol_points == approx((0.30 - rv) * 100)
    assert snap.vrp_variance_points == approx((0.09 - rv**2) * 10000)
    # Variance points and vol points must agree in sign.
    assert (snap.vrp_vol_points > 0) == (snap.vrp_variance_points > 0)


def test_classify_bands() -> None:
    assert vrp.classify(1.40)[0] == "Rich"
    assert vrp.classify(1.30)[0] == "Rich"
    assert vrp.classify(1.20)[0] == "Modestly rich"
    assert vrp.classify(1.00)[0] == "Fair"
    assert vrp.classify(0.94)[0] == "Cheap"


def test_ex_post_series_alignment_and_hit_rate() -> None:
    closes = _gbm(0.20, 600, seed=11)
    dates = [f"d{i:04d}" for i in range(len(closes))]
    dated = list(zip(dates, closes, strict=True))
    # Implied pinned 4 vol points above the true 20% → premium nearly always earned.
    implied = [(d, 0.24) for d in dates]

    series = vrp.vrp_series("TEST", implied, dated, horizon_days=21)

    # Every date except the final horizon (no forward window) yields an observation.
    assert len(series.observations) == len(dates) - 21
    assert series.mean == approx((0.24**2 - 0.20**2) * 10000, abs=60)
    assert series.hit_rate > 80
    # The honest n: overlapping dailies are not independent evidence.
    assert series.independent_windows == len(series.observations) // 21


def test_ex_post_series_skips_dates_missing_from_prices() -> None:
    closes = _gbm(0.20, 200, seed=5)
    dates = [f"d{i:04d}" for i in range(len(closes))]
    dated = list(zip(dates, closes, strict=True))
    implied = [("nonexistent", 0.24), *[(d, 0.24) for d in dates]]

    series = vrp.vrp_series("TEST", implied, dated, horizon_days=21)
    assert all(o[0] != "nonexistent" for o in series.observations)


def test_percentile_rank() -> None:
    assert vrp.percentile_rank([1, 2, 3, 4], 3.5) == approx(75.0)
    assert vrp.percentile_rank([], 1.0) is None


def test_downside_vol_equals_total_under_symmetry() -> None:
    closes = _gbm(0.25, 900, seed=17)
    total = vrp.realized_vol(closes, 252)
    down = vrp.downside_realized_vol(closes, 252)
    # The 2x scaling makes the two comparable when up/down days are balanced.
    assert down == approx(total, rel=0.15)


def test_upmove_artifact_fires_on_one_way_rally() -> None:
    closes = [100.0]
    for _ in range(299):
        closes.append(closes[-1] * 1.0005)  # quiet drift
    for _ in range(21):
        closes.append(closes[-1] * 1.010)  # one-way rally

    snap = vrp.vrp_snapshot("RALLY", 0.15, closes)
    assert snap.rv_downside == approx(0.0)
    assert snap.trailing_return > 0.20
    assert snap.upmove_artifact is True
    assert "Up-move artifact" in snap.to_output()


def test_upmove_artifact_silent_on_two_sided_tape() -> None:
    # A round trip: same realized vol, but down-days present and net return ~0.
    closes = [100.0] * 280
    for i in range(1, 280):
        closes[i] = closes[i - 1] * 1.0005
    for i in range(21):
        closes.append(closes[-1] * (0.98 if i % 2 == 0 else 1.021))

    snap = vrp.vrp_snapshot("CHOP", 0.15, closes)
    assert snap.upmove_artifact is False
    assert "Up-move artifact" not in snap.to_output()


def test_window_labels_follow_the_requested_window() -> None:
    closes = _gbm(0.25, 400, seed=23)
    out = vrp.vrp_snapshot("TEST", 0.30, closes, short_window=30).to_output()
    assert "RV trailing (30d)" in out
    assert "Trailing return (30d)" in out
    assert "RV downside-only (30d)" in out
    assert "(21d)" not in out


def _vol_regime(quiet_vol: float, spike_vol: float, spike_len: int, seed: int) -> list[float]:
    """Long quiet history, then a burst of high vol at the end."""
    closes = _gbm(quiet_vol, 900, seed=seed)
    rng = random.Random(seed + 1)
    d = spike_vol / math.sqrt(vrp.TRADING_DAYS)
    for _ in range(spike_len):
        closes.append(closes[-1] * math.exp(rng.gauss(0, d)))
    return closes


def test_har_recovers_constant_vol() -> None:
    closes = _gbm(0.25, 1200, seed=31)
    har = vrp.har_forecast_variance(closes, 21)
    assert math.sqrt(har) == approx(0.25, abs=0.06)


def test_har_needs_enough_history() -> None:
    assert vrp.har_forecast_variance(_gbm(0.25, 60, seed=2), 21) is None
    assert vrp.fit_har(_gbm(0.25, 60, seed=2), 21) is None


def test_har_mean_reverts_faster_than_ewma_after_a_spike() -> None:
    """The defect that motivated HAR: EWMA keeps a crash at high weight for weeks."""
    closes = _vol_regime(quiet_vol=0.20, spike_vol=1.00, spike_len=15, seed=41)

    ewma = math.sqrt(vrp.ewma_variance(closes))
    har = math.sqrt(vrp.har_forecast_variance(closes, 21))

    # Both see the spike, but HAR pulls back toward the long-run level.
    assert ewma > 0.45, "EWMA should still be dominated by the spike"
    assert har < ewma, "HAR must mean-revert below the EWMA estimate"


def test_snapshot_prefers_har_and_shows_ewma_for_contrast() -> None:
    closes = _gbm(0.25, 1200, seed=53)
    snap = vrp.vrp_snapshot("TEST", 0.30, closes)
    assert snap.forecast_method == "HAR"
    assert snap.rv_forecast_ewma is not None
    out = snap.to_output()
    assert "RV forecast (HAR)" in out
    assert "superseded" in out


def test_snapshot_falls_back_to_ewma_on_short_history() -> None:
    closes = _gbm(0.25, 120, seed=59)
    snap = vrp.vrp_snapshot("TEST", 0.30, closes)
    assert snap.forecast_method == "EWMA"
    assert "RV forecast (EWMA)" in snap.to_output()
    assert "superseded" not in snap.to_output()


def test_regime_break_guard_fires_on_elevated_realized_vol() -> None:
    closes = _vol_regime(quiet_vol=0.18, spike_vol=0.90, spike_len=25, seed=67)
    snap = vrp.vrp_snapshot("SPIKED", 0.30, closes)
    assert snap.rv_short_percentile > 80
    assert snap.regime_break is True
    assert "Regime break" in snap.to_output()


def test_regime_break_guard_silent_in_a_calm_tape() -> None:
    closes = _gbm(0.22, 1200, seed=71)
    snap = vrp.vrp_snapshot("CALM", 0.30, closes)
    assert snap.regime_break is False
    assert "Regime break" not in snap.to_output()
