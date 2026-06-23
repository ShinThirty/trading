"""SetupDetector — confirmed fires (geometry + lean + tape) and the proposal path.

The detector only fires a setup that clears all three gates, so the tests feed a
*confirming* timesale (a print at the offer = buy tape for a call/long; at the bid
= sell tape for a put/short). These pin: fade touch-and-reject geometry, break
cross-and-follow-through geometry, the direction-based lean filter (so a breakout
long fires at a resistance level under long-only), once-per-tag hysteresis, the
spread gate on the proposal, and the soft book-imbalance annotation.
"""

import pytest
from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.detector import SetupDetector
from trading_scalper.notify import Notifier
from trading_scalper.plan import Level, SessionPlan

_CALL = "QQQ260612C00720000"
_BREAK_CALL = "QQQ260612C00723000"
_BREAK_PUT = "QQQ260612P00719000"


def _buy_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price - 0.02, ask=price)  # print at offer -> buy


def _sell_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price, ask=price + 0.02)  # print at bid -> sell


def _plan(lean: str = "long-only") -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(719.40, "support", 718.90), Level(723.10, "resistance", 723.70)],
        default_stop_pct=0.15,
    )


def _detector(lean: str, notes: list[str]) -> SetupDetector:
    return SetupDetector(lambda: _plan(lean), notes.append, tolerance=0.10, rearm_margin=0.05)


# ── fade geometry + tape confirmation ───────────────────────


def test_support_fade_fires_on_confirming_tape() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_buy_ts("QQQ", 719.42))  # in band, buyers lifting
    assert len(notes) == 1
    assert "719.4" in notes[0] and "support" in notes[0] and "lifting offers" in notes[0]


def test_support_fade_silent_on_contrary_tape() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_sell_ts("QQQ", 719.40))  # at support but selling
    assert notes == []


def test_mixed_tape_waits_then_fires_when_tape_turns() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_timesale(TimeSale("QQQ", price=719.41, bid=719.39, ask=719.45))  # mid -> mixed
    assert notes == []  # in the band but unconfirmed -> wait, don't arm
    det.on_timesale(_buy_ts("QQQ", 719.42))  # tape turns -> fire once
    assert len(notes) == 1


def test_resistance_suppressed_under_long_lean() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_sell_ts("QQQ", 723.10))  # short, long-only forbids
    assert notes == []


def test_both_lean_fires_either_side() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_timesale(_buy_ts("QQQ", 719.40))  # support long
    det.on_timesale(_sell_ts("QQQ", 723.10))  # resistance short
    assert len(notes) == 2


def test_no_trade_lean_is_silent() -> None:
    notes: list[str] = []
    _detector("no-trade", notes).on_timesale(_buy_ts("QQQ", 719.40))
    assert notes == []


def test_fade_fires_once_until_price_leaves_the_band() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_timesale(_buy_ts("QQQ", 719.41))  # tag + confirm -> fire
    det.on_timesale(_buy_ts("QQQ", 719.39))  # still in band -> no re-fire
    assert len(notes) == 1
    det.on_timesale(_buy_ts("QQQ", 720.10))  # left band (> tol + margin) -> re-arm
    det.on_timesale(_buy_ts("QQQ", 719.40))  # tag again -> fire
    assert len(notes) == 2


def test_other_symbol_is_ignored() -> None:
    notes: list[str] = []
    _detector("both", notes).on_timesale(_buy_ts("SPY", 719.40))  # plan is for QQQ
    assert notes == []


def test_trade_drives_proximity_using_last_tape() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_timesale(_buy_ts("QQQ", 719.60))  # buy tape, but out of band -> no fire
    assert notes == []
    det.on_trade(Trade("QQQ", 719.42))  # in band; reuses the last tape (buy) -> fire
    assert len(notes) == 1


