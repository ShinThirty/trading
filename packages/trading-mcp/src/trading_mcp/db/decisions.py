import asyncio
import sqlite3
from enum import StrEnum

from trading_mcp.db import OptionType, normalize_enums, now


class Action(StrEnum):
    CLOSE = "CLOSE"
    ROLL = "ROLL"
    ASSIGN = "ASSIGN"
    HOLD = "HOLD"
    WRITE_NEW = "WRITE_NEW"


class DecisionStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset(
    {DecisionStatus.DONE, DecisionStatus.EXPIRED, DecisionStatus.CANCELLED}
)

_ENUM_FIELDS: dict[str, tuple[type[StrEnum], callable]] = {
    "option_type": (OptionType, str.lower),
    "action": (Action, str.upper),
    "status": (DecisionStatus, str.upper),
}

DECISION_COLUMNS = [
    "id",
    "ticker",
    "strike",
    "expiry",
    "option_type",
    "account",
    "quantity",
    "action",
    "status",
    "rationale",
    "deadline",
    "outcome",
    "source",
    "roll_id",
    "created_at",
    "updated_at",
    "completed_at",
]

UPDATABLE_FIELDS = frozenset(DECISION_COLUMNS) - {"id", "created_at", "updated_at", "completed_at"}

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS option_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT    NOT NULL,
    strike        REAL    NOT NULL,
    expiry        TEXT    NOT NULL,
    option_type   TEXT    NOT NULL,
    account       TEXT,
    quantity      INTEGER NOT NULL DEFAULT 1,
    action        TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'PENDING',
    rationale     TEXT,
    deadline      TEXT,
    outcome       TEXT,
    source        TEXT,
    roll_id       INTEGER REFERENCES rolls(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON option_decisions(ticker);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON option_decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_deadline ON option_decisions(deadline);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# -- Sync internals --


def _add_decision(conn: sqlite3.Connection, data: dict) -> dict:
    normalize_enums(data, _ENUM_FIELDS)
    data["ticker"] = data["ticker"].upper()
    data.setdefault("status", DecisionStatus.PENDING.value)
    ts = now()
    data["created_at"] = ts
    data["updated_at"] = ts

    fields = [k for k in DECISION_COLUMNS if k != "id" and k in data]
    placeholders = ", ".join(["?"] * len(fields))
    cols = ", ".join(fields)
    values = [data[k] for k in fields]

    cur = conn.execute(
        f"INSERT INTO option_decisions ({cols}) VALUES ({placeholders})", values
    )
    conn.commit()
    return _get_decision_by_id(conn, cur.lastrowid)


def _get_decision_by_id(conn: sqlite3.Connection, decision_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM option_decisions WHERE id = ?", (decision_id,)
    ).fetchone()
    return dict(row) if row else None


def _list_decisions(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    status: str | None = None,
    action: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []

    if not include_closed:
        clauses.append("status NOT IN ('DONE', 'EXPIRED', 'CANCELLED')")
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.upper())
    if status:
        clauses.append("status = ?")
        params.append(DecisionStatus(status.upper()).value)
    if action:
        clauses.append("action = ?")
        params.append(Action(action.upper()).value)
    if account:
        clauses.append("account = ?")
        params.append(account)
    if option_type:
        clauses.append("option_type = ?")
        params.append(OptionType(option_type.lower()).value)

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM option_decisions WHERE {where} ORDER BY ticker, deadline, created_at",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _update_decision(conn: sqlite3.Connection, decision_id: int, updates: dict) -> dict:
    decision = _get_decision_by_id(conn, decision_id)
    if decision is None:
        raise ValueError(f"No decision with id {decision_id}")
    if decision["status"] in TERMINAL_STATUSES:
        raise ValueError(f"Decision {decision_id} is already {decision['status']}")

    normalize_enums(updates, _ENUM_FIELDS)

    fields = {k: v for k, v in updates.items() if k in UPDATABLE_FIELDS and v is not None}
    if not fields:
        raise ValueError("No valid fields to update")

    fields["updated_at"] = now()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [decision_id]
    conn.execute(f"UPDATE option_decisions SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return _get_decision_by_id(conn, decision_id)


def _close_decision(
    conn: sqlite3.Connection,
    decision_id: int,
    status: str,
    outcome: str | None = None,
) -> dict:
    resolved = DecisionStatus(status.upper())
    if resolved not in TERMINAL_STATUSES:
        terminal = ", ".join(s.value for s in TERMINAL_STATUSES)
        raise ValueError(f"Status must be terminal: {terminal}")

    decision = _get_decision_by_id(conn, decision_id)
    if decision is None:
        raise ValueError(f"No decision with id {decision_id}")

    ts = now()
    updates: dict = {"status": resolved.value, "updated_at": ts, "completed_at": ts}
    if outcome:
        updates["outcome"] = outcome

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [decision_id]
    conn.execute(f"UPDATE option_decisions SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return _get_decision_by_id(conn, decision_id)


# -- Async public API --


async def add_decision(conn: sqlite3.Connection, data: dict) -> dict:
    return await asyncio.to_thread(_add_decision, conn, data)


async def get_decision_by_id(conn: sqlite3.Connection, decision_id: int) -> dict | None:
    return await asyncio.to_thread(_get_decision_by_id, conn, decision_id)


async def list_decisions(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    status: str | None = None,
    action: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    return await asyncio.to_thread(
        _list_decisions,
        conn,
        ticker=ticker,
        status=status,
        action=action,
        account=account,
        option_type=option_type,
        include_closed=include_closed,
    )


async def update_decision(conn: sqlite3.Connection, decision_id: int, updates: dict) -> dict:
    return await asyncio.to_thread(_update_decision, conn, decision_id, updates)


async def close_decision(
    conn: sqlite3.Connection,
    decision_id: int,
    status: str,
    outcome: str | None = None,
) -> dict:
    return await asyncio.to_thread(
        _close_decision, conn, decision_id, status, outcome=outcome
    )
