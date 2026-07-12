"""PaperPersister — the reviewable artifact: a fills JSONL + a P&L summary JSON.

Pins that FILLED events append trade rows, the summary carries realized P&L +
open positions, and ``run`` flushes a final summary on shutdown (cancellation).
"""

import asyncio
import json
from pathlib import Path

import pytest
from trading_scalper.domain import FireRecord, Side
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import (
    PaperPersister,
    SignalLog,
    default_fills_path,
    default_signals_path,
    default_summary_path,
    summarize_fills,
)
from trading_scalper.version import __version__


def _persister(broker: PaperBroker, tmp_path: Path) -> PaperPersister:
    return PaperPersister(
        broker,
        date="2026-06-12",
        fills_path=tmp_path / "fills.jsonl",
        summary_path=tmp_path / "summary.json",
        interval=0.01,
        clock=lambda: "2026-06-12T13:00:00+00:00",
    )


def test_fills_are_appended_as_jsonl(tmp_path: Path) -> None:
    broker = PaperBroker(multiplier=5)
    p = _persister(broker, tmp_path)
    broker.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )
    broker.trade("/MES", 6321.0)  # target fills -> a second FILLED event; the stop is cancelled

    rows = [json.loads(line) for line in p.fills_path.read_text().splitlines()]
    assert len(rows) == 2  # entry BUY + target SELL (a CANCELLED leg is not a fill)
    assert rows[0]["side"] == "BUY" and rows[0]["fill_price"] == 6300.0
    assert rows[1]["side"] == "SELL" and rows[1]["fill_price"] == 6320.0
    assert all(r["symbol"] == "/MES" for r in rows)
    # both legs share the bracket key (the entry-order id), and the close carries the label
    assert rows[0]["bracket_id"] == rows[0]["order_id"]  # entry: order id doubles as the key
    assert rows[1]["bracket_id"] == rows[0]["order_id"]
    assert rows[0]["realized_delta"] == 0.0  # opening fill realizes nothing
    assert rows[1]["realized_delta"] == pytest.approx(
        100.0
    )  # +100 win label on the close (20pt×$5)


def test_summary_has_realized_and_positions(tmp_path: Path) -> None:
    broker = PaperBroker(multiplier=5)
    p = _persister(broker, tmp_path)
    broker.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )
    broker.trade("/MES", 6321.0)  # +100 realized, position flat
    p.write_summary()

    summary = json.loads(p.summary_path.read_text())
    assert summary["date"] == "2026-06-12"
    assert summary["realized_pnl"] == pytest.approx(100.0)
    assert summary["n_fills"] == 2
    assert summary["positions"] == []  # flat after the round trip


def test_open_position_appears_in_summary(tmp_path: Path) -> None:
    broker = PaperBroker(multiplier=5)
    p = _persister(broker, tmp_path)
    broker.place_bracket(
        "/MES", Side.BUY, 2, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )  # left open
    p.write_summary()

    summary = json.loads(p.summary_path.read_text())
    assert summary["positions"] == [{"symbol": "/MES", "qty": 2}]


def test_summary_recomputes_across_a_daemon_restart(tmp_path: Path) -> None:
    """A regime remap restarts the daemon: a fresh broker appends to the same
    date-keyed fills log. The summary must reflect *both* processes' fills — the
    6/16 bug was the live summary dropping the morning's losing fade on restart."""
    fills, summary = tmp_path / "f.jsonl", tmp_path / "s.json"

    def persister(broker: PaperBroker) -> PaperPersister:
        return PaperPersister(
            broker,
            date="2026-06-16",
            fills_path=fills,
            summary_path=summary,
            clock=lambda: "2026-06-16T13:00:00+00:00",
        )

    # process 1 (morning fade): a losing round trip → −85
    broker1 = PaperBroker(multiplier=5)
    p1 = persister(broker1)
    broker1.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6283.0, target_price=6320.0, reference=6300.0
    )
    broker1.trade("/MES", 6283.0)  # stop fills → (6283−6300)×5 = −85 realized
    p1.write_summary()
    assert json.loads(summary.read_text())["realized_pnl"] == pytest.approx(-85.0)

    # process 2 (afternoon, post-remap): a *fresh* broker on the same log → +100
    broker2 = PaperBroker(multiplier=5)
    p2 = persister(broker2)
    broker2.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )
    broker2.trade("/MES", 6321.0)  # target (6320) fills → +100 realized
    p2.write_summary()

    # the live broker only knows its own +100; the recomputed summary knows both
    assert broker2.realized_pnl() == pytest.approx(100.0)
    s = json.loads(summary.read_text())
    assert s["realized_pnl"] == pytest.approx(15.0)  # −85 + 100, across both processes
    assert s["n_fills"] == 4  # two round trips, not just the live process's two
    assert s["positions"] == []  # both flat


