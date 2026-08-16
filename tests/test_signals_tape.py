"""signals._classify_tape — 2-week tape pattern classification (pure fn).

The tag is consumed as ground truth ("use it directly, do not re-derive"), so the
cases that matter are the ones where endpoint-to-endpoint stats hide the shape: a
gap several sessions back inflates the range and flattens the net, which the
range/net branches read as two-way chop when the tape was one event plus a one-way
move. Existing labels are pinned so the added branch stays additive.
"""

from pytest import approx
from trading_mcp.tools.signals import (
    _classify_tape,
    _dominant_prior_gap,
    _fully_digested_gap,
)


def _tape(closes: list[float], opens: list[float] | None = None) -> dict:
    """Classify from closes, defaulting opens to the prior close (i.e. no gaps)."""
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) * 1.005 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.995 for o, c in zip(opens, closes)]
    return _classify_tape(closes, opens, highs, lows)


# ── existing labels: pinned against regression ──────────────────────


def test_steady_rally() -> None:
    assert _tape([100 + i * 2 for i in range(10)])["pattern"] == "Steady Rally"


def test_steady_decline() -> None:
    assert _tape([100 - i * 2 for i in range(10)])["pattern"] == "Steady Decline"


def test_quiet() -> None:
    assert _tape([100 + (i % 2) * 0.3 for i in range(10)])["pattern"] == "Quiet"


def test_drift() -> None:
    """Range wide enough to clear Quiet (>=5%) but under Choppy's 15%, net near flat."""
    closes = [100.0, 104.0, 100.0, 106.0, 101.0, 105.0, 100.0, 104.0, 101.0, 102.0]
    result = _tape(closes)
    assert 5 <= result["range_pct"] < 15
    assert result["pattern"] == "Drift"


def test_todays_gap_still_wins() -> None:
    """Today's gap keeps its bare 5% test and is classified before the window scan."""
    closes = [100.0] * 9 + [88.0]
    opens = [100.0] * 9 + [89.0]  # -11% gap today
    assert _tape(closes, opens)["pattern"] == "Gap-Down"


def test_rally_then_gap_down_still_wins() -> None:
    closes = [100, 108, 116, 124, 132, 140, 148, 156, 164, 130]
    opens = [100, 108, 116, 124, 132, 140, 148, 156, 164, 132]  # -19.5% gap today
    assert _tape([float(c) for c in closes], [float(o) for o in opens])["pattern"] == (
        "Rally → Gap-Down"
    )


# ── the added branch: a gap several sessions back ───────────────────


def test_prior_gap_down_with_recovery_is_not_choppy() -> None:
    """The WDC shape: one earnings break, then a one-way recovery."""
    closes = [100.0, 101.0, 100.0, 87.0, 84.0, 85.0, 84.5, 88.0, 94.0, 98.0]
    opens = [100.0, 101.0, 100.0, 88.0, 84.0, 85.0, 84.5, 88.0, 94.0, 98.0]
    result = _tape(closes, opens)
    assert result["pattern"] == "Gap-Down → Recovery"
    # Reclaimed most of the drop from the post-gap trough back toward the pre-gap level.
    assert "reclaimed" in result["pattern_note"]
    # Before the fix this landed in Choppy: wide range, near-flat net.
    assert result["range_pct"] >= 15


def test_prior_gap_down_still_basing() -> None:
    closes = [100.0, 101.0, 100.0, 87.0, 84.0, 85.0, 84.5, 85.0, 86.0, 86.5]
    opens = [100.0, 101.0, 100.0, 88.0, 84.0, 85.0, 84.5, 85.0, 86.0, 86.5]
    assert _tape(closes, opens)["pattern"] == "Gap-Down → Basing"


def test_prior_gap_up_held() -> None:
    closes = [100.0, 99.0, 100.0, 113.0, 115.0, 116.0, 117.0, 118.0, 119.0, 120.0]
    opens = [100.0, 99.0, 100.0, 112.0, 115.0, 116.0, 117.0, 118.0, 119.0, 120.0]
    assert _tape(closes, opens)["pattern"] == "Gap-Up → Hold"


def test_prior_gap_up_faded() -> None:
    closes = [100.0, 99.0, 100.0, 113.0, 115.0, 112.0, 108.0, 104.0, 101.0, 100.5]
    opens = [100.0, 99.0, 100.0, 112.0, 115.0, 112.0, 108.0, 104.0, 101.0, 100.5]
    assert _tape(closes, opens)["pattern"] == "Gap-Up → Fade"


# ── the scale gate ──────────────────────────────────────────────────


def test_gap_must_be_outsized_for_this_name() -> None:
    """A 6% gap is not an event for a name that moves 6% daily — no label change."""
    closes = [100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0, 106.0]
    opens = [100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0, 106.0, 100.0, 106.0]
    # One 6% open gap exists but sits inside routine 6% daily churn.
    opens[3] = 106.0
    assert _dominant_prior_gap(closes, opens) is None
    assert _tape(closes, opens)["pattern"] not in {"Gap-Down → Recovery", "Gap-Down → Basing"}


