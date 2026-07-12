"""SetupDetector — confirmed fires (geometry + lean + tape) and the proposal path.

The detector only fires a setup that clears all three gates, so the tests feed a
*confirming* timesale (a print at the offer = buy tape for a long; at the bid = sell
tape for a short). These pin: fade touch-and-reject geometry, break
cross-and-follow-through geometry, the direction-based lean filter (so a breakout long
fires at a resistance level under long-only), once-per-tag hysteresis, the spread gate
on the proposal, and the soft book-imbalance annotation.

Prices are /MES (~6250) and margins are the ~10×-rescaled point geometry.
"""

import pytest
from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.detector import SetupDetector
from trading_scalper.domain import Side
from trading_scalper.notify import Notifier
from trading_scalper.plan import Level, SessionPlan

_S = 6190.0  # a support level
_R = 6230.0  # a resistance level


def _buy_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price - 0.25, ask=price)  # print at offer -> buy


def _sell_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price, ask=price + 0.25)  # print at bid -> sell


def _plan(lean: str = "long-only") -> SessionPlan:
    # alert-only levels (no direction): notify but place no paper trade
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(_S, "support", stop=6185.0), Level(_R, "resistance", stop=6235.0)],
        default_stop_points=5.0,
    )


def _detector(lean: str, notes: list[str]) -> SetupDetector:
    return SetupDetector(lambda: _plan(lean), notes.append, tolerance=1.0, rearm_margin=0.5)


# ── fade geometry + tape confirmation ───────────────────────


def test_support_fade_fires_on_confirming_tape() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_buy_ts("/MES", 6190.5))  # in band, buyers lifting
    assert len(notes) == 1
    assert "6190" in notes[0] and "support" in notes[0] and "lifting offers" in notes[0]


def test_support_fade_silent_on_contrary_tape() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_sell_ts("/MES", 6190.0))  # at support but selling
    assert notes == []


def test_mixed_tape_waits_then_fires_when_tape_turns() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_timesale(TimeSale("/MES", price=6190.3, bid=6189.5, ask=6191.0))  # mid -> mixed
    assert notes == []  # in the band but unconfirmed -> wait, don't arm
    det.on_timesale(_buy_ts("/MES", 6190.5))  # tape turns -> fire once
    assert len(notes) == 1


def test_resistance_suppressed_under_long_lean() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_sell_ts("/MES", 6230.0))  # short, long-only forbids
    assert notes == []


def test_both_lean_fires_either_side() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_timesale(_buy_ts("/MES", 6190.0))  # support long
    det.on_timesale(_sell_ts("/MES", 6230.0))  # resistance short
    assert len(notes) == 2


def test_no_trade_lean_is_silent() -> None:
    notes: list[str] = []
    _detector("no-trade", notes).on_timesale(_buy_ts("/MES", 6190.0))
    assert notes == []


def test_fade_fires_once_until_price_leaves_the_band() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_timesale(_buy_ts("/MES", 6190.5))  # tag + confirm -> fire
    det.on_timesale(_buy_ts("/MES", 6189.6))  # still in band -> no re-fire
    assert len(notes) == 1
    det.on_timesale(_buy_ts("/MES", 6192.0))  # left band (> tol + margin) -> re-arm
    det.on_timesale(_buy_ts("/MES", 6190.0))  # tag again -> fire
    assert len(notes) == 2


def test_other_symbol_is_ignored() -> None:
    notes: list[str] = []
    _detector("both", notes).on_timesale(_buy_ts("/ES", 6190.0))  # plan is for /MES
    assert notes == []


def test_trade_drives_proximity_using_last_tape() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_timesale(_buy_ts("/MES", 6192.5))  # buy tape, but out of band -> no fire
    assert notes == []
    det.on_trade(Trade("/MES", 6190.5))  # in band; reuses the last tape (buy) -> fire
    assert len(notes) == 1


def test_message_annotates_short_tape() -> None:
    notes: list[str] = []
    _detector("short-only", notes).on_timesale(_sell_ts("/MES", 6230.0))
    assert len(notes) == 1 and "hitting bids" in notes[0]


