"""SetupDetector — fires on a level tag, filtered by lean, with tape context.

It prompts the human and (when the level names a contract) emits a TradeProposal.
These pin the lean filter, the once-per-tag hysteresis (no spam while price
hovers), the no-trade silence, the tape annotation, and the proposal path.
"""

from trading_clients.market_stream import TimeSale, Trade
from trading_scalper.detector import SetupDetector
from trading_scalper.notify import Notifier
from trading_scalper.plan import Level, SessionPlan


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


def test_support_tag_fires_under_long_lean() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_trade(Trade("QQQ", 719.42))  # within 0.10 of 719.40
    assert len(notes) == 1
    assert "719.4" in notes[0] and "support" in notes[0]


def test_resistance_tag_suppressed_under_long_lean() -> None:
    notes: list[str] = []
    _detector("long-only", notes).on_trade(Trade("QQQ", 723.08))  # near resistance
    assert notes == []


def test_both_lean_fires_either_side() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_trade(Trade("QQQ", 719.40))
    det.on_trade(Trade("QQQ", 723.10))
    assert len(notes) == 2


def test_no_trade_lean_is_silent() -> None:
    notes: list[str] = []
    _detector("no-trade", notes).on_trade(Trade("QQQ", 719.40))
    assert notes == []


def test_fires_once_until_price_leaves_the_band() -> None:
    notes: list[str] = []
    det = _detector("both", notes)
    det.on_trade(Trade("QQQ", 719.41))  # tag -> fire
    det.on_trade(Trade("QQQ", 719.39))  # still in band -> no re-fire
    assert len(notes) == 1
    det.on_trade(Trade("QQQ", 720.10))  # left band (> tol + margin) -> re-arm
    det.on_trade(Trade("QQQ", 719.40))  # tag again -> fire
    assert len(notes) == 2


def test_other_symbol_is_ignored() -> None:
    notes: list[str] = []
    _detector("both", notes).on_trade(Trade("SPY", 719.40))  # plan is for QQQ
    assert notes == []


def test_timesale_at_offer_annotates_lifting() -> None:
    notes: list[str] = []
    det = _detector("long-only", notes)
    det.on_timesale(TimeSale("QQQ", price=719.42, bid=719.40, ask=719.42))  # print at ask
    assert len(notes) == 1
    assert "lifting offers" in notes[0]


def test_timesale_at_bid_annotates_hitting() -> None:
    notes: list[str] = []
    det = _detector("short-only", notes)
    det.on_timesale(TimeSale("QQQ", price=723.10, bid=723.10, ask=723.12))  # print at bid
    assert len(notes) == 1
    assert "hitting bids" in notes[0]


# ── TradeProposal emission ──────────────────────────────────


def _plan_with_contract(lean: str = "long-only") -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(719.40, "support", 718.90, contract="QQQ260612C00720000")],
        default_stop_pct=0.20,
        target_pct=0.25,
        contracts=2,
    )


def test_contract_level_emits_a_proposal() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _plan_with_contract(), notes.append, proposals.append)
    det.on_trade(Trade("QQQ", 719.41))

    assert len(notes) == 1  # still prompts the human
    assert len(proposals) == 1
    p = proposals[0]
    assert p.contract == "QQQ260612C00720000"
    assert p.quantity == 2
    assert p.stop_pct == 0.20 and p.target_pct == 0.25
    assert p.reason == notes[0]  # the proposal carries the alert text


def test_no_contract_level_only_notifies() -> None:
    notes: list[str] = []
    proposals: list = []
    det = SetupDetector(lambda: _plan(), notes.append, proposals.append)  # levels carry no contract
    det.on_trade(Trade("QQQ", 719.41))

    assert len(notes) == 1
    assert proposals == []  # alert-only, no paper trade


def test_proposal_fires_once_per_tag() -> None:
    proposals: list = []
    det = SetupDetector(lambda: _plan_with_contract("both"), lambda _m: None, proposals.append)
    det.on_trade(Trade("QQQ", 719.41))  # tag -> propose
    det.on_trade(Trade("QQQ", 719.39))  # still in band -> no re-propose
    assert len(proposals) == 1


# ── Notifier ────────────────────────────────────────────────


def test_notifier_formats_and_rings() -> None:
    lines: list[str] = []
    Notifier(bell=True, write=lines.append, clock=lambda: "09:31:00").notify("QQQ tagged 719.4")
    assert lines == ["\a[09:31:00] QQQ tagged 719.4"]


def test_notifier_without_bell() -> None:
    lines: list[str] = []
    Notifier(bell=False, write=lines.append, clock=lambda: "09:31:00").notify("hi")
    assert lines == ["[09:31:00] hi"]