def test_baseline_yardstick_overrides_the_quiet_post_gap_window() -> None:
    """A gap looks outsized against the calm days that follow it, not against normal tape.

    Same window either way; only the yardstick differs. Measured in-window the 6% gap
    clears the bar, because the post-gap sessions are quiet. Measured against a longer
    history of 6% daily churn it does not.
    """
    closes = [100.0, 100.5, 100.2, 94.0, 94.2, 94.1, 94.3, 94.2, 94.4, 94.3]
    opens = [100.0, 100.5, 100.2, 94.2, 94.2, 94.1, 94.3, 94.2, 94.4, 94.3]
    assert _dominant_prior_gap(closes, opens) is not None
    churny = [100.0 + (i % 2) * 6.0 for i in range(60)] + closes
    assert _dominant_prior_gap(closes, opens, churny) is None


def test_fully_reclaimed_gap_falls_through_to_a_trend_label() -> None:
    """Past the pre-gap level the event is digested — and the ratio would exceed 100%."""
    closes = [100.0, 100.5, 100.0, 92.0, 95.0, 99.0, 103.0, 106.0, 109.0, 112.0]
    opens = [100.0, 100.5, 100.0, 92.5, 95.0, 99.0, 103.0, 106.0, 109.0, 112.0]
    assert _dominant_prior_gap(closes, opens) is not None  # the gap is still found
    assert _fully_digested_gap(closes, opens, closes) is None  # but no longer describes it
    assert _tape(closes, opens)["pattern"] == "Steady Rally"


def test_fully_faded_gap_up_falls_through() -> None:
    closes = [100.0, 99.5, 100.0, 107.0, 105.0, 102.0, 99.0, 96.0, 94.0, 92.0]
    opens = [100.0, 99.5, 100.0, 106.5, 105.0, 102.0, 99.0, 96.0, 94.0, 92.0]
    assert _fully_digested_gap(closes, opens, closes) is None
    assert _tape(closes, opens)["pattern"] == "Steady Decline"


def test_sub_five_percent_gap_never_qualifies() -> None:
    """Quiet name, 3% gap — below the absolute floor even though it is 10x its norm."""
    closes = [100.0, 100.3, 100.1, 103.2, 103.4, 103.3, 103.5, 103.4, 103.6, 103.5]
    opens = [100.0, 100.3, 100.1, 103.1, 103.4, 103.3, 103.5, 103.4, 103.6, 103.5]
    assert _dominant_prior_gap(closes, opens) is None


def test_largest_gap_wins_when_several_qualify() -> None:
    closes = [100.0, 100.0, 92.0, 92.0, 80.0, 80.0, 81.0, 82.0, 83.0, 84.0]
    opens = [100.0, 100.0, 93.0, 92.0, 84.0, 80.0, 81.0, 82.0, 83.0, 84.0]
    found = _dominant_prior_gap(closes, opens)
    assert found is not None
    assert found[0] == 4  # the -8.7% gap beats the -7.0% one


def test_today_is_excluded_from_the_scan() -> None:
    closes = [100.0] * 9 + [88.0]
    opens = [100.0] * 9 + [89.0]
    assert _dominant_prior_gap(closes, opens) is None


# ── net_pct decomposition ───────────────────────────────────────────


def test_endpoint_net_hides_a_gap_and_recovery() -> None:
    """The blind spot: a break plus a rip nets to ~flat, so the 2W move reads quiet.

    net_pct is deliberately left raw — a gap is real price you would pay — but the
    path it conceals is reported alongside it.
    """
    closes = [100.0, 101.0, 100.0, 87.0, 84.0, 85.0, 84.5, 88.0, 94.0, 98.0]
    opens = [100.0, 101.0, 100.0, 88.0, 84.0, 85.0, 84.5, 88.0, 94.0, 98.0]
    r = _tape(closes, opens)
    assert r["net_pct"] == approx(-2.0, abs=0.1)  # endpoint says "barely moved"
    assert r["net_since_gap"] == approx(12.6, abs=0.5)  # path says "+13% off the low"
    assert r["gap_move"] == approx(-12.0, abs=0.1)
    assert r["gap_sessions_ago"] == 6


def test_no_gap_means_no_decomposition() -> None:
    r = _tape([100 + i * 2 for i in range(10)])
    assert r["net_since_gap"] is None
    assert r["gap_move"] is None
    assert r["gap_sessions_ago"] is None


def test_decomposition_survives_a_fully_digested_gap() -> None:
    """Distinct from the pattern label: a round-tripped gap still skews the endpoint.

    The tag falls through to a trend label, but net_pct is still measuring across the
    gap, so the decomposition must persist where `_fully_digested_gap` returns None.
    """
    closes = [100.0, 100.5, 100.0, 92.0, 95.0, 99.0, 103.0, 106.0, 109.0, 112.0]
    opens = [100.0, 100.5, 100.0, 92.5, 95.0, 99.0, 103.0, 106.0, 109.0, 112.0]
    r = _tape(closes, opens)
    assert r["pattern"] == "Steady Rally"
    assert _fully_digested_gap(closes, opens, closes) is None
    assert r["net_since_gap"] == approx(21.7, abs=0.5)


# ── degenerate inputs ───────────────────────────────────────────────


def test_too_few_bars_returns_empty() -> None:
    assert _classify_tape([100.0], [100.0], [100.0], [100.0]) == {}


def test_gap_scan_handles_short_and_ragged_input() -> None:
    assert _dominant_prior_gap([], []) is None
    assert _dominant_prior_gap([100.0, 90.0], [100.0, 95.0]) is None
    assert _dominant_prior_gap([100.0, 90.0, 80.0], [100.0]) is None
