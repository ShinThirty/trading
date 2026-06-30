"""ShadowRecorder — raw-tape capture + periodic VolumeProfile/VolumeRate snapshots.

Pins that it tracks underlyings only (option prints are ignored), buffers the raw
tape and flushes it on the timer, snapshots one row per traded underlying, and
flushes a final tape + snapshot on shutdown. Writes only — gates nothing.
"""

import asyncio
import json
from pathlib import Path

import pytest
from trading_clients.market_stream import TimeSale
from trading_scalper.shadow import (
    ShadowRecorder,
    default_shadow_path,
    default_tape_path,
)

_CLOCK = "2026-06-29T13:00:00+00:00"


def _recorder(tmp_path: Path, symbols: list[str] | None = None) -> ShadowRecorder:
    return ShadowRecorder(
        symbols or ["QQQ"],
        tape_path=tmp_path / "tape.jsonl",
        shadow_path=tmp_path / "shadow.jsonl",
        interval=0.01,
        clock=lambda: _CLOCK,
    )


def _ts(symbol: str, price: float, size: int = 100) -> TimeSale:
    return TimeSale(symbol, price=price, size=size, bid=price - 0.02, ask=price, ms=1_000)


def test_ignores_option_contract_prints(tmp_path: Path) -> None:
    rec = _recorder(tmp_path)
    rec.on_timesale(_ts("QQQ260629C00720000", 4.00))  # an option leg, not the underlying
    assert rec.profiles["QQQ"].total == 0.0
    assert rec._tape_buf == []  # nothing captured for a non-underlying symbol


def test_tracks_underlying_and_buffers_raw_tape(tmp_path: Path) -> None:
    rec = _recorder(tmp_path)
    rec.on_timesale(_ts("QQQ", 719.40, size=100))

    assert rec.profiles["QQQ"].total == pytest.approx(100.0)
    assert rec.rates["QQQ"].rate() == pytest.approx(100.0)
    assert len(rec._tape_buf) == 1
    assert not rec.tape_path.exists()  # buffered, not yet flushed to disk

    rec.flush_tape()
    rows = [json.loads(line) for line in rec.tape_path.read_text().splitlines()]
    assert rows == [
        {"symbol": "QQQ", "price": 719.40, "size": 100, "bid": 719.38, "ask": 719.40, "ms": 1_000}
    ]
    assert rec._tape_buf == []  # cleared after flush


def test_flush_tape_is_a_noop_when_empty(tmp_path: Path) -> None:
    rec = _recorder(tmp_path)
    rec.flush_tape()
    assert not rec.tape_path.exists()


def test_write_snapshots_one_row_per_traded_underlying(tmp_path: Path) -> None:
    rec = _recorder(tmp_path, symbols=["QQQ", "SPY"])
    rec.on_timesale(_ts("QQQ", 719.40, size=100))  # QQQ trades; SPY never does

    rec.write_snapshots()
    rows = [json.loads(line) for line in rec.shadow_path.read_text().splitlines()]
    assert len(rows) == 1  # only the traded underlying
    row = rows[0]
    assert row["ts"] == _CLOCK
    assert row["symbol"] == "QQQ"
    assert row["last"] == pytest.approx(719.40)
    assert row["poc"] == pytest.approx(719.40)
    assert row["total_vol"] == pytest.approx(100.0)
    assert set(row) >= {"poc", "val", "vah", "n_bins", "rate", "baseline", "ratio"}


def test_snapshots_skip_when_nothing_traded(tmp_path: Path) -> None:
    rec = _recorder(tmp_path)
    rec.write_snapshots()
    assert not rec.shadow_path.exists()  # no profile yet -> no file


def test_run_flushes_tape_and_snapshot_on_cancel(tmp_path: Path) -> None:
    rec = _recorder(tmp_path)
    rec.on_timesale(_ts("QQQ", 719.40, size=100))

    async def drive() -> None:
        task = asyncio.create_task(rec.run())
        await asyncio.sleep(0)  # let run() reach its first sleep
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())

    # the finally-clause flushed both artifacts
    assert len(rec.tape_path.read_text().splitlines()) == 1
    snap = json.loads(rec.shadow_path.read_text().splitlines()[0])
    assert snap["symbol"] == "QQQ" and snap["total_vol"] == pytest.approx(100.0)


def test_default_paths() -> None:
    assert default_tape_path("2026-06-29", root=Path("/tmp/x")) == Path(
        "/tmp/x/2026-06-29-tape.jsonl"
    )
    assert default_shadow_path("2026-06-29", root=Path("/tmp/x")) == Path(
        "/tmp/x/2026-06-29-shadow.jsonl"
    )