def test_message_annotates_short_tape() -> None:
    notes: list[str] = []
    _detector("short-only", notes).on_timesale(_sell_ts("QQQ", 723.10))
    assert len(notes) == 1 and "hitting bids" in notes[0]


# ── break geometry ──────────────────────────────────────────


def _break_plan(lean: str = "both") -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="breakout-trend",
        lean=lean,
        levels=[Level(723.10, "resistance", 723.70, contract=_BREAK_CALL, mode="break")],
        default_stop_pct=0.20,
        target_pct=0.20,
        contracts=1,
    )


def test_break_fires_only_after_cross_and_follow_through() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _break_plan(), notes.append, proposals.append, break_margin=0.05)
    det.on_timesale(_buy_ts("QQQ", 723.00))  # below the level -> arm (witnessed the setup side)
    det.on_timesale(_buy_ts("QQQ", 723.11))  # a poke, not past the margin -> no fire
    assert notes == []
    det.on_timesale(_buy_ts("QQQ", 723.20))  # crosses by margin with buyers -> fire
    assert len(notes) == 1 and len(proposals) == 1
    assert "broke" in notes[0] and "[break]" in notes[0]


def test_break_silent_without_follow_through_tape() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05)
    det.on_timesale(_sell_ts("QQQ", 723.00))  # below -> arm (arming is tape-agnostic)
    det.on_timesale(_sell_ts("QQQ", 723.30))  # crossed + armed, but sellers -> no follow-through
    assert notes == []


def test_break_call_fires_under_long_only_despite_resistance_side() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan("long-only"), notes.append, break_margin=0.05)
    det.on_timesale(_buy_ts("QQQ", 723.00))  # below the level -> arm
    det.on_timesale(_buy_ts("QQQ", 723.30))  # a breakout CALL is a long — long-only permits it
    assert len(notes) == 1


# ── break arming: must witness the setup side (cold-start / wake guard) ──


def _put_break_plan() -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="breakout-trend",
        lean="both",
        levels=[Level(719.40, "support", 719.90, contract=_BREAK_PUT, mode="break")],
        default_stop_pct=0.20,
        target_pct=0.20,
        contracts=1,
    )


def test_break_cold_start_above_level_does_not_fire() -> None:
    # daemon comes up with price already extended past the break level — never having
    # seen the setup side, it must not chase the top (the 2026-06-15 wake-into-top loss)
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05)
    det.on_timesale(_buy_ts("QQQ", 723.30))  # first-ever tick already broken out -> no fire
    assert notes == []


def test_break_fires_once_setup_side_is_witnessed() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05)
    det.on_timesale(_buy_ts("QQQ", 723.30))  # extended -> still unarmed, no fire
    det.on_timesale(_buy_ts("QQQ", 723.00))  # price returns below -> arm
    assert notes == []
    det.on_timesale(_buy_ts("QQQ", 723.20))  # fresh cross with follow-through -> fire
    assert len(notes) == 1


def test_break_support_breakdown_arms_from_above() -> None:
    # symmetry: a support-breakdown PUT (confirming = sell) arms from *above* support
    notes: list[str] = []
    det = SetupDetector(lambda: _put_break_plan(), notes.append, break_margin=0.05)
    det.on_timesale(_sell_ts("QQQ", 719.30))  # already below, never seen above -> no fire
    assert notes == []
    det.on_timesale(_sell_ts("QQQ", 719.60))  # above support -> arm
    det.on_timesale(_sell_ts("QQQ", 719.30))  # breakdown with sellers -> fire
    assert len(notes) == 1


# ── stream-gap re-arm (the wake-from-sleep guard) ──


def _bts(symbol: str, price: float, ms: int) -> TimeSale:
    """A timestamped buy timesale (print at the offer)."""
    return TimeSale(symbol, price=price, bid=price - 0.02, ask=price, ms=ms)


def _sts(symbol: str, price: float, ms: int) -> TimeSale:
    """A timestamped sell timesale (print at the bid)."""
    return TimeSale(symbol, price=price, bid=price, ask=price + 0.02, ms=ms)


