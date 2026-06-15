"""Composition root — the subsystems wired into one paper session.

These pin the new wiring contract: the tape drives both the matching engine and
the detector; quotes feed the detector's spread/book gates; a *confirmed* level
tag that names a contract auto-places an OCO bracket; an OCO leg fill flattens +
realizes; a confirmed tag with no option price yet soft-warns instead of trading;
and the subscribe list folds in the plan's option contracts.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.cli import _parse_demo_setup, build_session, collect_symbols
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import PaperPersister
from trading_scalper.plan import Level, SessionPlan


def _buy_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price - 0.02, ask=price)  # print at offer -> buy


class FakeFeed:
    """Records callbacks and lets a test push synthetic events through them."""

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

    def emit_quote(self, quote: Quote) -> None:
        for cb in self._quote:
            cb(quote)

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
        signals_path=tmp_path / "signals.jsonl",
    )


def test_build_session_wires_tape_and_quote_consumers(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    session = _session(feed, broker, tmp_path)

    # both drive_paper_fills + watch_setups register on every channel: trade and
    # timesale advance the engine + feed the detector; quote sets the broker's
    # book (entry fills at the ask) + the detector's spread/book read.
    assert len(feed._trade) == 2
    assert len(feed._timesale) == 2
    assert len(feed._quote) == 2
    assert isinstance(session.persister, PaperPersister)


def test_confirmed_tag_auto_places_a_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # seed the option price
    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed support tag -> auto-bracket

    assert broker.net_position("QQQ_C") == 1  # entry filled, OCO children resting


def test_confirmed_tag_logs_a_signal_row(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # seed the option price
    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed support tag -> fire + telemetry

    assert session.signals.n_fires == 1
    rows = [json.loads(line) for line in session.signals.path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "QQQ" and rows[0]["contract"] == "QQQ_C"
    assert rows[0]["confirming"] == "buy" and rows[0]["mode"] == "fade"


def test_signal_row_joins_to_bracket_fills_on_bracket_id(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # seed the option price
    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed tag -> bracket + signal row
    feed.emit_trade(Trade("QQQ_C", 3.10))  # crosses the stop -> close, loss realized

    signal = json.loads(session.signals.path.read_text().splitlines()[0])
    fills = [json.loads(line) for line in session.persister.fills_path.read_text().splitlines()]
    entry = next(f for f in fills if f["side"] == "BUY")
    close = next(f for f in fills if f["side"] == "SELL")

    # the fire's bracket_id ties it to the entry fill, and every leg shares the key...
    assert signal["bracket_id"] == entry["order_id"] == entry["bracket_id"]
    assert close["bracket_id"] == signal["bracket_id"]
    # ...so the fire's features join to the realized win/loss label recorded on the close
    assert entry["realized_delta"] == 0.0
    assert close["realized_delta"] == pytest.approx((3.10 - 4.00) * 100)  # -90 loss label


def test_alert_only_fire_records_null_bracket_id(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", contract=None))

    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed tag, but no contract -> no fill

    signal = json.loads(session.signals.path.read_text().splitlines()[0])
    assert (
        signal["bracket_id"] is None
    )  # nothing placed -> no join key, distinguishes no-fill fires


def test_bracket_stop_fill_flattens_and_realizes(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"))

    feed.emit_trade(Trade("QQQ_C", 4.00))  # entry ref
    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # bracket: stop 3.20, target 4.80
    feed.emit_trade(Trade("QQQ_C", 3.10))  # crosses the stop -> flat

    assert broker.net_position("QQQ_C") == 0
    assert broker.realized_pnl() == pytest.approx((3.10 - 4.00) * 100)  # -90


def test_break_mode_tag_with_clean_quote_places_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    plan = SessionPlan(
        date="2026-06-12",
        symbol="QQQ",
        regime="breakout-trend",
        lean="both",
        levels=[Level(723.10, "resistance", 723.70, contract="QQQ260612C00723000", mode="break")],
        default_stop_pct=0.20,
        target_pct=0.20,
        contracts=1,
    )
    _session(feed, broker, tmp_path, plan_source=lambda: plan)

    feed.emit_trade(Trade("QQQ260612C00723000", 2.00))  # seed option price
    feed.emit_quote(Quote("QQQ260612C00723000", bid=1.98, ask=2.00))  # clean, penny-wide
    feed.emit_timesale(_buy_ts("QQQ", 723.30))  # cross the level with follow-through buy tape

    assert broker.net_position("QQQ260612C00723000") == 1


def test_tag_with_no_option_price_soft_warns(tmp_path: Path) -> None:
    feed, broker, notes = FakeFeed(), PaperBroker(), []
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "QQQ_C"), notes=notes)

    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed tag, but the option never printed

    assert broker.net_position("QQQ_C") == 0
    assert any("no price" in n for n in notes)


def test_alert_only_level_places_no_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker()
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", contract=None))

    feed.emit_timesale(_buy_ts("QQQ", 719.41))  # confirmed tag, but the level names no contract

    assert broker.positions() == []  # nothing traded


def test_collect_symbols_folds_in_contracts() -> None:
    assert collect_symbols(_plan("both", "QQQ_C"), ["QQQ"]) == ["QQQ", "QQQ_C"]
    assert collect_symbols(None, ["QQQ", "SPY"]) == ["QQQ", "SPY"]
    assert collect_symbols(_plan("both", contract=None), ["QQQ"]) == ["QQQ"]


def test_parse_demo_setup_defaults_and_full() -> None:
    assert _parse_demo_setup("QQQ_C") == ("QQQ_C", 1, 2.00)
    assert _parse_demo_setup("QQQ_C:3:4.5") == ("QQQ_C", 3, 4.5)
