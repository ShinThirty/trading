import asyncio
import sqlite3
from enum import StrEnum

from trading_mcp.db import (
    EnumFields,
    OptionType,
    filter_updatable,
    insert_row,
    normalize_enums,
    normalize_input,
    now,
    resolve_terminal,
    select_by_id,
    select_required,
    update_by_id,
)


class RollStatus(StrEnum):
    PLANNED = "PLANNED"
    WORKING = "WORKING"
    FILLED = "FILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SKIP = "SKIP"


TERMINAL_STATUSES = frozenset(
    {RollStatus.FILLED, RollStatus.EXPIRED, RollStatus.CANCELLED, RollStatus.SKIP}
)

_ENUM_FIELDS: EnumFields = {
    "option_type": (OptionType, str.lower),
    "status": (RollStatus, str.upper),
}

ROLL_COLUMNS = [
    "id",
    "ticker",
    "account",
    "option_type",
    "quantity",
    "from_strike",
    "from_expiry",
    "to_strike",
    "to_expiry",
    "status",
    "net_credit",
    "reason",
    "created_at",
    "updated_at",
    "filled_at",
]

UPDATABLE_FIELDS = frozenset(ROLL_COLUMNS) - {"id", "created_at", "updated_at", "filled_at"}

_TABLE = "rolls"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS rolls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT    NOT NULL,
    account       TEXT,
    option_type   TEXT    NOT NULL,
    quantity      INTEGER NOT NULL DEFAULT 1,
    from_strike   REAL    NOT NULL,
    from_expiry   TEXT    NOT NULL,
    to_strike     REAL,
    to_expiry     TEXT,
    status        TEXT    NOT NULL DEFAULT 'PLANNED',
    net_credit    REAL,
    reason        TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    filled_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_rolls_ticker ON rolls(ticker);
CREATE INDEX IF NOT EXISTS idx_rolls_status ON rolls(status);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# -- Sync internals --


def _add_roll(conn: sqlite3.Connection, data: dict) -> dict:
    normalize_input(data, _ENUM_FIELDS, uppercase_ticker=True)
    data.setdefault("status", RollStatus.PLANNED.value)
    ts = now()
    data["created_at"] = ts
    data["updated_at"] = ts
    row_id = insert_row(conn, _TABLE, data, ROLL_COLUMNS)
    return select_required(conn, _TABLE, row_id)


def _get_roll_by_id(conn: sqlite3.Connection, roll_id: int) -> dict | None:
    return select_by_id(conn, _TABLE, roll_id)


def _get_active_rolls(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM rolls WHERE ticker = ? "
        "AND status NOT IN ('FILLED', 'EXPIRED', 'CANCELLED', 'SKIP') "
        "ORDER BY from_expiry",
        (ticker.upper(),),
    ).fetchall()
    return [dict(r) for r in rows]


def _list_rolls(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    status: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []

    if not include_closed:
        clauses.append("status NOT IN ('FILLED', 'EXPIRED', 'CANCELLED', 'SKIP')")
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if status:
        clauses.append("status = ?")
        params.append(RollStatus(status.upper()).value)
    if account:
        clauses.append("account = ?")
        params.append(account)
    if option_type:
        clauses.append("option_type = ?")
        params.append(OptionType(option_type.lower()).value)

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM rolls WHERE {where} ORDER BY ticker, from_expiry", params
    ).fetchall()
    return [dict(r) for r in rows]


def _update_roll(conn: sqlite3.Connection, roll_id: int, updates: dict) -> dict:
    roll = select_by_id(conn, _TABLE, roll_id)
    if roll is None:
        raise ValueError(f"No roll with id {roll_id}")
    if roll["status"] in TERMINAL_STATUSES:
        raise ValueError(f"Roll {roll_id} is already {roll['status']}")

    normalize_enums(updates, _ENUM_FIELDS)
    fields = filter_updatable(updates, UPDATABLE_FIELDS)
    if not fields:
        raise ValueError("No valid fields to update")

    fields["updated_at"] = now()
    update_by_id(conn, _TABLE, roll_id, fields)
    return select_required(conn, _TABLE, roll_id)


def _close_roll(
    conn: sqlite3.Connection,
    roll_id: int,
    status: str,
    reason: str | None = None,
    net_credit: float | None = None,
) -> dict:
    resolved = resolve_terminal(status, RollStatus, str.upper, TERMINAL_STATUSES)
    if select_by_id(conn, _TABLE, roll_id) is None:
        raise ValueError(f"No roll with id {roll_id}")

    ts = now()
    fields: dict = {"status": resolved.value, "updated_at": ts}
    if resolved == RollStatus.FILLED:
        fields["filled_at"] = ts
    if reason:
        fields["reason"] = reason
    if net_credit is not None:
        fields["net_credit"] = net_credit

    update_by_id(conn, _TABLE, roll_id, fields)
    return select_required(conn, _TABLE, roll_id)


# -- Async public API --


async def add_roll(conn: sqlite3.Connection, data: dict) -> dict:
    return await asyncio.to_thread(_add_roll, conn, data)


async def get_roll_by_id(conn: sqlite3.Connection, roll_id: int) -> dict | None:
    return await asyncio.to_thread(_get_roll_by_id, conn, roll_id)


async def get_active_rolls(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    return await asyncio.to_thread(_get_active_rolls, conn, ticker)


async def list_rolls(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    status: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    return await asyncio.to_thread(
        _list_rolls,
        conn,
        ticker=ticker,
        status=status,
        account=account,
        option_type=option_type,
        include_closed=include_closed,
    )


async def update_roll(conn: sqlite3.Connection, roll_id: int, updates: dict) -> dict:
    return await asyncio.to_thread(_update_roll, conn, roll_id, updates)


async def close_roll(
    conn: sqlite3.Connection,
    roll_id: int,
    status: str,
    reason: str | None = None,
    net_credit: float | None = None,
) -> dict:
    return await asyncio.to_thread(
        _close_roll, conn, roll_id, status, reason=reason, net_credit=net_credit
    )