# ── break geometry ──────────────────────────────────────────


def _break_plan(lean: str = "both") -> SessionPlan:
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="breakout-trend",
        lean=lean,
        levels=[Level(_R, "resistance", mode="break", direction="long", stop=6224.0)],
        default_stop_points=6.0,
        default_target_points=8.0,
        contracts=1,
    )


def test_break_fires_only_after_cross_and_follow_through() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _break_plan(), notes.append, proposals.append, break_margin=0.5)
    det.on_timesale(_buy_ts("/MES", 6228.0))  # below the level -> arm (witnessed the setup side)
    det.on_timesale(_buy_ts("/MES", 6230.3))  # a poke, not past the margin -> no fire
    assert notes == []
    det.on_timesale(_buy_ts("/MES", 6231.0))  # crosses by margin with buyers -> fire
    assert len(notes) == 1 and len(proposals) == 1
    assert "broke" in notes[0] and "[break]" in notes[0]


def test_break_silent_without_follow_through_tape() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5)
    det.on_timesale(_sell_ts("/MES", 6228.0))  # below -> arm (arming is tape-agnostic)
    det.on_timesale(_sell_ts("/MES", 6232.0))  # crossed + armed, but sellers -> no follow-through
    assert notes == []


def test_break_long_fires_under_long_only_despite_resistance_side() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan("long-only"), notes.append, break_margin=0.5)
    det.on_timesale(_buy_ts("/MES", 6228.0))  # below the level -> arm
    det.on_timesale(_buy_ts("/MES", 6232.0))  # a breakout long — long-only permits it
    assert len(notes) == 1


# ── break arming: must witness the setup side (cold-start / wake guard) ──


def _put_break_plan() -> SessionPlan:
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="breakout-trend",
        lean="both",
        levels=[Level(_S, "support", mode="break", direction="short", stop=6196.0)],
        default_stop_points=6.0,
        default_target_points=8.0,
        contracts=1,
    )


def test_break_cold_start_above_level_does_not_fire() -> None:
    # daemon comes up with price already extended past the break level — never having
    # seen the setup side, it must not chase the top (the 2026-06-15 wake-into-top loss)
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5)
    det.on_timesale(_buy_ts("/MES", 6232.0))  # first-ever tick already broken out -> no fire
    assert notes == []


def test_break_fires_once_setup_side_is_witnessed() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5)
    det.on_timesale(_buy_ts("/MES", 6232.0))  # extended -> still unarmed, no fire
    det.on_timesale(_buy_ts("/MES", 6228.0))  # price returns below -> arm
    assert notes == []
    det.on_timesale(_buy_ts("/MES", 6231.0))  # fresh cross with follow-through -> fire
    assert len(notes) == 1


def test_break_support_breakdown_arms_from_above() -> None:
    # symmetry: a support-breakdown short (confirming = sell) arms from *above* support
    notes: list[str] = []
    det = SetupDetector(lambda: _put_break_plan(), notes.append, break_margin=0.5)
    det.on_timesale(_sell_ts("/MES", 6188.0))  # already below, never seen above -> no fire
    assert notes == []
    det.on_timesale(_sell_ts("/MES", 6192.0))  # above support -> arm
    det.on_timesale(_sell_ts("/MES", 6189.0))  # breakdown with sellers -> fire
    assert len(notes) == 1


# ── stream-gap re-arm (the wake-from-sleep guard) ──


def _bts(symbol: str, price: float, ms: int) -> TimeSale:
    """A timestamped buy timesale (print at the offer)."""
    return TimeSale(symbol, price=price, bid=price - 0.25, ask=price, ms=ms)


def _sts(symbol: str, price: float, ms: int) -> TimeSale:
    """A timestamped sell timesale (print at the bid)."""
    return TimeSale(symbol, price=price, bid=price, ask=price + 0.25, ms=ms)


def test_stream_gap_unarms_break_so_wake_into_extended_does_not_fire() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5, gap_s=90.0)
    det.on_timesale(_bts("/MES", 6228.0, ms=1_000_000))  # below -> arm (pre-sleep)
    det.on_timesale(_bts("/MES", 6265.0, ms=1_120_000))  # 120s gap, woke extended -> no break fire
    assert not any("broke" in n for n in notes)  # the wake-into-top fire is suppressed
    assert any("stream gap" in n for n in notes)  # and the re-arm is announced


