"""Tests for the scalper scorecard: extraction, cohort attribution, stats, gate, cache."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest
from trading_scalper.scorecard import (
    CACHE_NAME,
    SCHEMA_VERSION,
    ClosedTrade,
    Gate,
    compute_stats,
    extract_session,
    load_closed_trades,
    resolve_cohort,
)


def _write(path: Path, rows: list[dict], *, gz: bool = False) -> None:
    body = "\n".join(json.dumps(r) for r in rows) + "\n"
    if gz:
        path.with_name(path.name + ".gz").write_bytes(gzip.compress(body.encode()))
    else:
        path.write_text(body)


def _fill(bracket: str, side: str, delta: float | None, *, ts: str = "2026-06-23T15:00:00+00:00"):
    return {
        "ts": ts,
        "order_id": bracket,
        "bracket_id": bracket,
        "symbol": "QQQ260623C00520000",
        "side": side,
        "qty": 1,
        "fill_price": 2.0,
        "realized_delta": delta,
    }


def _signal(bracket: str, mode: str, version: str | None):
    row = {"ts": "2026-06-23T15:00:00+00:00", "symbol": "QQQ", "mode": mode, "bracket_id": bracket}
    if version is not None:
        row["version"] = version
    return row


def _session(root: Path, session: str, fills: list[dict], signals: list[dict], *, gz=False) -> None:
    _write(root / f"{session}.jsonl", fills, gz=gz)
    _write(root / f"{session}-signals.jsonl", signals, gz=gz)


# ── cohort attribution ───────────────────────────────────────────────────────


def test_stamped_version_overrides_the_retro_map() -> None:
    # A 2026-06-15 session that carries a stamp is graded by the stamp, not its date.
    assert resolve_cohort("2026-06-15", "0.4.2") == "0.4"


def test_retro_map_boundaries() -> None:
    assert resolve_cohort("2026-06-14", None) == "0.1"
    assert resolve_cohort("2026-06-15", None) == "0.2"  # downtime-safe break arming
    assert resolve_cohort("2026-06-22", None) == "0.2"
    assert resolve_cohort("2026-06-23", None) == "0.3"  # verdict modes + cooldown
    assert resolve_cohort("2026-07-09", None) == "0.3"  # shadow ship stayed observer-only


# ── extraction ───────────────────────────────────────────────────────────────


def test_extraction_closes_on_sell_counts_scratch_and_flags_orphans(tmp_path: Path) -> None:
    fills = [
        _fill("b1", "BUY", 0.0),
        _fill("b1", "SELL", 50.0),  # a winner
        _fill("b2", "BUY", 0.0),
        _fill("b2", "SELL", 0.0),  # a $0 scratch — still closed
        _fill("b3", "BUY", 0.0),  # open only — NOT closed
        _fill("b9", "SELL", -20.0),  # no signal row — orphan → "?"
    ]
    signals = [_signal("b1", "break", "0.3.1"), _signal("b2", "fade", "0.3.1")]
    _session(tmp_path, "2026-06-23", fills, signals)

    trades = {t.bracket_id: t for t in extract_session(tmp_path, "2026-06-23")}
    assert set(trades) == {"b1", "b2", "b9"}  # b3 (open-only) excluded
    assert trades["b1"].mode == "break" and trades["b1"].pnl == 50.0
    assert trades["b2"].mode == "fade" and trades["b2"].pnl == 0.0  # scratch counted
    assert trades["b9"].mode == "?" and trades["b9"].version is None  # orphan flagged


def test_extraction_sums_multi_fill_pnl(tmp_path: Path) -> None:
    # A partial-then-final exit: P&L is the sum of realized_delta across the bracket.
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 30.0), _fill("b1", "SELL", 15.0)]
    _session(tmp_path, "2026-06-23", fills, [_signal("b1", "retest", "0.3.1")])
    (trade,) = extract_session(tmp_path, "2026-06-23")
    assert trade.pnl == 45.0


def test_extraction_reads_gzipped_logs(tmp_path: Path) -> None:
    # Post-retention sessions are gzipped in place; extraction must still read them.
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 12.0)]
    _session(tmp_path, "2026-06-23", fills, [_signal("b1", "break", None)], gz=True)
    (trade,) = extract_session(tmp_path, "2026-06-23")
    assert trade.pnl == 12.0 and trade.version is None


# ── stats ────────────────────────────────────────────────────────────────────


def test_stats_math_is_hand_verifiable() -> None:
    trades = [
        ClosedTrade("2026-06-23", "t1", "b1", "break", "0.3.0", 100.0),
        ClosedTrade("2026-06-23", "t2", "b2", "break", "0.3.0", -50.0),
        ClosedTrade("2026-06-24", "t3", "b3", "break", "0.3.0", 40.0),
    ]
    (s,) = compute_stats(trades)
    assert s.cohort == "0.3" and s.mode == "break"
    assert s.n == 3 and s.sessions == 2
    assert s.total == 90.0
    assert s.expectancy == 30.0
    assert s.win_rate == pytest.approx(0.667, abs=1e-3)
    assert s.profit_factor == pytest.approx(2.8)  # 140 gross win / 50 gross loss
    assert s.max_drawdown == -50.0  # equity 100→50→90; peak 100; worst dip -50
    # gross wins 140, best session (6/23) contributes 100 → 0.714
    assert s.concentration == pytest.approx(0.714, abs=1e-3)
    # exp - 1.645 * stdev/sqrt(n) = 30 - 1.645*75.498/sqrt(3) ≈ -41.71
    assert s.expectancy_lb == pytest.approx(-41.71, abs=0.05)


def test_no_loss_gives_infinite_pf_and_single_trade_has_no_ci() -> None:
    import math

    (s,) = compute_stats([ClosedTrade("2026-06-29", "t", "b", "reversal", "0.3.0", 49.0)])
    assert math.isinf(s.profit_factor)  # no losing trade
    assert s.expectancy_lb is None  # n < 2, no confidence interval
    assert s.concentration == pytest.approx(1.0)


def test_compute_stats_groups_by_cohort_and_mode() -> None:
    trades = [
        ClosedTrade("2026-06-15", "t", "b1", "break", None, 10.0),  # retro → 0.2
        ClosedTrade("2026-06-23", "t", "b2", "break", None, 10.0),  # retro → 0.3
        ClosedTrade("2026-06-23", "t", "b3", "fade", "0.3.1", -5.0),
    ]
    stats = {(s.cohort, s.mode): s for s in compute_stats(trades)}
    assert set(stats) == {("0.2", "break"), ("0.3", "break"), ("0.3", "fade")}


# ── gate ─────────────────────────────────────────────────────────────────────


def _stats(**kw):
    base = dict(
        cohort="0.3",
        mode="break",
        n=60,
        sessions=12,
        win_rate=0.6,
        total=1200.0,
        expectancy=20.0,
        expectancy_lb=5.0,
        profit_factor=2.0,
        max_drawdown=-100.0,
        concentration=0.3,
    )
    base.update(kw)
    from trading_scalper.scorecard import ModeStats

    return ModeStats(**base)


def test_gate_passes_a_clean_cohort() -> None:
    assert Gate().evaluate(_stats()) == []


def test_gate_reports_each_failure() -> None:
    reasons = Gate().evaluate(
        _stats(n=22, sessions=3, profit_factor=0.4, expectancy_lb=-9.0, concentration=0.7)
    )
    joined = " ".join(reasons)
    assert "n=22" in joined and "sessions=3" in joined
    assert "PF" in joined and "expectancy LB" in joined and "concentration" in joined


def test_gate_flags_missing_confidence_interval() -> None:
    assert any("n≥2" in r for r in Gate().evaluate(_stats(n=1, expectancy_lb=None)))


# ── cache ────────────────────────────────────────────────────────────────────


class _CountingExtract:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, root: Path, session: str) -> list[ClosedTrade]:
        self.calls.append(session)
        return extract_session(root, session)


def test_past_sessions_are_cached_and_not_reparsed(tmp_path: Path) -> None:
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 25.0)]
    _session(tmp_path, "2026-06-23", fills, [_signal("b1", "break", "0.3.1")])
    today = date(2026, 7, 1)

    first = _CountingExtract()
    t1 = load_closed_trades(tmp_path, today=today, _extract=first)
    assert first.calls == ["2026-06-23"]  # parsed once
    assert (tmp_path / CACHE_NAME).exists()

    second = _CountingExtract()
    t2 = load_closed_trades(tmp_path, today=today, _extract=second)
    assert second.calls == []  # served entirely from cache
    assert [t.pnl for t in t1] == [t.pnl for t in t2] == [25.0]


def test_todays_session_is_never_cached(tmp_path: Path) -> None:
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 25.0)]
    _session(tmp_path, "2026-07-01", fills, [_signal("b1", "break", "0.3.1")])
    today = date(2026, 7, 1)

    first = _CountingExtract()
    load_closed_trades(tmp_path, today=today, _extract=first)
    second = _CountingExtract()
    load_closed_trades(tmp_path, today=today, _extract=second)
    assert first.calls == second.calls == ["2026-07-01"]  # re-parsed both times
    cache_file = tmp_path / CACHE_NAME
    if cache_file.exists():
        blob = json.loads(cache_file.read_text())
        assert "2026-07-01" not in blob.get("sessions", {})


def test_schema_mismatch_discards_and_rebuilds_cache(tmp_path: Path) -> None:
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 25.0)]
    _session(tmp_path, "2026-06-23", fills, [_signal("b1", "break", "0.3.1")])
    (tmp_path / CACHE_NAME).write_text(
        json.dumps({"schema": SCHEMA_VERSION + 999, "sessions": {"2026-06-23": []}})
    )
    today = date(2026, 7, 1)

    stub = _CountingExtract()
    trades = load_closed_trades(tmp_path, today=today, _extract=stub)
    assert stub.calls == ["2026-06-23"]  # stale-schema cache ignored → real parse
    assert [t.pnl for t in trades] == [25.0]
    blob = json.loads((tmp_path / CACHE_NAME).read_text())
    assert blob["schema"] == SCHEMA_VERSION  # rewritten at the current schema


def test_no_cache_flag_bypasses_and_never_writes(tmp_path: Path) -> None:
    fills = [_fill("b1", "BUY", 0.0), _fill("b1", "SELL", 25.0)]
    _session(tmp_path, "2026-06-23", fills, [_signal("b1", "break", "0.3.1")])
    stub = _CountingExtract()
    load_closed_trades(tmp_path, today=date(2026, 7, 1), use_cache=False, _extract=stub)
    assert stub.calls == ["2026-06-23"]
    assert not (tmp_path / CACHE_NAME).exists()