def test_stream_gap_unarms_break_so_wake_into_extended_does_not_fire() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05, gap_s=90.0)
    det.on_timesale(_bts("QQQ", 723.00, ms=1_000_000))  # below -> arm (pre-sleep)
    det.on_timesale(_bts("QQQ", 744.50, ms=1_120_000))  # 120s gap, woke extended -> no break fire
    assert not any("broke" in n for n in notes)  # the wake-into-top fire is suppressed
    assert any("stream gap" in n for n in notes)  # and the re-arm is announced


def test_small_gap_keeps_arming_and_break_still_fires() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05, gap_s=90.0)
    det.on_timesale(_bts("QQQ", 723.00, ms=1_000_000))  # below -> arm
    det.on_timesale(_bts("QQQ", 723.20, ms=1_005_000))  # 5s later, no gap, still armed -> fire
    assert any("broke" in n for n in notes)
    assert not any("stream gap" in n for n in notes)


def test_gap_with_nothing_armed_is_silent() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05, gap_s=90.0)
    det.on_timesale(_bts("QQQ", 744.50, ms=1_000_000))  # extended, never armed
    det.on_timesale(_bts("QQQ", 744.60, ms=1_120_000))  # 120s gap, but nothing to drop -> silent
    assert notes == []


def test_stream_gap_unarms_breakdown_so_wake_into_extended_does_not_fire() -> None:
    # the downside mirror: a support-breakdown PUT armed from above must also re-witness
    # its setup side after a sleep, not fire on waking far below the level
    notes: list[str] = []
    det = SetupDetector(lambda: _put_break_plan(), notes.append, break_margin=0.05, gap_s=90.0)
    det.on_timesale(_sts("QQQ", 719.60, ms=1_000_000))  # above support -> arm (pre-sleep)
    det.on_timesale(_sts("QQQ", 700.00, ms=1_120_000))  # 120s gap, woke far below -> no fire
    assert not any("broke" in n for n in notes)
    assert any("stream gap" in n for n in notes)


# ── TradeProposal emission + spread gate ────────────────────


def _plan_with_contract(lean: str = "long-only") -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(719.40, "support", 718.90, contract=_CALL)],
        default_stop_pct=0.20,
        target_pct=0.25,
        contracts=2,
    )


def test_contract_level_emits_a_proposal() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _plan_with_contract(), notes.append, proposals.append)
    det.on_timesale(_buy_ts("QQQ", 719.41))

    assert len(notes) == 1  # still prompts the human
    assert len(proposals) == 1
    p = proposals[0]
    assert p.contract == _CALL
    assert p.quantity == 2
    assert p.stop_pct == 0.20 and p.target_pct == 0.25
    assert p.reason == notes[0]  # the proposal carries the alert text


def test_no_contract_level_only_notifies() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _plan(), notes.append, proposals.append)  # levels carry no contract
    det.on_timesale(_buy_ts("QQQ", 719.41))

    assert len(notes) == 1
    assert proposals == []  # alert-only, no paper trade


def test_proposal_fires_once_per_tag() -> None:
    proposals: list = []
    det = SetupDetector(lambda: _plan_with_contract("both"), lambda _m: None, proposals.append)
    det.on_timesale(_buy_ts("QQQ", 719.41))  # tag -> propose
    det.on_timesale(_buy_ts("QQQ", 719.39))  # still in band -> no re-propose
    assert len(proposals) == 1


def test_wide_option_spread_alerts_but_skips_proposal() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _plan_with_contract(), notes.append, proposals.append, spread_max_pct=0.10
    )
    det.on_quote(Quote(_CALL, bid=1.00, ask=2.00))  # 50% spread — too wide to model a fill
    det.on_timesale(_buy_ts("QQQ", 719.41))

    assert len(notes) == 1 and "spread too wide" in notes[0]
    assert proposals == []  # confirmed setup, but not paper-filled