def test_small_gap_keeps_arming_and_break_still_fires() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5, gap_s=90.0)
    det.on_timesale(_bts("/MES", 6228.0, ms=1_000_000))  # below -> arm
    det.on_timesale(_bts("/MES", 6231.0, ms=1_005_000))  # 5s later, no gap, still armed -> fire
    assert any("broke" in n for n in notes)
    assert not any("stream gap" in n for n in notes)


def test_gap_with_nothing_armed_is_silent() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.5, gap_s=90.0)
    det.on_timesale(_bts("/MES", 6265.0, ms=1_000_000))  # extended, never armed
    det.on_timesale(_bts("/MES", 6266.0, ms=1_120_000))  # 120s gap, but nothing to drop -> silent
    assert notes == []


def test_stream_gap_unarms_breakdown_so_wake_into_extended_does_not_fire() -> None:
    # the downside mirror: a support-breakdown short armed from above must also re-witness
    # its setup side after a sleep, not fire on waking far below the level
    notes: list[str] = []
    det = SetupDetector(lambda: _put_break_plan(), notes.append, break_margin=0.5, gap_s=90.0)
    det.on_timesale(_sts("/MES", 6192.0, ms=1_000_000))  # above support -> arm (pre-sleep)
    det.on_timesale(_sts("/MES", 6150.0, ms=1_120_000))  # 120s gap, woke far below -> no fire
    assert not any("broke" in n for n in notes)
    assert any("stream gap" in n for n in notes)


# ── TradeProposal emission + spread gate ────────────────────


def _plan_tradeable(lean: str = "long-only") -> SessionPlan:
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(_S, "support", direction="long", stop=6185.0, target=6202.0)],
        default_stop_points=6.0,
        default_target_points=8.0,
        contracts=2,
    )


def test_tradeable_level_emits_a_proposal() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _plan_tradeable(), notes.append, proposals.append)
    det.on_timesale(_buy_ts("/MES", 6190.5))

    assert len(notes) == 1  # still prompts the human
    assert len(proposals) == 1
    p = proposals[0]
    assert p.symbol == "/MES"
    assert p.direction is Side.BUY
    assert p.quantity == 2
    assert p.stop_price == 6185.0 and p.target_price == 6202.0  # explicit level prices
    assert p.reason == notes[0]  # the proposal carries the alert text


def test_derived_bracket_prices_from_default_points() -> None:
    # a tradeable level with no explicit stop/target derives them from the plan's default points
    plan = SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean="long-only",
        levels=[Level(_S, "support", direction="long")],
        default_stop_points=6.0,
        default_target_points=8.0,
    )
    proposals: list = []
    SetupDetector(lambda: plan, lambda _m: None, proposals.append).on_timesale(
        _buy_ts("/MES", 6190.5)
    )
    p = proposals[0]
    assert p.stop_price == _S - 6.0  # 6184.0, long stop below
    assert p.target_price == _S + 8.0  # 6198.0, long target above


def test_alert_only_level_only_notifies() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _plan(), notes.append, proposals.append
    )  # levels carry no direction
    det.on_timesale(_buy_ts("/MES", 6190.5))

    assert len(notes) == 1
    assert proposals == []  # alert-only, no paper trade


def test_proposal_fires_once_per_tag() -> None:
    proposals: list = []
    det = SetupDetector(lambda: _plan_tradeable("both"), lambda _m: None, proposals.append)
    det.on_timesale(_buy_ts("/MES", 6190.5))  # tag -> propose
    det.on_timesale(_buy_ts("/MES", 6189.6))  # still in band -> no re-propose
    assert len(proposals) == 1


def test_inverted_bracket_alerts_but_skips_proposal() -> None:
    # an explicit stop on the WRONG side of a long level must not rest a nonsensical OCO
    plan = SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean="long-only",
        levels=[Level(_S, "support", direction="long", stop=6195.0, target=6202.0)],  # stop ABOVE
    )
    notes: list[str] = []
    proposals: list = []
    SetupDetector(lambda: plan, notes.append, proposals.append).on_timesale(_buy_ts("/MES", 6190.5))
    assert proposals == []
    assert "bracket geometry inverted" in notes[0]


