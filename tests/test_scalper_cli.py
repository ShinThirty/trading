"""Composition root — the subsystems wired into one paper session.

These pin the new wiring contract: the tape drives both the matching engine and
the detector (so the traded futures symbol is always priced before a fire); quotes
feed the detector's spread/book gates; a *confirmed* level tag with a direction
auto-places a direction-aware OCO bracket; an OCO leg fill flattens + realizes; and
the subscribe list includes the plan's symbol.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.cli import (
    _parse_demo_setup,
    _plan_key,
    build_session,
    collect_symbols,
    make_executor,
)
from trading_scalper.domain import Side, TradeProposal
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import PaperPersister
from trading_scalper.plan import Level, SessionPlan


def _buy_ts(symbol: str, price: float) -> TimeSale:
    return TimeSale(symbol, price=price, bid=price - 0.25, ask=price)  # print at offer -> buy


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


def _plan(lean: str = "both", direction: str | None = "long") -> SessionPlan:
    return SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="fragile-pin",
        lean=lean,
        levels=[Level(6190.0, "support", direction=direction, stop=6185.0, target=6200.0)],
        default_stop_points=6.0,
        default_target_points=8.0,
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
        date="2026-07-12",
        underlyings=["/MES"],
        fills_path=tmp_path / "fills.jsonl",
        summary_path=tmp_path / "summary.json",
        signals_path=tmp_path / "signals.jsonl",
        tape_path=tmp_path / "tape.jsonl",
        shadow_path=tmp_path / "shadow.jsonl",
    )


def test_build_session_wires_tape_and_quote_consumers(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    session = _session(feed, broker, tmp_path)

    # both drive_paper_fills + watch_setups register on every channel: trade and
    # timesale advance the engine + feed the detector; quote sets the broker's
    # book (entry fills at the ask) + the detector's spread/book read. The shadow
    # recorder adds a third timesale subscriber (volume telemetry, reads nothing back).
    assert len(feed._trade) == 2
    assert len(feed._timesale) == 3
    assert len(feed._quote) == 2
    assert isinstance(session.persister, PaperPersister)
    assert session.basis is None  # no reference symbol → no carry-basis shadow


def test_reference_symbol_wires_the_basis_shadow(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    session = build_session(
        feed,
        broker,
        lambda: _plan(),
        notifier=Notifier(bell=False, write=lambda _l: None),
        date="2026-07-12",
        underlyings=["/MESU26:XCME"],
        fills_path=tmp_path / "fills.jsonl",
        summary_path=tmp_path / "summary.json",
        signals_path=tmp_path / "signals.jsonl",
        tape_path=tmp_path / "tape.jsonl",
        shadow_path=tmp_path / "shadow.jsonl",
        reference_symbol="SPX",
        basis_path=tmp_path / "basis.jsonl",
    )
    # the basis recorder adds one quote + one trade subscriber on top of the base wiring
    assert session.basis is not None
    assert len(feed._quote) == 3
    assert len(feed._trade) == 3


def test_confirmed_tag_auto_places_a_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "long"))

    # the tape print both seeds the broker's last price AND fires the detector (drive_paper_fills
    # is wired before the detector), so the entry is always priced — no separate seed needed
    feed.emit_timesale(_buy_ts("/MES", 6190.0))  # confirmed support tag -> auto-bracket

    assert broker.net_position("/MES") == 1  # entry filled, OCO children resting


def test_confirmed_tag_logs_a_signal_row(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "long"))

    feed.emit_timesale(_buy_ts("/MES", 6190.0))  # confirmed support tag -> fire + telemetry

    assert session.signals.n_fires == 1
    rows = [json.loads(line) for line in session.signals.path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "/MES" and rows[0]["contract"] == "/MES"  # traded instrument
    assert rows[0]["confirming"] == "buy" and rows[0]["mode"] == "fade"


def test_signal_row_joins_to_bracket_fills_on_bracket_id(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "long"))

    feed.emit_timesale(
        _buy_ts("/MES", 6190.0)
    )  # confirmed tag -> bracket (entry 6190) + signal row
    feed.emit_trade(Trade("/MES", 6184.0))  # crosses the stop (6185) -> close, loss realized

    signal = json.loads(session.signals.path.read_text().splitlines()[0])
    fills = [json.loads(line) for line in session.persister.fills_path.read_text().splitlines()]
    entry = next(f for f in fills if f["side"] == "BUY")
    close = next(f for f in fills if f["side"] == "SELL")

    # the fire's bracket_id ties it to the entry fill, and every leg shares the key...
    assert signal["bracket_id"] == entry["order_id"] == entry["bracket_id"]
    assert close["bracket_id"] == signal["bracket_id"]
    # ...so the fire's features join to the realized win/loss label recorded on the close
    assert entry["realized_delta"] == 0.0
    assert close["realized_delta"] == pytest.approx((6184.0 - 6190.0) * 5)  # -30 loss label


def test_alert_only_fire_records_null_bracket_id(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    session = _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", direction=None))

    feed.emit_timesale(_buy_ts("/MES", 6190.0))  # confirmed tag, but no direction -> no fill

    signal = json.loads(session.signals.path.read_text().splitlines()[0])
    assert (
        signal["bracket_id"] is None
    )  # nothing placed -> no join key, distinguishes no-fill fires


def test_bracket_stop_fill_flattens_and_realizes(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", "long"))

    feed.emit_timesale(_buy_ts("/MES", 6190.0))  # bracket: entry 6190, stop 6185, target 6200
    feed.emit_trade(Trade("/MES", 6184.0))  # crosses the stop -> flat

    assert broker.net_position("/MES") == 0
    assert broker.realized_pnl() == pytest.approx((6184.0 - 6190.0) * 5)  # -30


def test_break_mode_tag_with_clean_quote_places_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    plan = SessionPlan(
        date="2026-07-12",
        symbol="/MES",
        regime="breakout-trend",
        lean="both",
        levels=[
            Level(6230.0, "resistance", mode="break", direction="long", stop=6224.0, target=6238.0)
        ],
        default_stop_points=6.0,
        default_target_points=8.0,
        contracts=1,
    )
    _session(feed, broker, tmp_path, plan_source=lambda: plan)

    feed.emit_quote(Quote("/MES", bid=6229.75, ask=6230.0))  # clean, one-tick book
    feed.emit_timesale(_buy_ts("/MES", 6228.0))  # below the level -> arm the break (no fire yet)
    feed.emit_timesale(_buy_ts("/MES", 6231.0))  # cross the level with follow-through buy tape

    assert broker.net_position("/MES") == 1


def test_executor_soft_warns_when_broker_has_no_price(tmp_path: Path) -> None:
    # the defensive branch: a proposal on a symbol the broker has never seen a price for
    # cannot fill, so it soft-warns and returns None rather than raising
    del tmp_path
    broker, notes = PaperBroker(multiplier=5), []
    execute = make_executor(broker, Notifier(bell=False, write=notes.append))

    result = execute(TradeProposal("/MES", Side.BUY, 1, stop_price=6185.0, target_price=6200.0))

    assert result is None
    assert broker.net_position("/MES") == 0
    assert any("no price" in n for n in notes)


def test_alert_only_level_places_no_bracket(tmp_path: Path) -> None:
    feed, broker = FakeFeed(), PaperBroker(multiplier=5)
    _session(feed, broker, tmp_path, plan_source=lambda: _plan("both", direction=None))

    feed.emit_timesale(_buy_ts("/MES", 6190.0))  # confirmed tag, but the level names no direction

    assert broker.positions() == []  # nothing traded


def test_collect_symbols_includes_plan_symbol() -> None:
    assert collect_symbols(_plan("both"), ["/MES"]) == ["/MES"]  # plan symbol already present
    assert collect_symbols(None, ["/MES", "/ES"]) == ["/MES", "/ES"]
    # if --symbols omits the plan symbol, it's appended so the daemon still subscribes it
    assert collect_symbols(_plan("both"), ["/ES"]) == ["/ES", "/MES"]


def test_plan_key_sanitizes_streamer_symbol() -> None:
    assert _plan_key("/MESU25:XCME") == "MESU25"
    assert _plan_key("/MES") == "MES"


def test_parse_demo_setup_defaults_and_full() -> None:
    assert _parse_demo_setup("/MES") == ("/MES", 1, 6300.00)
    assert _parse_demo_setup("/MES:3:6305.0") == ("/MES", 3, 6305.0)
