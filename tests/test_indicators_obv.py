"""indicators.obv — anchored on-balance volume (pure fn).

Pins the anchor semantics that make a post-gap flow read trustworthy: bars before
the anchor are None, the anchor bar itself is the zero baseline (its own volume is
never signed), and an outsized gap bar stops contributing once anchored past. The
unanchored default must stay byte-identical to the pre-anchor behavior.
"""

from trading_clients import indicators as ta


def _bars(closes: list[float], volumes: list[float]) -> list[dict]:
    """Minimal OHLCV bars — obv only reads close and volume."""
    return [{"close": c, "volume": v} for c, v in zip(closes, volumes)]


def test_unanchored_matches_legacy_behavior() -> None:
    bars = _bars([10.0, 11.0, 10.5, 12.0], [100, 200, 300, 400])
    # Bar 0 is the baseline; +200, -300, +400 thereafter.
    assert ta.obv(bars) == [0.0, 200.0, -100.0, 300.0]


def test_flat_close_leaves_running_total_unchanged() -> None:
    bars = _bars([10.0, 10.0, 11.0], [100, 999, 50])
    assert ta.obv(bars) == [0.0, 0.0, 50.0]


def test_anchor_nones_prior_bars_and_zeroes_the_anchor() -> None:
    bars = _bars([10.0, 11.0, 10.5, 12.0], [100, 200, 300, 400])
    assert ta.obv(bars, 2) == [None, None, 0.0, 400.0]


def test_anchor_excludes_the_gap_bar_it_sits_on() -> None:
    """The whole point: a 10x-volume gap bar must not reach the anchored sum."""
    closes = [100.0, 99.0, 60.0, 62.0, 64.0]
    volumes = [10.0, 10.0, 500.0, 10.0, 10.0]
    bars = _bars(closes, volumes)

    # Unanchored: -10, -500, +10, +10 — the gap bar swamps the recovery and the
    # cumulative read stays deeply negative while price is rising.
    assert ta.obv(bars)[-1] == -490.0
    # Anchored at the gap bar, only the recovery is counted — sign flips.
    assert ta.obv(bars, 2)[-1] == 20.0


def test_anchor_at_last_bar_yields_a_bare_baseline() -> None:
    bars = _bars([10.0, 11.0], [100, 200])
    assert ta.obv(bars, 1) == [None, 0.0]


def test_anchor_past_end_is_all_none() -> None:
    bars = _bars([10.0, 11.0], [100, 200])
    assert ta.obv(bars, 2) == [None, None]
    assert ta.obv(bars, 99) == [None, None]


def test_empty_bars() -> None:
    assert ta.obv([]) == []
    assert ta.obv([], 3) == []


def test_missing_volume_counts_as_zero() -> None:
    bars = [{"close": 10.0}, {"close": 11.0}, {"close": 12.0, "volume": 50}]
    assert ta.obv(bars) == [0.0, 0.0, 50.0]