def test_wide_spread_alerts_but_skips_proposal() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _plan_tradeable(), notes.append, proposals.append, spread_max_pct=0.001
    )
    det.on_quote(Quote("/MES", bid=6180.0, ask=6200.0))  # ~0.32% spread — too wide to model a fill
    det.on_timesale(_buy_ts("/MES", 6190.5))

    assert len(notes) == 1 and "spread too wide" in notes[0]
    assert proposals == []  # confirmed setup, but not paper-filled


def test_tight_spread_proposes() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _plan_tradeable(), notes.append, proposals.append, spread_max_pct=0.001
    )
    det.on_quote(Quote("/MES", bid=6190.25, ask=6190.50))  # one-tick spread — tradeable
    det.on_timesale(_buy_ts("/MES", 6190.5))

    assert len(proposals) == 1 and "spread too wide" not in notes[0]


def test_book_imbalance_annotated() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_quote(Quote("/MES", bid=6189.5, ask=6191.0, bid_size=500, ask_size=100))
    det.on_timesale(_buy_ts("/MES", 6190.5))
    assert len(notes) == 1 and "book bid-heavy 500x100" in notes[0]


# ── zero-gamma tripwire ─────────────────────────────────────


def _flip_plan(flip: float | None = 6195.0) -> SessionPlan:
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean="no-trade",  # tripwire must fire even when no trading is allowed
        zero_gamma=flip,
        levels=[],
    )


def _flip_detector(notes: list[str], flip: float | None = 6195.0) -> SetupDetector:
    return SetupDetector(lambda: _flip_plan(flip), notes.append, flip_margin=1.0)


def test_flip_first_tick_only_records_side() -> None:
    notes: list[str] = []
    _flip_detector(notes).on_trade(Trade("/MES", 6198.0))  # above flip, but first obs
    assert notes == []  # learns the side, does not alert


def test_flip_fires_on_down_cross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("/MES", 6198.0))  # start above
    det.on_trade(Trade("/MES", 6193.0))  # cross below by > margin -> fire
    assert len(notes) == 1
    assert "zero-gamma flip 6195" in notes[0] and "below" in notes[0]
    assert "re-run /scalp prep" in notes[0] and "stop fading" in notes[0]


def test_flip_fires_on_up_cross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("/MES", 6192.0))  # start below
    det.on_trade(Trade("/MES", 6196.5))  # cross above by > margin -> fire
    assert len(notes) == 1 and "above" in notes[0] and "reasserting" in notes[0]


def test_flip_debounces_within_margin_band() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("/MES", 6198.0))  # above
    det.on_trade(Trade("/MES", 6194.5))  # only 0.5 below flip (< margin) -> no fire
    det.on_trade(Trade("/MES", 6195.5))  # back up within band -> no fire
    assert notes == []


def test_flip_refires_on_recross() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("/MES", 6198.0))  # above
    det.on_trade(Trade("/MES", 6193.5))  # down-cross -> fire
    det.on_trade(Trade("/MES", 6196.5))  # up-cross -> fire again (each genuine cross flags)
    assert len(notes) == 2 and "below" in notes[0] and "above" in notes[1]


def test_flip_silent_when_plan_has_no_flip() -> None:
    notes: list[str] = []
    det = _flip_detector(notes, flip=None)
    det.on_trade(Trade("/MES", 6198.0))
    det.on_trade(Trade("/MES", 6100.0))  # huge move, but no flip to cross
    assert notes == []


def test_flip_ignores_non_underlying_symbol() -> None:
    notes: list[str] = []
    det = _flip_detector(notes)
    det.on_trade(Trade("/ES", 6198.0))  # plan is /MES -> filtered before the tripwire
    det.on_trade(Trade("/ES", 6193.0))
    assert notes == []


# ── B4 velocity/absorption telemetry (recorded, never gated) ─


