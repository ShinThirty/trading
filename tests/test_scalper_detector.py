"""SetupDetector — confirmed fires (geometry + lean + tape) and the proposal path.

The detector only fires a setup that clears all three gates, so the tests feed a
*confirming* timesale (a print at the offer = buy tape for a call/long; at the bid
= sell tape for a put/short). These pin: fade touch-and-reject geometry, break
cross-and-follow-through geometry, the direction-based lean filter (so a breakout
long fires at a resistance level under long-only), once-per-tag hysteresis, the
spread gate on the proposal, and the soft book-imbalance annotation.
"""

from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.detector import SetupDetector
from trading_scalper.notify import Notifier
from trading_scalper.plan import Level, SessionPlan

_CALL = "QQQ260612C00720000"
_BREAK_CALL = "QQQ260612C00723000"


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
    det.on_timesale(_buy_ts("QQQ", 723.11))  # a poke, not past the margin -> no fire
    assert notes == []
    det.on_timesale(_buy_ts("QQQ", 723.20))  # crosses by margin with buyers -> fire
    assert len(notes) == 1 and len(proposals) == 1
    assert "broke" in notes[0] and "[break]" in notes[0]


def test_break_silent_without_follow_through_tape() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan(), notes.append, break_margin=0.05)
    det.on_timesale(_sell_ts("QQQ", 723.30))  # crossed, but sellers -> no follow-through
    assert notes == []


def test_break_call_fires_under_long_only_despite_resistance_side() -> None:
    notes: list[str] = []
    det = SetupDetector(lambda: _break_plan("long-only"), notes.append, break_margin=0.05)
    det.on_timesale(_buy_ts("QQQ", 723.30))  # a breakout CALL is a long — long-only permits it
    assert len(notes) == 1


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


# ── Notifier ────────────────────────────────────────────────


def test_notifier_formats_and_rings() -> None:
    lines: list[str] = []
    Notifier(bell=True, write=lines.append, clock=lambda: "09:31:00").notify("QQQ tagged 719.4")
    assert lines == ["\a[09:31:00] QQQ tagged 719.4"]


def test_notifier_without_bell() -> None:
    lines: list[str] = []
    Notifier(bell=False, write=lines.append, clock=lambda: "09:31:00").notify("hi")
    assert lines == ["[09:31:00] hi"]