def test_tight_option_spread_proposes() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _plan_with_contract(), notes.append, proposals.append, spread_max_pct=0.10
    )
    det.on_quote(Quote(_CALL, bid=1.98, ask=2.00))  # 1% spread — tradeable
    det.on_timesale(_buy_ts("QQQ", 719.41))

    assert len(proposals) == 1 and "spread too wide" not in notes[0]


def test_underlying_book_imbalance_annotated() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_quote(Quote("QQQ", bid=719.39, ask=719.43, bid_size=500, ask_size=100))
    det.on_timesale(_buy_ts("QQQ", 719.41))
    assert len(notes) == 1 and "book bid-heavy 500x100" in notes[0]


# ── zero-gamma tripwire ─────────────────────────────────────


def _flip_plan(flip: float | None = 719.95) -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="fragile-pin",
        lean="no-trade",  # tripwire must fire even when no trading is allowed
        zero_gamma=flip,
        levels=[],
    )


def _flip_detector(notes: list[str], flip: float | None = 719.95) -> SetupDetector:
    return SetupDetector(lambda: _flip_plan(flip), notes.append, flip_margin=0.10)


def test_flip_first_tick_only_records_side() -> None:
    notes: list[str] = []
    _flip_detector(notes).on_trade(Trade("QQQ", 721.00))  # above flip, but first obs
    assert notes == []  # learns the side, does not alert


def test_flip_fires_on_down_cross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("QQQ", 721.00))  # start above
    det.on_trade(Trade("QQQ", 719.80))  # cross below by > margin -> fire
    assert len(notes) == 1
    assert "zero-gamma flip 719.95" in notes[0] and "below" in notes[0]
    assert "re-run /scalp prep" in notes[0] and "stop fading" in notes[0]


def test_flip_fires_on_up_cross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("QQQ", 719.00))  # start below
    det.on_trade(Trade("QQQ", 720.10))  # cross above by > margin -> fire
    assert len(notes) == 1 and "above" in notes[0] and "reasserting" in notes[0]


def test_flip_debounces_within_margin_band() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("QQQ", 721.00))  # above
    det.on_trade(Trade("QQQ", 719.90))  # only 0.05 below flip (< margin) -> no fire
    det.on_trade(Trade("QQQ", 720.00))  # back up within band -> no fire
    assert notes == []


def test_flip_refires_on_recross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("QQQ", 721.00))  # above
    det.on_trade(Trade("QQQ", 719.70))  # down-cross -> fire
    det.on_trade(Trade("QQQ", 720.20))  # up-cross -> fire again (each genuine cross flags)
    assert len(notes) == 2 and "below" in notes[0] and "above" in notes[1]


def test_flip_silent_when_plan_has_no_flip() -> None:
    notes: list[str] = []
    det = _flip_detector(notes, flip=None)
    det.on_trade(Trade("QQQ", 721.00))
    det.on_trade(Trade("QQQ", 700.00))  # huge move, but no flip to cross
    assert notes == []


def test_flip_ignores_non_underlying_symbol() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("SPY", 721.00))  # plan is QQQ -> filtered before the tripwire
    det.on_trade(Trade("SPY", 719.00))
    assert notes == []


# ── B4 velocity/absorption telemetry (recorded, never gated) ─


def _ts(symbol: str, price: float, *, size: int, side: str, ms: int) -> TimeSale:
    """A timestamped, sized timesale whose aggressor side is forced via the quote."""
    if side == "buy":
        return TimeSale(symbol, price=price, size=size, bid=price - 0.02, ask=price, ms=ms)
    return TimeSale(symbol, price=price, size=size, bid=price, ask=price + 0.02, ms=ms)


def _recording_detector(records: list, lean: str = "long-only") -> SetupDetector:
    return SetupDetector(
        lambda: _plan(lean), lambda _m: None, record=records.append, tolerance=0.10
    )


