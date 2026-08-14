"""credit_breadth — local history for FINRA corporate bond market breadth.

Pins the persistence contract the backfill and the MCP tool both depend on:
idempotent upserts, the resumability set (stored ∪ confirmed-empty), and the
newest-N ordering the trend window reads. Also pins the run-length detection
behind the base-rate analysis, where an off-by-one would silently change the
recommended alert threshold.
"""

import asyncio
import importlib.util
import sqlite3
import sys
from datetime import date
from pathlib import Path

from trading_mcp.db.credit_breadth import (
    UNIVERSE_144A,
    UNIVERSE_ALL,
    coverage,
    init_schema,
    known_dates,
    mark_empty,
    select_grade_series,
    select_session,
    upsert_session,
)

_SPEC = importlib.util.spec_from_file_location(
    "analyze_credit_divergence",
    Path(__file__).resolve().parent.parent
    / "packages"
    / "trading-mcp"
    / "scripts"
    / "analyze_credit_divergence.py",
)
analyze = importlib.util.module_from_spec(_SPEC)
# Register before exec: @dataclass resolves annotations through
# sys.modules[cls.__module__], which is absent for a spec-loaded module.
sys.modules[_SPEC.name] = analyze
_SPEC.loader.exec_module(analyze)

GRADE_HY = "high yield"
GRADE_IG = "investment grade"


def _conn() -> sqlite3.Connection:
    # check_same_thread=False mirrors open_db(): the async wrappers run their
    # queries via asyncio.to_thread, so the connection is used off the thread
    # that created it.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def _rows(grade: str = GRADE_HY, hi: int = 100, lo: int = 20) -> list[dict]:
    return [
        {
            "grade": grade,
            "total_trades": 1500,
            "advances": 900,
            "declines": 500,
            "unchanged": 100,
            "fifty_two_week_high": hi,
            "fifty_two_week_low": lo,
            "total_volume_mm": 1234.5,
        }
    ]


def test_upsert_and_read_back() -> None:
    async def drive() -> None:
        conn = _conn()
        await upsert_session(conn, date(2026, 8, 13), UNIVERSE_ALL, _rows())
        got = await select_session(conn, "2026-08-13", UNIVERSE_ALL)
        assert len(got) == 1
        assert got[0]["grade"] == GRADE_HY
        assert got[0]["fifty_two_week_high"] == 100
        assert got[0]["total_volume_mm"] == 1234.5

    asyncio.run(drive())


def test_upsert_is_idempotent_and_overwrites_in_place() -> None:
    """Re-running the backfill over stored dates must not duplicate rows."""

    async def drive() -> None:
        conn = _conn()
        day = date(2026, 8, 13)
        await upsert_session(conn, day, UNIVERSE_ALL, _rows(hi=100))
        await upsert_session(conn, day, UNIVERSE_ALL, _rows(hi=111))
        got = await select_session(conn, "2026-08-13", UNIVERSE_ALL)
        assert len(got) == 1
        assert got[0]["fifty_two_week_high"] == 111

    asyncio.run(drive())


def test_universes_do_not_collide() -> None:
    async def drive() -> None:
        conn = _conn()
        day = date(2026, 8, 13)
        await upsert_session(conn, day, UNIVERSE_ALL, _rows(hi=259, lo=51))
        await upsert_session(conn, day, UNIVERSE_144A, _rows(hi=72, lo=18))
        broad = await select_session(conn, "2026-08-13", UNIVERSE_ALL)
        a144 = await select_session(conn, "2026-08-13", UNIVERSE_144A)
        assert broad[0]["fifty_two_week_high"] == 259
        assert a144[0]["fifty_two_week_high"] == 72

    asyncio.run(drive())


