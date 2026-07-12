"""BreakoutTracker — the false-break-reversal / confirmed-break-retest verdict machine.

Synthetic ``(price, ms)`` ticks drive every transition. Timers/margins are set small and
explicit per-test so the geometry is what's under test, not the (recalibrating) defaults.
Resistance and support are exercised as mirrors: support flips inside↔outside and the
verdict directions, but runs the identical machine. Prices/margins are /ES-scale.
"""

from trading_scalper.breakout import BreakoutTracker, Phase, Verdict

# Compact, fast-resolving tunables shared across the geometry tests (/ES point scale). The
# excursion floor is set low here so the small synthetic pokes still exercise the transitions;
# the chop-filtering floor itself is tested separately (the live default is 7.5).
_KW = dict(
    break_margin=1.0,
    min_break_excursion=1.0,
    follow_through_margin=10.0,
    confirm_s=10.0,
    failure_window_s=60.0,
    reentry_margin=1.0,
    retest_proximity=2.0,
    retest_window_s=60.0,
)


def _res() -> BreakoutTracker:
    return BreakoutTracker(price=6250.0, side="resistance", **_KW)


def _sup() -> BreakoutTracker:
    return BreakoutTracker(price=6240.0, side="support", **_KW)


# ── arming: must witness the inside (setup) side first ──────────────


def test_cold_start_outside_does_not_track() -> None:
    t = _res()
    # first-ever tick already extended above the wall — never saw the setup side
    assert t.update(6255.0, ms=0) is None
    assert t.phase is Phase.WATCHING  # not armed; a later cross from here won't fire
    assert t.update(6255.5, ms=1000) is None and t.phase is Phase.WATCHING


def test_witnessing_inside_arms_to_inside() -> None:
    t = _res()
    assert t.update(6249.0, ms=0) is None
    assert t.phase is Phase.INSIDE


# ── REVERSAL: cross out, snap back inside, never committed ──────────


def test_resistance_failed_break_fires_reversal() -> None:
    t = _res()
    t.update(6249.0, ms=0)  # inside -> arm
    assert t.update(6252.0, ms=1000) is None and t.phase is Phase.CROSSED  # poked above
    assert t.update(6255.0, ms=2000) is None  # still out, not yet committed (max_ex 5.0 < 10.0)
    v = t.update(6248.5, ms=3000)  # snapped back >= reentry_margin inside, within failure_window
    assert v is Verdict.REVERSAL and t.phase is Phase.DONE


def test_support_failed_break_fires_reversal_mirror() -> None:
    t = _sup()
    t.update(6241.0, ms=0)  # above support -> arm (inside = above)
    assert t.update(6238.0, ms=1000) is None and t.phase is Phase.CROSSED  # poked below
    v = t.update(6241.5, ms=2000)  # snapped back up >= reentry inside the window
    assert v is Verdict.REVERSAL


def test_snap_back_after_failure_window_does_not_reverse() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    t.update(6253.0, ms=1000)  # cross at t0=1000
    v = t.update(6248.0, ms=70_000)  # snapped back, but 69s later (> 60s window) -> not a fail
    assert v is None and t.phase is Phase.INSIDE  # dropped, re-armed for a fresh attempt


def test_explosive_run_blocks_reversal_via_follow_through() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    t.update(6253.0, ms=1000)
    assert t.update(6262.0, ms=2000) is None and t.phase is Phase.CONFIRMED  # max_ex 12.0 >= 10.0
    # even a snap-back now cannot reverse — the break already committed
    assert t.update(6249.0, ms=3000) is None and t.phase is Phase.DONE


# ── GO_WITH: confirm (by time or distance), retest, resume ──────────


def test_resistance_confirm_by_time_then_retest_resume_fires_go_with() -> None:
    t = _res()
    t.update(6249.0, ms=0)  # arm
    t.update(6252.0, ms=1000)  # cross -> CROSSED
    assert t.update(6254.0, ms=12_000) is None and t.phase is Phase.CONFIRMED  # held 11s >= 10s
    assert t.update(6251.0, ms=13_000) is None  # pulled back within retest_proximity (2.0)
    v = t.update(6252.0, ms=14_000)  # resumed outward past break_margin -> go-with
    assert v is Verdict.GO_WITH and t.phase is Phase.DONE


def test_support_confirm_then_retest_resume_fires_go_with_mirror() -> None:
    t = _sup()
    t.update(6241.0, ms=0)
    t.update(6238.0, ms=1000)  # breakdown cross
    assert t.update(6236.0, ms=12_000) is None and t.phase is Phase.CONFIRMED  # held >= confirm_s
    assert t.update(6239.0, ms=13_000) is None  # retest back up to the wall
    v = t.update(6238.0, ms=14_000)  # resumed downward -> continuation short
    assert v is Verdict.GO_WITH


def test_confirm_by_distance_without_timestamps() -> None:
    t = _res()
    t.update(6249.0, ms=None)  # arm (geometry only)
    t.update(6252.0, ms=None)  # cross
    assert t.update(6261.0, ms=None) is None and t.phase is Phase.CONFIRMED  # distance confirm