def test_fire_records_velocity_and_confirming_size() -> None:
    records: list = []
    det = _recording_detector(records)
    # two buy prints, 0.5s apart, falling 719.60 -> 719.42 into support; second is in-band
    det.on_timesale(_ts("QQQ", 719.60, size=10, side="buy", ms=1000))  # out of band, recorded
    det.on_timesale(_ts("QQQ", 719.42, size=15, side="buy", ms=1500))  # in band -> fire
    assert len(records) == 1
    r = records[0]
    assert r.confirming == "buy"
    assert r.cum_confirming_size == 25  # 10 + 15 within the window
    assert r.cum_contrary_size == 0
    assert r.velocity == pytest.approx((719.42 - 719.60) / 0.5)  # -0.36 $/s, falling in


def test_fire_records_contrary_size_separately() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_timesale(_ts("QQQ", 719.80, size=30, side="sell", ms=1000))  # contrary, out of band
    det.on_timesale(_ts("QQQ", 719.42, size=12, side="buy", ms=1300))  # confirming, in band -> fire
    r = records[0]
    assert r.cum_confirming_size == 12 and r.cum_contrary_size == 30


def test_fire_records_book_imbalance() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_quote(Quote("QQQ", bid=719.39, ask=719.43, bid_size=800, ask_size=200))
    det.on_timesale(_buy_ts("QQQ", 719.41))
    assert records[0].book_imbalance == 600  # 800 - 200


def test_fire_records_alert_only_level() -> None:
    records: list = []
    det = _recording_detector(records)  # _plan levels carry no contract
    det.on_timesale(_buy_ts("QQQ", 719.41))
    assert len(records) == 1 and records[0].contract is None


def test_velocity_is_none_without_timestamps() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_timesale(_buy_ts("QQQ", 719.41))  # _buy_ts carries no ms
    assert records[0].velocity is None


def test_record_sink_is_optional() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_buy_ts("QQQ", 719.41))  # no record sink
    assert len(notes) == 1  # still fires + notifies, no crash without a recorder


# ── breakout-attempt verdicts: reversal + retest (geometry, not tape) ──

_REV_PUT = "QQQ260612P00740000"  # failed-break of resistance → snap back down → short PUT
_GO_CALL = "QQQ260612C00740000"  # confirmed break of resistance → continuation up → long CALL

# small, fast-resolving verdict tunables so the geometry (not the calibrated defaults) is tested
_VKW = dict(
    break_margin=0.10,
    min_break_excursion=0.10,
    follow_through_margin=1.00,
    confirm_s=10.0,
    failure_window_s=60.0,
    reentry_margin=0.10,
    retest_proximity=0.20,
    retest_window_s=60.0,
)


def _verdict_plan(lean: str = "both", *, reversal: bool = True, retest: bool = True) -> SessionPlan:
    levels = []
    if reversal:
        levels.append(Level(740.0, "resistance", 740.5, contract=_REV_PUT, mode="reversal"))
    if retest:
        levels.append(Level(740.0, "resistance", 739.5, contract=_GO_CALL, mode="retest"))
    return SessionPlan(
        date="2026-06-22",
        symbol="QQQ",
        regime="breakout-trend",
        lean=lean,
        levels=levels,
        default_stop_pct=0.20,
        target_pct=0.20,
        contracts=1,
    )


def _verdict_detector(notes: list, proposals: list, lean: str = "both") -> SetupDetector:
    return SetupDetector(lambda: _verdict_plan(lean), notes.append, proposals.append, **_VKW)


