"""Composition root — the subsystems wired into one paper session.

These pin the new wiring contract: the tape drives both the matching engine and
the detector; a level tag that names a contract auto-places an OCO bracket in the
paper broker; an OCO leg fill flattens + realizes; a tag with no option price yet
soft-warns instead of trading; and the subscribe list folds in the plan's option
contracts.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from trading_clients.market_stream import TimeSale, Trade
from trading_scalper.cli import _parse_demo_setup, build_session, collect_symbols
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import PaperPersister
from trading_scalper.plan import Level, SessionPlan


class FakeFeed:
    """Records callbacks and lets a test push synthetic prints through them."""

    def __init__(self) -> None:
        self.subscribed: list[str] | None = None
        self._quote: list[Callable] = []
        self._trade: list[Callable] = []
        self._timesale: list[Callable] = []

    async def subscribe(self, symbols: list[str]) -> None:
        self.subscribed = list(symbols)

    def on_quote(self, cb: Callable) -> None:
        self._quote.append(cb)

    def on_trade(self, cb: Callable) -> None:
        self._trade.append(cb)

    def on_timesale(self, cb: Callable) -> None:
        self._timesale.append(cb)

    def emit_trade(self, trade: Trade) -> None:
        for cb in self._trade:
            cb(trade)

    def emit_timesale(self, ts: TimeSale) -> None:
        for cb in self._timesale:
            cb(ts)


def _plan(lean: str = "both", contract: str | None = "QQQ_C") -> SessionPlan:
    return SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(719.40, "support", 718.90, contract=contract)],
        default_stop_pct=0.20,
        target_pct=0.20,
        contracts=1,
    )


def _session(
    feed: FakeFeed,
    broker: PaperBroker,
    tmp_path: Path,
    *,
    plan_source: Callable[[], SessionPlan | None] | None = None,
    notes: list[str] | None = None,
):
    write = notes.append if notes is not None else (lambda _line: None)
    notifier = Notifier(bell=False, write=write)
    return build_session(
        feed,
        broker,
        plan_source or (lambda: _plan()),
        notifier=notifier,
        date="2026-06-12",
        fills_path=tmp_path / "fills.jsonl",
        summary_path=tmp_path / "summary.json",
    )


def test_build_session_wires_two_tape_consumers_each(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    session = _session(feed, broker, tmp_path)

    # drive_paper_fills + watch_setups each register on trade + timesale
    assert len(feed._trade) == 2
    assert len(feed._timesale) == 2
    assert isinstance(session.persister, PaperPersister)


def test_level_tag_auto_places_a_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # seed the option price
    feed.emit_trade(Trade("QQQ", 719.41))  # tag the support level -> auto-bracket

    assert broker.net_position("QQQ_C") == 1  # entry filled, OCO children resting


def test_bracket_stop_fill_flattens_and_realizes(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # entry ref
    feed.emit_trade(Trade("QQQ", 719.41))  # bracket: stop 3.20, target 4.80
    feed.emit_trade(Trade("QQQ_C", 3.10))  # crosses the stop -> flat

    assert broker.net_position("QQQ_C") == 0
    assert broker.realized_pnl() == pytest.approx((3.10 - 4.00) * 100)  # -90


def test_tag_with_no_option_price_soft_warns(tmp_path: Path) -> None:
    feed, broker, notes = FakeFeed(), PaperBroker(), []
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"), notes=notes)

    feed.emit_trade(Trade("QQQ", 719.41))  # tag, but the option never printed

    assert broker.net_position("QQQ_C") == 0
    assert any("no price" in n for n in notes)


def test_alert_only_level_places_no_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", contract=None))

    feed.emit_trade(Trade("QQQ", 719.41))  # tags, but the level names no contract

    assert broker.positions() == []  # nothing traded


def test_collect_symbols_folds_in_contracts() -> None:
    assert collect_symbols(_plan("both", "QQQ_C"), ["QQQ"]) == ["QQQ", "QQQ_C"]
    assert collect_symbols(None, ["QQQ", "SPY"]) == ["QQQ", "SPY"]
    assert collect_symbols(_plan("both", contract=None), ["QQQ"]) == ["QQQ"]


def test_parse_demo_setup_defaults_and_full() -> None:
    assert _parse_demo_setup("QQQ_C") == ("QQQ_C", 1, 2.00)
    assert _parse_demo_setup("QQQ_C:3:4.5") == ("QQQ_C", 3, 4.5)