def _ts(symbol: str, price: float, *, size: int, side: str, ms: int) -> TimeSale:
    """A timestamped, sized timesale whose aggressor side is forced via the quote."""
    if side == "buy":
        return TimeSale(symbol, price=price, size=size, bid=price - 0.25, ask=price, ms=ms)
    return TimeSale(symbol, price=price, size=size, bid=price, ask=price + 0.25, ms=ms)


def _recording_detector(records: list, lean: str = "long-only") -> SetupDetector:
    return SetupDetector(lambda: _plan(lean), lambda _m: None, record=records.append, tolerance=1.0)


def test_fire_records_velocity_and_confirming_size() -> None:
    records: list = []
    det = _recording_detector(records)
    # two buy prints, 0.5s apart, falling 6191.5 -> 6190.4 into support; second is in-band
    det.on_timesale(_ts("/MES", 6191.5, size=10, side="buy", ms=1000))  # out of band, recorded
    det.on_timesale(_ts("/MES", 6190.4, size=15, side="buy", ms=1500))  # in band -> fire
    assert len(records) == 1
    r = records[0]
    assert r.confirming == "buy"
    assert r.cum_confirming_size == 25  # 10 + 15 within the window
    assert r.cum_contrary_size == 0
    assert r.velocity == pytest.approx((6190.4 - 6191.5) / 0.5)  # -2.2 $/s, falling in


def test_fire_records_contrary_size_separately() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_timesale(_ts("/MES", 6191.5, size=30, side="sell", ms=1000))  # contrary, out of band
    det.on_timesale(
        _ts("/MES", 6190.4, size=12, side="buy", ms=1300)
    )  # confirming, in band -> fire
    r = records[0]
    assert r.cum_confirming_size == 12 and r.cum_contrary_size == 30


def test_fire_records_book_imbalance() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_quote(Quote("/MES", bid=6189.5, ask=6191.0, bid_size=800, ask_size=200))
    det.on_timesale(_buy_ts("/MES", 6190.5))
    assert records[0].book_imbalance == 600  # 800 - 200


def test_fire_records_alert_only_level() -> None:
    records: list = []
    det = _recording_detector(records)  # _plan levels carry no direction
    det.on_timesale(_buy_ts("/MES", 6190.5))
    assert len(records) == 1 and records[0].contract is None


def test_velocity_is_none_without_timestamps() -> None:
    records: list = []
    det = _recording_detector(records)
    det.on_timesale(_buy_ts("/MES", 6190.5))  # _buy_ts carries no ms
    assert records[0].velocity is None


def test_record_sink_is_optional() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_timesale(_buy_ts("/MES", 6190.5))  # no record sink
    assert len(notes) == 1  # still fires + notifies, no crash without a recorder


# ── breakout-attempt verdicts: reversal + retest (geometry, not tape) ──

_W = 6250.0  # a verdict wall

# small, fast-resolving verdict tunables so the geometry (not the calibrated defaults) is tested
_VKW = dict(
    break_margin=1.0,
    min_break_excursion=1.0,
    follow_through_margin=10.0,
    confirm_s=10.0,
    failure_window_s=60.0,
    reentry_margin=1.0,
    retest_proximity=2.0,
    retest_window_s=60.0,
)


def _verdict_plan(lean: str = "both", *, reversal: bool = True, retest: bool = True) -> SessionPlan:
    levels = []
    if reversal:  # failed-break of resistance → snap back down → short
        levels.append(Level(_W, "resistance", mode="reversal", direction="short", stop=6255.0))
    if retest:  # confirmed break of resistance → continuation up → long
        levels.append(Level(_W, "resistance", mode="retest", direction="long", stop=6244.0))
    return SessionPlan(
        date="2026-06-22",
        symbol="/MES",
        regime="breakout-trend",
        lean=lean,
        levels=levels,
        default_stop_points=6.0,
        default_target_points=8.0,
        contracts=1,
    )


def _verdict_detector(notes: list, proposals: list, lean: str = "both") -> SetupDetector:
    return SetupDetector(lambda: _verdict_plan(lean), notes.append, proposals.append, **_VKW)


