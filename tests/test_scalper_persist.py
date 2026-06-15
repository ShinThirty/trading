"""PaperPersister — the reviewable artifact: a fills JSONL + a P&L summary JSON.

Pins that FILLED events append trade rows, the summary carries realized P&L +
open positions, and ``run`` flushes a final summary on shutdown (cancellation).
"""

import asyncio
import json
from pathlib import Path

import pytest
from trading_scalper.domain import FireRecord
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import (
    PaperPersister,
    SignalLog,
    default_fills_path,
    default_signals_path,
    default_summary_path,
)


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
    broker = PaperBroker()
    p = _persister(broker, tmp_path)
    broker.place_bracket("QQQ_C", 1, stop_pct=0.20, target_pct=0.20, reference=4.00)
    broker.trade("QQQ_C", 4.85)  # target fills -> a second FILLED event; the stop is cancelled

    rows = [json.loads(line) for line in p.fills_path.read_text().splitlines()]
    assert len(rows) == 2  # entry BUY + target SELL (a CANCELLED leg is not a fill)
    assert rows[0]["side"] == "BUY" and rows[0]["fill_price"] == 4.00
    assert rows[1]["side"] == "SELL" and rows[1]["fill_price"] == 4.80
    assert all(r["symbol"] == "QQQ_C" for r in rows)
    # both legs share the bracket key (the entry-order id), and the close carries the label
    assert rows[0]["bracket_id"] == rows[0]["order_id"]  # entry: order id doubles as the key
    assert rows[1]["bracket_id"] == rows[0]["order_id"]
    assert rows[0]["realized_delta"] == 0.0  # opening fill realizes nothing
    assert rows[1]["realized_delta"] == pytest.approx(80.0)  # +80 win label on the close


def test_summary_has_realized_and_positions(tmp_path: Path) -> None:
    broker = PaperBroker()
    p = _persister(broker, tmp_path)
    broker.place_bracket("QQQ_C", 1, stop_pct=0.20, target_pct=0.20, reference=4.00)
    broker.trade("QQQ_C", 4.85)  # +80 realized, position flat
    p.write_summary()

    summary = json.loads(p.summary_path.read_text())
    assert summary["date"] == "2026-06-12"
    assert summary["realized_pnl"] == pytest.approx(80.0)
    assert summary["n_fills"] == 2
    assert summary["positions"] == []  # flat after the round trip


def test_open_position_appears_in_summary(tmp_path: Path) -> None:
    broker = PaperBroker()
    p = _persister(broker, tmp_path)
    broker.place_bracket("QQQ_C", 2, stop_pct=0.20, target_pct=0.20, reference=4.00)  # left open
    p.write_summary()

    summary = json.loads(p.summary_path.read_text())
    assert summary["positions"] == [{"symbol": "QQQ_C", "qty": 2}]


def test_run_flushes_a_final_summary_on_cancel(tmp_path: Path) -> None:
    broker = PaperBroker()
    p = _persister(broker, tmp_path)
    broker.place_bracket("QQQ_C", 1, stop_pct=0.20, target_pct=0.20, reference=4.00)

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
        symbol="QQQ",
        level=719.40,
        side="support",
        mode="fade",
        confirming="buy",
        price=719.42,
        contract="QQQ260612C00720000",
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