def test_summarize_fills_handles_a_missing_log(tmp_path: Path) -> None:
    assert summarize_fills(tmp_path / "nope.jsonl") == {
        "realized_pnl": 0.0,
        "positions": [],
        "n_fills": 0,
    }


def test_summarize_fills_nets_open_positions_across_symbols(tmp_path: Path) -> None:
    broker = PaperBroker(multiplier=5)
    _persister(broker, tmp_path)  # subscribes the fills writer
    broker.place_bracket(
        "/MES", Side.BUY, 3, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )  # +3 open
    broker.place_bracket(
        "/ES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )
    broker.trade("/ES", 6321.0)  # /ES round-trips flat; /MES still long 3

    out = summarize_fills(tmp_path / "fills.jsonl")
    assert out["positions"] == [{"symbol": "/MES", "qty": 3}]
    assert out["n_fills"] == 3  # 2 opens + 1 close


def test_run_flushes_a_final_summary_on_cancel(tmp_path: Path) -> None:
    broker = PaperBroker(multiplier=5)
    p = _persister(broker, tmp_path)
    broker.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )

    async def drive() -> None:
        task = asyncio.create_task(p.run())
        await asyncio.sleep(0)  # let run() reach its first sleep
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())

    summary = json.loads(p.summary_path.read_text())  # written by the finally-clause
    assert summary["n_fills"] == 1  # only the entry filled; the bracket is still resting


def test_default_paths() -> None:
    assert default_fills_path("2026-06-12", root=Path("/tmp/x")) == Path("/tmp/x/2026-06-12.jsonl")
    assert default_summary_path("2026-06-12", root=Path("/tmp/x")) == Path(
        "/tmp/x/2026-06-12-summary.json"
    )
    assert default_signals_path("2026-06-12", root=Path("/tmp/x")) == Path(
        "/tmp/x/2026-06-12-signals.jsonl"
    )


def _fire_record(**overrides: object) -> FireRecord:
    base = dict(
        symbol="/MES",
        level=6190.40,
        side="support",
        mode="fade",
        confirming="buy",
        price=6190.42,
        contract="/MES",
        bracket_id="paper-1",
        velocity=-0.3612,
        cum_confirming_size=25,
        cum_contrary_size=4,
        book_imbalance=600,
    )
    return FireRecord(**(base | overrides))  # type: ignore[arg-type]


def test_signal_log_appends_a_row_per_fire(tmp_path: Path) -> None:
    log = SignalLog(tmp_path / "signals.jsonl", clock=lambda: "2026-06-12T13:00:00+00:00")
    log.record(_fire_record())
    log.record(_fire_record(confirming="sell", contract=None, velocity=None))

    rows = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert log.n_fires == 2 and len(rows) == 2
    assert rows[0]["ts"] == "2026-06-12T13:00:00+00:00"
    assert rows[0]["velocity"] == pytest.approx(-0.3612)
    assert rows[0]["cum_confirming_size"] == 25 and rows[0]["book_imbalance"] == 600
    assert rows[0]["bracket_id"] == "paper-1"  # join key to the bracket's fills
    assert rows[1]["velocity"] is None and rows[1]["contract"] is None  # alert-only, no time base
    assert rows[0]["version"] == __version__  # cohort key for the scorecard