def test_reversal_verdict_fires_short_on_snapback_despite_buy_tape() -> None:
    # the whole point: a failed-break reversal is geometry, NOT tape — it fires the short
    # even though the prints are at the offer (buy tape, contrary to the short's direction)
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("/MES", 6247.0, ms=0))  # inside the wall → arm
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))  # crossed above by > break_margin
    det.on_timesale(_bts("/MES", 6248.5, ms=2000))  # snapped back inside in-window → REVERSAL
    assert len(proposals) == 1 and proposals[0].direction is Side.SELL
    assert any("failed-break reversal" in n and "[reversal]" in n for n in notes)


def test_retest_verdict_fires_long_on_confirmed_break_and_resume() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("/MES", 6247.0, ms=0))  # arm
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))  # cross
    det.on_timesale(_bts("/MES", 6252.5, ms=12_000))  # held ≥ confirm_s → CONFIRMED
    det.on_timesale(_bts("/MES", 6251.0, ms=13_000))  # pulled back to the wall (retest)
    det.on_timesale(_bts("/MES", 6252.0, ms=14_000))  # resumed outward → GO_WITH
    assert any(p.direction is Side.BUY for p in proposals)
    assert any("breakout retest" in n and "[retest]" in n for n in notes)


def test_reversal_short_suppressed_under_long_only_lean() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals, lean="long-only")
    det.on_timesale(_bts("/MES", 6247.0, ms=0))
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))
    det.on_timesale(_bts("/MES", 6248.5, ms=2000))  # REVERSAL verdict, but short → blocked
    assert proposals == [] and not any("reversal" in n for n in notes)


def test_go_with_silent_when_no_retest_row_on_the_wall() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _verdict_plan(retest=False), notes.append, proposals.append, **_VKW)
    det.on_timesale(_bts("/MES", 6247.0, ms=0))
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))
    det.on_timesale(_bts("/MES", 6252.5, ms=12_000))  # CONFIRMED
    det.on_timesale(_bts("/MES", 6251.0, ms=13_000))  # retest
    det.on_timesale(_bts("/MES", 6252.0, ms=14_000))  # GO_WITH verdict, but no retest row → nothing
    assert proposals == []


def test_stream_gap_resets_breakout_tracker_mid_attempt() -> None:
    notes: list[str] = []
    proposals: list = []
    det = _verdict_detector(notes, proposals)
    det.on_timesale(_bts("/MES", 6247.0, ms=1_000_000))  # arm
    det.on_timesale(_bts("/MES", 6252.0, ms=1_001_000))  # cross → CROSSED (mid-attempt)
    det.on_timesale(_bts("/MES", 6248.5, ms=1_200_000))  # 199s gap → tracker dropped before update
    assert proposals == []  # the snap-back across the dead time does NOT fire a reversal
    assert any("stream gap" in n for n in notes)


def test_reversal_fire_records_telemetry_with_mode() -> None:
    records: list = []
    det = SetupDetector(lambda: _verdict_plan(), lambda _m: None, record=records.append, **_VKW)
    det.on_timesale(_bts("/MES", 6247.0, ms=0))
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))
    det.on_timesale(_bts("/MES", 6248.5, ms=2000))
    assert len(records) == 1
    assert records[0].mode == "reversal" and records[0].contract == "/MES"
    assert records[0].confirming == "sell"  # short → sell-confirming, recorded for the join


# ── per-level re-fire cooldown (caps the machine-gun during a regime mismatch) ──


def test_cooldown_blocks_rapid_refire_of_same_level() -> None:
    # an oscillating wall re-arms on every re-entry; the cooldown stops the re-fire until
    # cooldown_s has passed (the 2026-06-18 fade machine-gun, capped)
    notes: list[str] = []
    det = SetupDetector(
        lambda: _plan("both"), notes.append, cooldown_s=10.0, tolerance=1.0, rearm_margin=0.5
    )
    det.on_timesale(_bts("/MES", 6190.5, ms=0))  # tag + confirm -> fire (cooldown stamped at 0)
    assert len(notes) == 1
    det.on_timesale(_bts("/MES", 6192.0, ms=2000))  # leave the band -> re-arm
    det.on_timesale(_bts("/MES", 6190.0, ms=4000))  # re-enter 4s later -> still cooling, suppressed
    assert len(notes) == 1
    det.on_timesale(_bts("/MES", 6192.0, ms=6000))  # leave again
    det.on_timesale(
        _bts("/MES", 6190.0, ms=12_000)
    )  # re-enter 12s after fire -> cooled off -> fires
    assert len(notes) == 2