def test_known_dates_unions_stored_and_empty() -> None:
    """This set is what makes the backfill resumable — a date in either table
    is settled and must never be re-requested."""

    async def drive() -> None:
        conn = _conn()
        await upsert_session(conn, date(2026, 8, 13), UNIVERSE_ALL, _rows())
        await mark_empty(conn, date(2026, 7, 4), UNIVERSE_ALL)
        known = await known_dates(conn, UNIVERSE_ALL)
        assert known == {"2026-08-13", "2026-07-04"}
        # A holiday marked for one universe says nothing about the other.
        assert await known_dates(conn, UNIVERSE_144A) == set()

    asyncio.run(drive())


def test_grade_series_returns_newest_first_and_respects_limit() -> None:
    async def drive() -> None:
        conn = _conn()
        for d in range(1, 11):
            await upsert_session(conn, date(2026, 8, d), UNIVERSE_ALL, _rows(hi=d))
        series = await select_grade_series(conn, UNIVERSE_ALL, GRADE_HY, 3)
        assert [r["trade_date"] for r in series] == [
            "2026-08-10",
            "2026-08-09",
            "2026-08-08",
        ]

    asyncio.run(drive())


def test_grade_series_end_bound() -> None:
    async def drive() -> None:
        conn = _conn()
        for d in range(1, 11):
            await upsert_session(conn, date(2026, 8, d), UNIVERSE_ALL, _rows(hi=d))
        series = await select_grade_series(conn, UNIVERSE_ALL, GRADE_HY, 2, end="2026-08-05")
        assert [r["trade_date"] for r in series] == ["2026-08-05", "2026-08-04"]

    asyncio.run(drive())


def test_coverage_reports_span_and_per_universe_counts() -> None:
    async def drive() -> None:
        conn = _conn()
        await upsert_session(conn, date(2026, 8, 11), UNIVERSE_ALL, _rows())
        await upsert_session(conn, date(2026, 8, 13), UNIVERSE_ALL, _rows())
        await upsert_session(conn, date(2026, 8, 13), UNIVERSE_144A, _rows())
        cov = await coverage(conn)
        assert cov["first_date"] == "2026-08-11"
        assert cov["last_date"] == "2026-08-13"
        assert cov["sessions"] == 2
        assert cov["by_universe"] == {UNIVERSE_ALL: 2, UNIVERSE_144A: 1}

    asyncio.run(drive())


def test_empty_coverage_on_fresh_db() -> None:
    async def drive() -> None:
        cov = await coverage(_conn())
        assert cov["sessions"] == 0
        assert cov["by_universe"] == {}

    asyncio.run(drive())


# ── Base-rate analysis ─────────────────────────────────────────


def test_runs_finds_consecutive_stretches() -> None:
    assert analyze.runs([False, True, True, False, True]) == [(1, 2), (4, 1)]
    assert analyze.runs([True, True, True]) == [(0, 3)]
    assert analyze.runs([False, False]) == []
    assert analyze.runs([]) == []


def test_runs_handles_trailing_stretch() -> None:
    """A run ending at the last element must still be counted — dropping it
    would undercount exactly the most recent, most decision-relevant episode."""
    assert analyze.runs([False, True, True]) == [(1, 2)]


def test_divergence_flag_requires_144a_negative_and_broad_not() -> None:
    def s(a144: int, broad: int) -> analyze.Session:
        return analyze.Session(
            day=date(2026, 8, 13), broad_hy_net=broad, a144_hy_net=a144, broad_ig_net=0
        )

    assert s(-5, 10).diverging  # 144A cracking, broad fine → fires
    assert not s(-5, -10).diverging  # both weak → not a divergence
    assert not s(5, 10).diverging  # 144A fine → no
    assert s(-1, 0).diverging  # broad exactly flat still counts as "not negative"


def test_duration_signature_is_ig_negative_hy_positive() -> None:
    def s(ig: int, hy: int) -> analyze.Session:
        return analyze.Session(
            day=date(2026, 8, 13), broad_hy_net=hy, a144_hy_net=0, broad_ig_net=ig
        )

    assert s(-87, 208).duration_signature  # the 2026-08-13 live reading
    assert not s(50, 208).duration_signature
    assert not s(-87, -50).duration_signature  # both negative = broad weakness
