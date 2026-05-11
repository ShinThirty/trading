"""TWSE monthly revenue persistence.

Caches the trailing monthly revenue series for individual TWSE-listed
companies in the local SQLite DB so the MCP tool can return history
without hitting an external source every call. The OpenAPI feed only
exposes the most recent reporting month — every poll upserts three
explicit months (current, prior, same-month-prior-year) and lets the
history accumulate naturally over time.

Source tags:
  - twse_openapi : pulled from openapi.twse.com.tw t187ap05_L feed
  - derived      : computed from YTD arithmetic on an OpenAPI row
  - manual_seed  : inserted by the prepopulate script for older months
"""

from __future__ import annotations

import asyncio
import sqlite3

from trading_mcp.db import now

_TABLE = "twse_monthly_revenue"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS twse_monthly_revenue (
    company_code      TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    month             INTEGER NOT NULL,
    revenue_thousands INTEGER NOT NULL,
    yoy_pct           REAL,
    source            TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    PRIMARY KEY (company_code, year, month)
);

CREATE INDEX IF NOT EXISTS idx_twse_rev_company_ym
    ON twse_monthly_revenue(company_code, year DESC, month DESC);
"""

# Source-tag priority for upsert decisions — a higher-priority source can
# overwrite a lower one, but not vice-versa. Live API beats derived math
# beats manual seed.
_SOURCE_PRIORITY = {
    "manual_seed": 1,
    "derived": 2,
    "twse_openapi": 3,
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# ── Sync internals ─────────────────────────────────────────────


def _upsert(
    conn: sqlite3.Connection,
    *,
    company_code: str,
    year: int,
    month: int,
    revenue_thousands: int,
    yoy_pct: float | None,
    source: str,
) -> bool:
    """Insert or refresh a row. Returns True if the row was written.

    Source priority gate: a lower-priority source can't overwrite the
    revenue figure or source tag of a higher-priority row (e.g. a later
    `manual_seed` won't blow over a prior `twse_openapi` write for the
    same month). It *can* still fill a NULL `yoy_pct` — the OpenAPI only
    carries yoy_pct on the headline month, so prior-month and
    prior-year-month rows often land without it, and a later manual seed
    that knows the YoY shouldn't be wasted.

    Within an accepted same-or-higher-priority write, `yoy_pct` is
    likewise preserved from the existing row when the incoming value is
    None — a re-poll of the prior-month field shouldn't blank out a
    metric a previous call already captured.
    """
    if source not in _SOURCE_PRIORITY:
        raise ValueError(f"Unknown source: {source}")
    incoming = _SOURCE_PRIORITY[source]

    existing = conn.execute(
        "SELECT source, yoy_pct FROM twse_monthly_revenue "
        "WHERE company_code = ? AND year = ? AND month = ?",
        (company_code, year, month),
    ).fetchone()
    if existing is not None:
        prior = _SOURCE_PRIORITY.get(existing["source"], 0)
        if incoming < prior:
            # Don't touch revenue/source, but backfill a missing yoy_pct.
            if existing["yoy_pct"] is None and yoy_pct is not None:
                conn.execute(
                    "UPDATE twse_monthly_revenue SET yoy_pct = ?, updated_at = ? "
                    "WHERE company_code = ? AND year = ? AND month = ?",
                    (yoy_pct, now(), company_code, year, month),
                )
                conn.commit()
                return True
            return False
        if yoy_pct is None and existing["yoy_pct"] is not None:
            yoy_pct = existing["yoy_pct"]

    conn.execute(
        "INSERT OR REPLACE INTO twse_monthly_revenue "
        "(company_code, year, month, revenue_thousands, yoy_pct, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (company_code, year, month, revenue_thousands, yoy_pct, source, now()),
    )
    conn.commit()
    return True


def _select_recent(
    conn: sqlite3.Connection,
    company_code: str,
    limit: int,
) -> list[dict]:
    """Return the most-recent N months for a company, newest-first."""
    rows = conn.execute(
        "SELECT company_code, year, month, revenue_thousands, yoy_pct, source, updated_at "
        "FROM twse_monthly_revenue "
        "WHERE company_code = ? "
        "ORDER BY year DESC, month DESC "
        "LIMIT ?",
        (company_code, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _count(conn: sqlite3.Connection, company_code: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM twse_monthly_revenue WHERE company_code = ?",
        (company_code,),
    ).fetchone()
    return int(row["n"]) if row else 0


# ── Async public API ───────────────────────────────────────────


async def upsert(
    conn: sqlite3.Connection,
    *,
    company_code: str,
    year: int,
    month: int,
    revenue_thousands: int,
    yoy_pct: float | None,
    source: str,
) -> bool:
    return await asyncio.to_thread(
        _upsert,
        conn,
        company_code=company_code,
        year=year,
        month=month,
        revenue_thousands=revenue_thousands,
        yoy_pct=yoy_pct,
        source=source,
    )


async def select_recent(conn: sqlite3.Connection, company_code: str, limit: int) -> list[dict]:
    return await asyncio.to_thread(_select_recent, conn, company_code, limit)


async def count(conn: sqlite3.Connection, company_code: str) -> int:
    return await asyncio.to_thread(_count, conn, company_code)
