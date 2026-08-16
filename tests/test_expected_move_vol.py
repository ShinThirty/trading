"""options._vol_verdict — the IV/HV row on get_expected_move (pure fn).

This row used to carry a cheap/rich label off trailing realized vol, which reads
"cheap" precisely after a vol spike — when forward vol is about to mean-revert down
and the options are not cheap. The label is gone; the ratio stays as data and the
verdict is delegated to get_variance_risk_premium, which forecasts forward RV off a
far longer history than this tool holds.
"""

import re
from math import exp

from trading_mcp.tools.options import _vol_verdict


def _quiet_closes(n: int = 80, step: float = 0.004) -> list[float]:
    """Alternating small moves — a calm tape with no dominant bar."""
    closes = [100.0]
    for i in range(n):
        closes.append(closes[-1] * exp(step if i % 2 else -step))
    return closes


def test_ratio_carries_no_verdict_at_any_level() -> None:
    """The regression that matters: a bare number, never "0.70 (cheap)"."""
    for iv, hv in ((0.20, 1.00), (1.00, 0.20), (0.50, 0.50)):
        out = _vol_verdict(iv, hv, hv, _quiet_closes())
        assert re.fullmatch(r"\d+\.\d\d", out["IV/HV Ratio (trailing)"])
        # And the verdict is explicitly handed to the tool that can make it.
        assert "get_variance_risk_premium" in out["Vol read"]


def test_ratio_is_still_reported() -> None:
    out = _vol_verdict(0.70, 1.00, 1.00, _quiet_closes())
    assert out["IV/HV Ratio (trailing)"] == "0.70"


def test_missing_inputs_yield_nothing() -> None:
    assert _vol_verdict(None, 1.0, 1.0, _quiet_closes()) == {}
    assert _vol_verdict(0.5, None, 1.0, _quiet_closes()) == {}
    assert _vol_verdict(0.5, 0.0, 1.0, _quiet_closes()) == {}


def test_regime_shift_escalates() -> None:
    out = _vol_verdict(0.50, 0.21, 0.25, _quiet_closes())
    assert "cooling" in out["Vol read"]
    out = _vol_verdict(0.50, 0.25, 0.21, _quiet_closes())
    assert "heating" in out["Vol read"]


def test_stable_regime_does_not_escalate() -> None:
    out = _vol_verdict(0.50, 0.24, 0.25, _quiet_closes())
    assert "⚠" not in out["Vol read"]


def test_single_bar_variance_escalates_over_regime_shift() -> None:
    """A gap sits in both HV windows, so they agree while both run hot.

    HV20 and HV50 are passed as equal here — the regime check cannot see anything.
    Only the concentration statistic catches it.
    """
    closes = _quiet_closes()
    closes.append(closes[-1] * exp(-0.18))  # one violent bar
    out = _vol_verdict(0.50, 0.60, 0.60, closes)
    assert "one bar drives" in out["Vol read"]
    assert "event-inflated" in out["Vol read"]


def test_concentration_check_tolerates_short_history() -> None:
    """Too few bars to measure concentration — fall back, do not raise."""
    out = _vol_verdict(0.50, 0.40, 0.40, [100.0, 101.0, 100.5])
    assert "Vol read" in out
    assert _vol_verdict(0.50, 0.40, 0.40, None)["Vol read"]
    assert _vol_verdict(0.50, 0.40, 0.40, [])["Vol read"]
