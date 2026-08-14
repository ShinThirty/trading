"""FINRA corporate bond market breadth persistence.

FINRA partitions `corporateMarketBreadth` on the trade date, so reading a
history means one HTTP round trip per session — fine for a batch backfill,
far too slow to do inside a tool call. This table is the local copy: the
backfill writes it once, the tool reads the trend window out of it, and a
daily poll appends the newest session.

Persisting also makes the *shadow period* mean something. A signal that is only
ever read as a live snapshot accumulates no evidence, so no amount of waiting
would ever qualify it for promotion. The stored series is what a base rate gets
computed against.

Two universes share the table, distinguished by `universe`:
  - `all`  : all reported corporate bonds
  - `144a` : 144A private placements only — the channel speculative issuers
             fund through, and the reason this data is worth keeping

Each (date, universe) carries one row per grade (all securities / investment
grade / high yield / convertibles).

Published sessions are immutable, so writes are plain upserts with no
source-priority arbitration — unlike `twse_revenue`, there is only ever one
source for a given cell.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

from trading_mcp.db import now

UNIVERSE_ALL = "all"
UNIVERSE_144A = "144a"

# A 204 from FINRA means "no rows", which is either a holiday or a session that
# hasn't published yet — FINRA runs T+1. Only treat an empty as *permanent*
# past this age; recording a recent one would make every later run skip the
# date forever and leave a hole in the series.
EMPTY_IS_FINAL_AFTER_DAYS = 7

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS credit_breadth (
    trade_date           TEXT    NOT NULL,
    universe             TEXT    NOT NULL,
    grade                TEXT    NOT NULL,
    total_trades         INTEGER NOT NULL,
    advances             INTEGER NOT NULL,
    declines             INTEGER NOT NULL,
    unchanged            INTEGER NOT NULL,
    fifty_two_week_high  INTEGER NOT NULL,
    fifty_two_week_low   INTEGER NOT NULL,
    total_volume_mm      REAL    NOT NULL,
    updated_at           TEXT    NOT NULL,
    PRIMARY KEY (trade_date, universe, grade)
);

CREATE INDEX IF NOT EXISTS idx_credit_breadth_date
    ON credit_breadth(trade_date DESC);

-- Sessions FINRA answered with an empty 204 (holidays, and dates before the
-- dataset's history begins). Recorded so a resumed backfill doesn't re-request
-- them forever; without this the same ~40 holidays get retried on every run.
CREATE TABLE IF NOT EXISTS credit_breadth_empty (
    trade_date  TEXT NOT NULL,
    universe    TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (trade_date, universe)
);
"""

_COLUMNS = (
    "trade_date",
    "universe",
    "grade",
    "total_trades",
    "advances",
    "declines",
    "unchanged",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "total_volume_mm",
)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# ── Sync internals ─────────────────────────────────────────────


def _upsert_session(
    conn: sqlite3.Connection,
    trade_date: date,
    universe: str,
    rows: list[dict],
) -> int:
    """Write every grade row for one (date, universe). Returns rows written."""
    stamp = now()
    conn.executemany(
        "INSERT OR REPLACE INTO credit_breadth "
        "(trade_date, universe, grade, total_trades, advances, declines, unchanged, "
        " fifty_two_week_high, fifty_two_week_low, total_volume_mm, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                trade_date.isoformat(),
                universe,
                r["grade"],
                r["total_trades"],
                r["advances"],
                r["declines"],
                r["unchanged"],
                r["fifty_two_week_high"],
                r["fifty_two_week_low"],
                r["total_volume_mm"],
                stamp,
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def _mark_empty(conn: sqlite3.Connection, trade_date: date, universe: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO credit_breadth_empty (trade_date, universe, checked_at) "
        "VALUES (?, ?, ?)",
        (trade_date.isoformat(), universe, now()),
    )
    conn.commit()


def _known_dates(conn: sqlite3.Connection, universe: str) -> set[str]:
    """Dates already resolved for a universe — populated or confirmed empty.

    The union is what makes the backfill resumable: anything in here is settled
    and never needs another request.
    """
    have = conn.execute(
        "SELECT DISTINCT trade_date FROM credit_breadth WHERE universe = ?",
        (universe,),
    ).fetchall()
    empty = conn.execute(
        "SELECT trade_date FROM credit_breadth_empty WHERE universe = ?",
        (universe,),
    ).fetchall()
    return {r["trade_date"] for r in have} | {r["trade_date"] for r in empty}


def _select_grade_series(
    conn: sqlite3.Connection,
    universe: str,
    grade: str,
    limit: int,
    end: str | None = None,
) -> list[dict]:
    """One grade's series for one universe, newest-first."""
    sql = (
        "SELECT trade_date, grade, total_trades, advances, declines, unchanged, "
        "       fifty_two_week_high, fifty_two_week_low, total_volume_mm "
        "FROM credit_breadth WHERE universe = ? AND grade = ?"
    )
    params: list[object] = [universe, grade]
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    sql += " ORDER BY trade_date DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _select_session(conn: sqlite3.Connection, trade_date: str, universe: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trade_date, grade, total_trades, advances, declines, unchanged, "
        "       fifty_two_week_high, fifty_two_week_low, total_volume_mm "
        "FROM credit_breadth WHERE trade_date = ? AND universe = ?",
        (trade_date, universe),
    ).fetchall()
    return [dict(r) for r in rows]


def _coverage(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT MIN(trade_date) AS first_date, MAX(trade_date) AS last_date, "
        "       COUNT(DISTINCT trade_date) AS sessions "
        "FROM credit_breadth"
    ).fetchone()
    per_universe = conn.execute(
        "SELECT universe, COUNT(DISTINCT trade_date) AS sessions "
        "FROM credit_breadth GROUP BY universe"
    ).fetchall()
    return {
        "first_date": row["first_date"] if row else None,
        "last_date": row["last_date"] if row else None,
        "sessions": int(row["sessions"]) if row and row["sessions"] else 0,
        "by_universe": {r["universe"]: int(r["sessions"]) for r in per_universe},
    }


# ── Async public API ───────────────────────────────────────────


async def upsert_session(
    conn: sqlite3.Connection, trade_date: date, universe: str, rows: list[dict]
) -> int:
    return await asyncio.to_thread(_upsert_session, conn, trade_date, universe, rows)


async def mark_empty(conn: sqlite3.Connection, trade_date: date, universe: str) -> None:
    await asyncio.to_thread(_mark_empty, conn, trade_date, universe)


async def known_dates(conn: sqlite3.Connection, universe: str) -> set[str]:
    return await asyncio.to_thread(_known_dates, conn, universe)


async def select_grade_series(
    conn: sqlite3.Connection,
    universe: str,
    grade: str,
    limit: int,
    end: str | None = None,
) -> list[dict]:
    return await asyncio.to_thread(_select_grade_series, conn, universe, grade, limit, end)


async def select_session(conn: sqlite3.Connection, trade_date: str, universe: str) -> list[dict]:
    return await asyncio.to_thread(_select_session, conn, trade_date, universe)


async def coverage(conn: sqlite3.Connection) -> dict:
    return await asyncio.to_thread(_coverage, conn)
