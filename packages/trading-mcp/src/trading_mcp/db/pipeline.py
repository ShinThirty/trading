import asyncio
import sqlite3
from enum import StrEnum

from trading_mcp.db import normalize_enums, now


class Intent(StrEnum):
    ACCUMULATE = "accumulate"
    ENTER_AT_DISCOUNT = "enter-at-discount"
    HARVEST_PREMIUM = "harvest-premium"
    BEARISH = "bearish"
    EXIT = "exit"
    IPO_MOMENTUM = "ipo-momentum"
    WATCHLIST = "watchlist"


class Status(StrEnum):
    LIVE = "LIVE"
    WAITING = "WAITING"
    PIPELINE = "PIPELINE"
    SKIP = "SKIP"
    CLOSED = "CLOSED"
    SHELVED = "SHELVED"
    REMOVED = "REMOVED"


TERMINAL_STATUSES = frozenset({Status.CLOSED, Status.SHELVED, Status.REMOVED, Status.SKIP})


class Pipeline(StrEnum):
    WEBULL = "webull"
    FIDELITY = "fidelity"


class Tier(StrEnum):
    FULL = "full"
    STANDARD = "standard"
    REDUCED = "reduced"


class Conviction(StrEnum):
    HIGHEST = "highest"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    NEGATIVE = "negative"


# Maps field name to (enum class, normalizer applied before enum lookup)
_ENUM_FIELDS: dict[str, tuple[type[StrEnum], callable]] = {
    "intent": (Intent, str.lower),
    "status": (Status, str.upper),
    "pipeline": (Pipeline, str.lower),
    "tier": (Tier, str.lower),
    "conviction": (Conviction, str.lower),
}

ENTRY_COLUMNS = [
    "id",
    "ticker",
    "intent",
    "status",
    "account",
    "pipeline",
    "tier",
    "conviction",
    "priority",
    "thesis",
    "position",
    "entry_plan",
    "management",
    "catalysts",
    "watch_items",
    "pe",
    "peg",
    "roe",
    "de",
    "drawdown_pct",
    "rev_growth",
    "earnings_date",
    "created_at",
    "updated_at",
    "closed_at",
]

UPDATABLE_FIELDS = frozenset(ENTRY_COLUMNS) - {"id", "created_at", "updated_at", "closed_at"}

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS pipeline_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT    NOT NULL,
    intent        TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    account       TEXT,
    pipeline      TEXT,
    tier          TEXT,
    conviction    TEXT,
    priority      INTEGER,
    thesis        TEXT,
    position      TEXT,
    entry_plan    TEXT,
    management    TEXT,
    catalysts     TEXT,
    watch_items   TEXT,
    pe            REAL,
    peg           REAL,
    roe           REAL,
    de            REAL,
    drawdown_pct  REAL,
    rev_growth    REAL,
    earnings_date TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_ticker ON pipeline_entries(ticker);
CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline_entries(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_pipeline ON pipeline_entries(pipeline);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_ticker_active
    ON pipeline_entries(ticker) WHERE status NOT IN ('CLOSED', 'REMOVED', 'SHELVED', 'SKIP');

CREATE TABLE IF NOT EXISTS pipeline_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id   INTEGER NOT NULL REFERENCES pipeline_entries(id) ON DELETE CASCADE,
    note       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notes_entry ON pipeline_notes(entry_id);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# -- Sync internals --


def _add_entry(conn: sqlite3.Connection, data: dict) -> dict:
    normalize_enums(data, _ENUM_FIELDS)

    data["ticker"] = data["ticker"].upper()
    data.setdefault("status", Status.PIPELINE.value)
    ts = now()
    data["created_at"] = ts
    data["updated_at"] = ts

    fields = [k for k in ENTRY_COLUMNS if k != "id" and k in data]
    placeholders = ", ".join(["?"] * len(fields))
    cols = ", ".join(fields)
    values = [data[k] for k in fields]

    cur = conn.execute(
        f"INSERT INTO pipeline_entries ({cols}) VALUES ({placeholders})", values
    )
    conn.commit()
    return _get_entry_by_id(conn, cur.lastrowid)


def _get_active_entry(conn: sqlite3.Connection, ticker: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM pipeline_entries WHERE ticker = ? "
        "AND status NOT IN ('CLOSED', 'REMOVED', 'SHELVED', 'SKIP') "
        "ORDER BY updated_at DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    return dict(row) if row else None


def _get_entry_by_id(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM pipeline_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    return dict(row) if row else None


def _list_entries(
    conn: sqlite3.Connection,
    *,
    pipeline: str | None = None,
    status: str | None = None,
    intent: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    clauses: list[str] = []
    params: list[str] = []

    if not include_closed:
        clauses.append("status NOT IN ('CLOSED', 'REMOVED', 'SHELVED', 'SKIP')")
    if pipeline:
        clauses.append("pipeline = ?")
        params.append(Pipeline(pipeline.lower()).value)
    if status:
        clauses.append("status = ?")
        params.append(Status(status.upper()).value)
    if intent:
        clauses.append("intent = ?")
        params.append(Intent(intent.lower()).value)

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM pipeline_entries WHERE {where} ORDER BY pipeline, priority, ticker",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _update_entry(conn: sqlite3.Connection, ticker: str, updates: dict) -> dict:
    entry = _get_active_entry(conn, ticker)
    if entry is None:
        raise ValueError(f"No active pipeline entry for {ticker.upper()}")

    normalize_enums(updates, _ENUM_FIELDS)

    fields = {k: v for k, v in updates.items() if k in UPDATABLE_FIELDS and v is not None}
    if not fields:
        raise ValueError("No valid fields to update")

    ts = now()
    fields["updated_at"] = ts

    new_status = fields.get("status", "")
    if new_status in TERMINAL_STATUSES:
        fields["closed_at"] = ts

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [entry["id"]]
    conn.execute(f"UPDATE pipeline_entries SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return _get_entry_by_id(conn, entry["id"])


def _close_entry(conn: sqlite3.Connection, ticker: str, status: str = "CLOSED") -> dict:
    resolved = Status(status.upper())
    if resolved not in TERMINAL_STATUSES:
        terminal = ", ".join(s.value for s in TERMINAL_STATUSES)
        raise ValueError(f"Status must be terminal: {terminal}")

    entry = _get_active_entry(conn, ticker)
    if entry is None:
        raise ValueError(f"No active pipeline entry for {ticker.upper()}")

    ts = now()
    conn.execute(
        "UPDATE pipeline_entries SET status = ?, closed_at = ?, updated_at = ? WHERE id = ?",
        (resolved.value, ts, ts, entry["id"]),
    )
    conn.commit()
    return _get_entry_by_id(conn, entry["id"])


def _add_note(conn: sqlite3.Connection, ticker: str, note: str) -> dict:
    entry = _get_active_entry(conn, ticker)
    if entry is None:
        raise ValueError(f"No active pipeline entry for {ticker.upper()}")

    cur = conn.execute(
        "INSERT INTO pipeline_notes (entry_id, note) VALUES (?, ?)",
        (entry["id"], note),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM pipeline_notes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def _get_notes(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pipeline_notes WHERE entry_id = ? ORDER BY created_at",
        (entry_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# -- Async public API --


async def add_entry(conn: sqlite3.Connection, data: dict) -> dict:
    return await asyncio.to_thread(_add_entry, conn, data)


async def get_active_entry(conn: sqlite3.Connection, ticker: str) -> dict | None:
    return await asyncio.to_thread(_get_active_entry, conn, ticker)


async def get_entry_by_id(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    return await asyncio.to_thread(_get_entry_by_id, conn, entry_id)


async def list_entries(
    conn: sqlite3.Connection,
    *,
    pipeline: str | None = None,
    status: str | None = None,
    intent: str | None = None,
    include_closed: bool = False,
) -> list[dict]:
    return await asyncio.to_thread(
        _list_entries,
        conn,
        pipeline=pipeline,
        status=status,
        intent=intent,
        include_closed=include_closed,
    )


async def update_entry(conn: sqlite3.Connection, ticker: str, updates: dict) -> dict:
    return await asyncio.to_thread(_update_entry, conn, ticker, updates)


async def close_entry(conn: sqlite3.Connection, ticker: str, status: str = "CLOSED") -> dict:
    return await asyncio.to_thread(_close_entry, conn, ticker, status)


async def add_note(conn: sqlite3.Connection, ticker: str, note: str) -> dict:
    return await asyncio.to_thread(_add_note, conn, ticker, note)


async def get_notes(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    return await asyncio.to_thread(_get_notes, conn, entry_id)