def test_reversal_verdict_fires_put_on_snapback_despite_buy_tape() -> None:
    # the whole point: a failed-break reversal is geometry, NOT tape — it fires the short PUT
    # even though the prints are at the offer (buy tape, contrary to the PUT's direction)
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("QQQ", 739.0, ms=0))  # inside the wall → arm
    det.on_timesale(_bts("QQQ", 740.20, ms=1000))  # crossed above by > break_margin
    det.on_timesale(_bts("QQQ", 739.85, ms=2000))  # snapped back inside in-window → REVERSAL
    assert len(proposals) == 1 and proposals[0].contract == _REV_PUT
    assert any("failed-break reversal" in n and "[reversal]" in n for n in notes)


def test_retest_verdict_fires_call_on_confirmed_break_and_resume() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("QQQ", 739.0, ms=0))  # arm
    det.on_timesale(_bts("QQQ", 740.20, ms=1000))  # cross
    det.on_timesale(_bts("QQQ", 740.40, ms=12_000))  # held ≥ confirm_s → CONFIRMED
    det.on_timesale(_bts("QQQ", 740.10, ms=13_000))  # pulled back to the wall (retest)
    det.on_timesale(_bts("QQQ", 740.25, ms=14_000))  # resumed outward → GO_WITH
    assert any(p.contract == _GO_CALL for p in proposals)
    assert any("breakout retest" in n and "[retest]" in n for n in notes)


def test_reversal_short_suppressed_under_long_only_lean() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals, lean="long-only")
    det.on_timesale(_bts("QQQ", 739.0, ms=0))
    det.on_timesale(_bts("QQQ", 740.20, ms=1000))
    det.on_timesale(_bts("QQQ", 739.85, ms=2000))  # REVERSAL verdict, but PUT is short → blocked
    assert proposals == [] and not any("reversal" in n for n in notes)


def test_go_with_silent_when_no_retest_row_on_the_wall() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _verdict_plan(retest=False), notes.append, proposals.append, **_VKW)
    det.on_timesale(_bts("QQQ", 739.0, ms=0))
    det.on_timesale(_bts("QQQ", 740.20, ms=1000))
    det.on_timesale(_bts("QQQ", 740.40, ms=12_000))  # CONFIRMED
    det.on_timesale(_bts("QQQ", 740.10, ms=13_000))  # retest
    det.on_timesale(_bts("QQQ", 740.25, ms=14_000))  # GO_WITH verdict, but no retest row → nothing
    assert proposals == []


def test_stream_gap_resets_breakout_tracker_mid_attempt() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("QQQ", 739.0, ms=1_000_000))  # arm
    det.on_timesale(_bts("QQQ", 740.20, ms=1_001_000))  # cross → CROSSED (mid-attempt)
    det.on_timesale(_bts("QQQ", 739.85, ms=1_200_000))  # 199s gap → tracker dropped before update
    assert proposals == []  # the snap-back across the dead time does NOT fire a reversal
    assert any("stream gap" in n for n in notes)


def test_reversal_fire_records_telemetry_with_mode() -> None:
    records: list = []
    det = SetupDetector(lambda: _verdict_plan(), lambda _m: None, record=records.append, **_VKW)
    det.on_timesale(_bts("QQQ", 739.0, ms=0))
    det.on_timesale(_bts("QQQ", 740.20, ms=1000))
    det.on_timesale(_bts("QQQ", 739.85, ms=2000))
    assert len(records) == 1
    assert records[0].mode == "reversal" and records[0].contract == _REV_PUT
    assert records[0].confirming == "sell"  # PUT → sell-confirming, recorded for the join


# ── Notifier ────────────────────────────────────────────────


def test_notifier_formats_and_rings() -> None:
    lines: list[str] = []
    Notifier(bell=True, write=lines.append, clock=lambda: "09:31:00").notify("QQQ tagged 719.4")
    assert lines == ["\a[09:31:00] QQQ tagged 719.4"]


def test_notifier_without_bell() -> None:
    lines: list[str] = []
    Notifier(bell=False, write=lines.append, clock=lambda: "09:31:00").notify("hi")
    assert lines == ["[09:31:00] hi"]
