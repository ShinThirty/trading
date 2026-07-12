"""BasisRecorder: the future↔reference (SPX) carry-basis shadow series.

Pins the price-selection rules (future = quote mid, reference index = last trade, each
with a fallback), the both-legs-required gate, and the write-only artifact.
"""

import json
from pathlib import Path

from trading_clients.market_stream import Quote, Trade
from trading_scalper.basis import BasisRecorder

FUT = "/MESU26:XCME"
REF = "SPX"


def _rec(tmp_path: Path) -> BasisRecorder:
    return BasisRecorder(FUT, REF, basis_path=tmp_path / "basis.jsonl", clock=lambda: "T")


def test_basis_is_future_mid_minus_reference_trade(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    rec.on_quote(Quote(FUT, bid=7625.5, ask=7626.5))  # future mid = 7626.0
    rec.on_trade(Trade(REF, 7575.0))  # index level prints as a Trade during RTH
    row = rec.snapshot_row()
    assert row is not None
    assert row["future_price"] == 7626.0
    assert row["reference_level"] == 7575.0
    assert row["basis"] == 51.0


def test_none_until_both_legs_have_a_price(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    assert rec.snapshot_row() is None
    rec.on_quote(Quote(FUT, bid=7625.5, ask=7626.5))
    assert rec.snapshot_row() is None  # reference still missing
    rec.on_trade(Trade(REF, 7575.0))
    assert rec.snapshot_row() is not None


def test_future_falls_back_to_last_trade_without_a_quote(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    rec.on_trade(Trade(FUT, 7626.0))  # no quote yet → use the last trade
    rec.on_trade(Trade(REF, 7575.0))
    assert rec.snapshot_row()["basis"] == 51.0


def test_reference_falls_back_to_quote_mid_without_a_trade(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    rec.on_quote(Quote(FUT, bid=7625.5, ask=7626.5))  # future mid 7626.0
    rec.on_quote(Quote(REF, bid=7560.0, ask=7580.0))  # index quote mid 7570.0, no trade
    assert rec.snapshot_row()["basis"] == 56.0


def test_ignores_unrelated_symbols(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    rec.on_quote(Quote("QQQ", bid=1.0, ask=2.0))
    rec.on_trade(Trade("QQQ", 1.5))
    assert rec.snapshot_row() is None  # neither leg is the future or the reference


def test_write_snapshot_appends_a_row_and_skips_when_incomplete(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    rec.write_snapshot()  # incomplete → no file
    assert not rec.basis_path.exists()

    rec.on_quote(Quote(FUT, bid=7625.5, ask=7626.5))
    rec.on_trade(Trade(REF, 7575.0))
    rec.write_snapshot()

    rows = [json.loads(line) for line in rec.basis_path.read_text().splitlines()]
    assert rows == [
        {
            "ts": "T",
            "future": FUT,
            "future_price": 7626.0,
            "reference": REF,
            "reference_level": 7575.0,
            "basis": 51.0,
        }
    ]
