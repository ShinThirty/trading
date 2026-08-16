"""indicators — single-bar concentration diagnostics (pure fns).

`window_concentration` (largest element's share) and `window_effective_n` (inverse
Herfindahl) answer "is this window's reading really one bar?" — the check that keeps
a gap-dominated HV10 or %B from being read as a measurement of the tape.

The pair exists because they fail differently: max-share is blind to a two-sided
event that splits its weight over two bars, which is exactly the earnings pop /
next-day give-back shape. Effective-N sees both.
"""

from pytest import approx
from trading_clients import indicators as ta


def test_even_window_is_unconcentrated() -> None:
    vals = [1.0] * 10
    assert ta.window_concentration(vals, 10)[-1] == approx(10.0)  # fair share = 100/10
    assert ta.window_effective_n(vals, 10)[-1] == approx(10.0)  # all 10 bars count


def test_single_dominant_bar() -> None:
    vals = [0.0] * 9 + [100.0]
    assert ta.window_concentration(vals, 10)[-1] == approx(100.0)
    assert ta.window_effective_n(vals, 10)[-1] == approx(1.0)


def test_two_sided_event_hides_from_max_share_but_not_effective_n() -> None:
    """The reason both functions exist: an earnings pop plus its give-back."""
    vals = [1.0] * 8 + [50.0, 50.0]
    # Each event bar owns only ~46% — indistinguishable from routine top-heaviness.
    assert ta.window_concentration(vals, 10)[-1] == approx(46.3, abs=0.5)
    # But the window carries the information of barely two bars — a shade over 2.0,
    # since the eight quiet bars still contribute a sliver of weight.
    assert ta.window_effective_n(vals, 10)[-1] == approx(2.33, abs=0.02)


def test_warmup_positions_are_none() -> None:
    vals = [1.0, 2.0, 3.0]
    assert ta.window_concentration(vals, 3) == [None, None, approx(50.0)]
    assert ta.window_effective_n(vals, 3)[:2] == [None, None]


def test_window_longer_than_series() -> None:
    assert ta.window_concentration([1.0, 2.0], 5) == [None, None]
    assert ta.window_effective_n([1.0, 2.0], 5) == [None, None]


def test_non_positive_window_totals_are_none() -> None:
    zeros = [0.0] * 5
    assert ta.window_concentration(zeros, 3)[-1] is None
    assert ta.window_effective_n(zeros, 3)[-1] is None


def test_degenerate_periods() -> None:
    assert ta.window_concentration([1.0, 2.0], 0) == [None, None]
    assert ta.window_effective_n([1.0, 2.0], -1) == [None, None]
    assert ta.window_concentration([], 3) == []
    assert ta.window_effective_n([], 3) == []


def test_effective_n_never_exceeds_the_window() -> None:
    for vals in ([1.0] * 20, [5.0, 1.0, 3.0, 9.0, 2.0] * 4, list(range(1, 21))):
        for v in ta.window_effective_n([float(x) for x in vals], 10):
            if v is not None:
                assert 1.0 <= v <= 10.0 + 1e-9


def test_concentration_slides_with_the_window() -> None:
    """A spike stops counting once it exits the lookback."""
    vals = [1.0, 1.0, 100.0, 1.0, 1.0, 1.0]
    series = ta.window_concentration(vals, 3)
    assert series[2] == approx(98.0, abs=0.1)  # spike in window
    assert series[5] == approx(33.3, abs=0.1)  # spike gone, back to even


def test_true_ranges_matches_atr_inputs() -> None:
    bars = [
        {"high": 11.0, "low": 9.0, "close": 10.0},
        {"high": 12.0, "low": 10.5, "close": 11.5},  # gap up: |H-prevC| = 2.0 wins
        {"high": 11.0, "low": 5.0, "close": 6.0},  # H-L = 6.0 wins
    ]
    assert ta.true_ranges(bars) == [2.0, 2.0, 6.5]
    assert ta.true_ranges([]) == []