def test_cooldown_is_per_level_not_global() -> None:
    # one level cooling must not silence a different level — the cap is per setup, not global
    notes: list[str] = []
    det = SetupDetector(
        lambda: _plan("both"), notes.append, cooldown_s=300.0, tolerance=1.0, rearm_margin=0.5
    )
    det.on_timesale(_bts("/MES", 6190.5, ms=0))  # support fade fires
    det.on_timesale(_sts("/MES", 6230.0, ms=1000))  # resistance fade — different level -> fires
    assert len(notes) == 2


def test_cooldown_is_noop_without_timestamps() -> None:
    # a ms-less feed has no time base, so the cooldown degrades to a no-op (re-fires on re-entry)
    notes: list[str] = []
    det = SetupDetector(
        lambda: _plan("both"), notes.append, cooldown_s=300.0, tolerance=1.0, rearm_margin=0.5
    )
    det.on_timesale(_buy_ts("/MES", 6190.5))  # ms-less fire
    det.on_timesale(_buy_ts("/MES", 6192.0))  # leave the band -> re-arm
    det.on_timesale(_buy_ts("/MES", 6190.0))  # re-enter immediately -> no time base -> re-fires
    assert len(notes) == 2


def test_cooldown_caps_oscillating_wall_reversal() -> None:
    # the cooldown composes with the verdict path: a wall that pokes-and-snaps repeatedly fires
    # the reversal once, then the cooldown suppresses the next snap-back within the window
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(
        lambda: _verdict_plan("both"), notes.append, proposals.append, cooldown_s=60.0, **_VKW
    )
    det.on_timesale(_bts("/MES", 6247.0, ms=0))  # inside -> arm
    det.on_timesale(_bts("/MES", 6252.0, ms=1000))  # cross out
    det.on_timesale(_bts("/MES", 6248.5, ms=2000))  # snap back -> REVERSAL fires (cooldown at 2000)
    det.on_timesale(_bts("/MES", 6247.0, ms=3000))  # well inside -> tracker re-arms
    det.on_timesale(_bts("/MES", 6252.0, ms=4000))  # cross out again
    det.on_timesale(_bts("/MES", 6248.5, ms=5000))  # snap back 3s later -> verdict, but cooling
    assert len([p for p in proposals if p.direction is Side.SELL]) == 1


def test_stream_gap_clears_refire_cooldown() -> None:
    # a gap forces fresh re-witnessing, so a post-gap fire is a NEW setup and must not inherit
    # the pre-gap cooldown — even though only 200s (< the 300s cooldown) elapsed
    notes: list[str] = []
    det = SetupDetector(
        lambda: _plan("both"),
        notes.append,
        cooldown_s=300.0,
        gap_s=90.0,
        tolerance=1.0,
        rearm_margin=0.5,
    )
    det.on_timesale(_bts("/MES", 6190.5, ms=1_000_000))  # support fade fires (cooldown stamped)
    det.on_timesale(_bts("/MES", 6190.5, ms=1_200_000))  # 200s gap -> cooldown dropped -> re-fires
    assert len([n for n in notes if "support" in n]) == 2
    assert any("stream gap" in n for n in notes)


# ── Notifier ────────────────────────────────────────────────


def test_notifier_formats_and_rings() -> None:
    lines: list[str] = []
    Notifier(bell=True, write=lines.append, clock=lambda: "09:31:00").notify("/MES tagged 6190")
    assert lines == ["\a[09:31:00] /MES tagged 6190"]


def test_notifier_without_bell() -> None:
    lines: list[str] = []
    Notifier(bell=False, write=lines.append, clock=lambda: "09:31:00").notify("hi")
    assert lines == ["[09:31:00] hi"]