def test_confirmed_but_no_retest_does_not_chase() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    t.update(6252.0, ms=1000)
    t.update(6254.0, ms=12_000)  # CONFIRMED at 12_000
    # price runs away and never retests; window (60s) lapses
    assert t.update(6280.0, ms=20_000) is None and t.phase is Phase.CONFIRMED
    assert t.update(6290.0, ms=80_000) is None and t.phase is Phase.DONE  # window passed, no chase


def test_confirmed_then_full_failure_yields_nothing() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    t.update(6252.0, ms=1000)
    t.update(6254.0, ms=12_000)  # CONFIRMED
    # collapses fully back inside before any retest-resume -> no go-with, too late to reverse
    assert t.update(6249.0, ms=13_000) is None and t.phase is Phase.DONE


# ── re-arming for a fresh attempt ───────────────────────────────────


def test_done_rearms_when_price_returns_inside() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    t.update(6253.0, ms=1000)
    assert t.update(6248.0, ms=2000) is Verdict.REVERSAL  # first attempt -> DONE
    assert t.update(6247.0, ms=3000) is None and t.phase is Phase.INSIDE  # well inside -> re-armed
    # a fresh attempt can now resolve again
    t.update(6253.0, ms=4000)
    assert t.update(6248.0, ms=5000) is Verdict.REVERSAL


def test_poke_under_break_margin_does_not_start_attempt() -> None:
    t = _res()
    t.update(6249.0, ms=0)
    assert t.update(6250.5, ms=1000) is None and t.phase is Phase.INSIDE  # < break_margin (1.0)


# ── excursion floor: a graze that never committed is not a "failed break" ──


def test_uncommitted_poke_snapback_does_not_reverse() -> None:
    # crossed the wall but only by 2.0 (< min_break_excursion 5.0) before snapping back —
    # it never *broke*, so it's chop, not a failed break. (The 6/18 chop machine-gun fix.)
    t = BreakoutTracker(price=6250.0, side="resistance", **{**_KW, "min_break_excursion": 5.0})
    t.update(6249.0, ms=0)  # arm
    t.update(6252.0, ms=1000)  # crossed by break_margin but max_ex only 2.0
    v = t.update(6248.5, ms=2000)  # snapped back — but uncommitted → no reversal, re-track
    assert v is None and t.phase is Phase.INSIDE


def test_committed_poke_snapback_reverses_above_floor() -> None:
    # same shape, but the poke commits past the floor → a genuine failed break
    t = BreakoutTracker(price=6250.0, side="resistance", **{**_KW, "min_break_excursion": 5.0})
    t.update(6249.0, ms=0)
    t.update(6256.0, ms=1000)  # max_ex 6.0 ≥ floor 5.0
    assert t.update(6248.5, ms=2000) is Verdict.REVERSAL


def test_hover_that_never_commits_does_not_time_confirm() -> None:
    # price sits just past the wall (3.0) for longer than confirm_s but under the floor —
    # a hover is not a break, so it must not confirm (→ no spurious go-with on chop)
    t = BreakoutTracker(price=6250.0, side="resistance", **{**_KW, "min_break_excursion": 5.0})
    t.update(6249.0, ms=0)
    t.update(6253.0, ms=1000)  # crossed; max_ex 3.0 < floor
    assert t.update(6253.0, ms=20_000) is None and t.phase is Phase.CROSSED  # held but uncommitted


# ── 6/22 QQQ breakdown replay (network-free regression of the calibration) ──

# The QQQ-era calibrated constants — the ratios these tunables came from. The live /MES
# defaults are the ~10× rescale of these, pending recalibration against recorded /MES tape;
# this replay stays pinned to the original QQQ scale so the historical trade still regresses.
_QQQ_CALIB = dict(
    break_margin=0.05,
    min_break_excursion=0.75,
    follow_through_margin=2.00,
    confirm_s=150.0,
    failure_window_s=120.0,
    reentry_margin=0.10,
    retest_proximity=0.20,
    retest_window_s=360.0,
)


def test_0622_breakdown_retest_resume_fires_go_with_with_calibrated_constants() -> None:
    """The 2026-06-22 trade-of-the-day, replayed at the QQQ-era calibrated constants.

    740 as a downside-break (support) wall: price breaks below at 10:30, holds, retests the
    wall from below at 10:35 (bounce to 739.9, never reclaimed), then resumes down — a GO_WITH.
    Prices/timestamps are the real 1-min path; the old 120 s retest_window would have missed it.
    """
    t = BreakoutTracker(price=740.0, side="support", **_QQQ_CALIB)
    base = 1_000_000  # arbitrary epoch-ms anchor
    path = [  # (seconds_from_anchor, price) — abridged real 6/22 10:27→10:38 path
        (0, 740.78),  # above the wall → witness inside (support inside = above)
        (60, 740.43),
        (180, 739.16),  # 10:30 break down through 740
        (240, 738.83),
        (300, 738.19),  # holding below; commits past min_break_excursion + follow_through
        (360, 738.35),
        (420, 739.89),  # 10:35 retest — bounce back up toward the wall (0.11 below), no reclaim
        (480, 739.62),  # rolls over
        (540, 739.00),  # resumes down past the wall → GO_WITH
    ]
    fires = [t.update(p, base + s * 1000) for s, p in path]
    assert Verdict.GO_WITH in fires
    assert all(v is None or v is Verdict.GO_WITH for v in fires)  # no spurious reversal en route
