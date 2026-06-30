"""VolumeProfile + VolumeRate — the shadow-mode volume observers.

Pins the POC / value-area / HVN-LVN math and the break-side density read (the
candidate runner-leg signal, recorded but gating nothing), plus the rolling
volume-rate window + decayed-baseline ratio. Pure computation, no I/O.
"""

import pytest
from trading_scalper.volume import VolumeProfile, VolumeRate


def _canonical() -> VolumeProfile:
    """A 5-bin profile: POC at 719.40, a thin LVN tail at 719.70."""
    p = VolumeProfile()  # bucket 0.10, VA 70%, HVN 1.5x / LVN 0.3x
    p.add(719.40, 100)
    p.add(719.50, 50)
    p.add(719.30, 30)
    p.add(719.60, 20)
    p.add(719.70, 5)
    return p


def test_add_buckets_and_poc() -> None:
    p = _canonical()
    assert p.total == pytest.approx(205.0)
    assert len(p._bins) == 5
    assert p.poc() == pytest.approx(719.40)  # heaviest bin


def test_add_ignores_nonpositive_and_none_size() -> None:
    p = VolumeProfile()
    p.add(719.40, None)
    p.add(719.40, 0)
    p.add(719.40, -5)
    assert p.total == 0.0
    assert p.poc() is None
    assert p.value_area() is None
    assert p.classify(719.40) == "empty"


def test_same_dime_accumulates_one_bin() -> None:
    p = VolumeProfile()
    p.add(719.41, 10)  # rounds to the 719.40 bin
    p.add(719.44, 10)  # same bin
    assert len(p._bins) == 1
    assert p.total == pytest.approx(20.0)


def test_value_area_expands_to_target() -> None:
    val, vah = _canonical().value_area()  # target 0.70 * 205 = 143.5
    # POC 719.40 (100) annexes the heavier side (above: 75 > below: 30) -> +719.50 (50) = 150
    assert val == pytest.approx(719.40)
    assert vah == pytest.approx(719.50)


def test_classify_hvn_lvn_normal() -> None:
    p = _canonical()  # mean bin = 205 / 5 = 41
    assert p.classify(719.40) == "HVN"  # 100 >= 1.5 * 41
    assert p.classify(719.70) == "LVN"  # 5 < 0.3 * 41
    assert p.classify(719.50) == "normal"  # 50, neither


def test_break_side_read_void_above_resistance() -> None:
    p = VolumeProfile()
    for px in (719.00, 719.10, 719.20):  # a block below the wall, air above
        p.add(px, 100)
    # wall 719.30 resistance, reach 0.30 -> outside (719.40/.50/.60)=0 vs inside=300
    assert p.break_side_read(719.30, "resistance", 0.30) == "void"


def test_break_side_read_hvn_above_resistance() -> None:
    p = VolumeProfile()
    for px in (719.00, 719.10, 719.20):  # thin setup side
        p.add(px, 10)
    for px in (719.40, 719.50, 719.60):  # thick wall ahead
        p.add(px, 200)
    assert p.break_side_read(719.30, "resistance", 0.30) == "hvn"


def test_break_side_read_mixed_when_comparable() -> None:
    p = VolumeProfile()
    for px in (719.00, 719.10, 719.20, 719.40, 719.50, 719.60):
        p.add(px, 100)  # symmetric across the wall
    assert p.break_side_read(719.30, "resistance", 0.30) == "mixed"


def test_break_side_read_support_mirror() -> None:
    p = VolumeProfile()
    for px in (719.40, 719.50, 719.60):  # block above, air below
        p.add(px, 100)
    # support: break side is *below*; below is empty vs above (inside) = 300 -> void
    assert p.break_side_read(719.30, "support", 0.30) == "void"


def test_break_side_read_empty_without_setup_side() -> None:
    p = VolumeProfile()
    p.add(719.50, 100)  # only outside the wall, nothing inside
    assert p.break_side_read(719.30, "resistance", 0.30) == "empty"


def test_snapshot_shape() -> None:
    snap = _canonical().snapshot()
    assert snap == {
        "total_vol": 205.0,
        "n_bins": 5,
        "poc": pytest.approx(719.40),
        "val": pytest.approx(719.40),
        "vah": pytest.approx(719.50),
    }


# ── VolumeRate ──────────────────────────────────────────────────────────────


def test_rate_sums_within_window_and_evicts() -> None:
    r = VolumeRate(window_s=60.0)
    r.add(100, ms=0)
    r.add(50, ms=30_000)  # +30s, both inside the 60s window
    assert r.rate() == pytest.approx(150.0)
    r.add(20, ms=70_000)  # now: ms=0 is 70s back -> evicted; 30s + 70s prints survive
    assert r.rate() == pytest.approx(70.0)


def test_ms_less_print_is_ignored_by_rate() -> None:
    r = VolumeRate()
    r.add(100, ms=0)
    r.add(999, ms=None)  # no timeline slot -> ignored, not inflating the window
    assert r.rate() == pytest.approx(100.0)


def test_ratio_reads_expansion_vs_baseline() -> None:
    r = VolumeRate(window_s=60.0, baseline_halflife_s=300.0)
    r.add(10, ms=0)  # baseline seeds to the first window volume (10)
    assert r.ratio() == pytest.approx(1.0)
    r.add(200, ms=1_000)  # window jumps to 210; baseline barely moves over 1s
    assert r.ratio() > 1.5  # expanding volume reads well above baseline


def test_rate_snapshot_shape() -> None:
    r = VolumeRate()
    r.add(40, ms=0)
    snap = r.snapshot()
    assert set(snap) == {"rate", "baseline", "ratio"}
    assert snap["rate"] == pytest.approx(40.0)
    assert snap["ratio"] == pytest.approx(1.0)


def test_empty_rate_snapshot_is_null_baseline() -> None:
    r = VolumeRate()
    assert r.snapshot() == {"rate": 0.0, "baseline": None, "ratio": None}
