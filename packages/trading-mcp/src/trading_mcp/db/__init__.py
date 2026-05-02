import sqlite3
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".trading" / "trading.db"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


def open_db(path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


EnumFields = dict[str, tuple[type[StrEnum], Callable[[str], str]]]


def normalize_enums(data: dict, enum_fields: EnumFields) -> None:
    for field, (enum_cls, normalize) in enum_fields.items():
        value = data.get(field)
        if value is None:
            continue
        try:
            data[field] = enum_cls(normalize(value)).value
        except ValueError:
            allowed = ", ".join(m.value for m in enum_cls)
            raise ValueError(f"Invalid {field}: '{value}'. Allowed: {allowed}") from None


def normalize_input(data: dict, enum_fields: EnumFields, *, uppercase_ticker: bool = False) -> None:
    """Apply enum normalization and (optionally) upper-case the ticker field in-place."""
    normalize_enums(data, enum_fields)
    if uppercase_ticker and "ticker" in data and data["ticker"]:
        data["ticker"] = data["ticker"].upper()


def insert_row(conn: sqlite3.Connection, table: str, data: dict, columns: Iterable[str]) -> int:
    """Generic INSERT — uses only keys from `data` that appear in `columns` (excluding `id`).
    Commits and returns lastrowid. Caller is responsible for setting timestamps/defaults."""
    fields = [k for k in columns if k != "id" and k in data]
    placeholders = ", ".join(["?"] * len(fields))
    cols = ", ".join(fields)
    values = [data[k] for k in fields]
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
    conn.commit()
    if cur.lastrowid is None:
        raise RuntimeError(f"INSERT into {table} returned no row id")
    return cur.lastrowid


def select_by_id(conn: sqlite3.Connection, table: str, row_id: int) -> dict | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def select_required(conn: sqlite3.Connection, table: str, row_id: int) -> dict:
    """Like `select_by_id` but raises if missing. Use after a write to assert the row exists."""
    row = select_by_id(conn, table, row_id)
    if row is None:
        raise RuntimeError(f"Row {row_id} not found in {table}")
    return row


def update_by_id(conn: sqlite3.Connection, table: str, row_id: int, fields: dict) -> None:
    """Generic UPDATE — caller passes already-validated/filtered fields including updated_at."""
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), row_id]
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", values)
    conn.commit()


def filter_updatable(updates: dict, updatable: frozenset[str]) -> dict:
    """Drop keys that aren't in `updatable` or whose value is None."""
    return {k: v for k, v in updates.items() if k in updatable and v is not None}


def resolve_terminal(
    status: str,
    enum_cls: type[StrEnum],
    normalize: Callable[[str], str],
    terminal: frozenset,
) -> StrEnum:
    """Normalize+coerce `status` to enum and require it be a terminal value, else raise."""
    resolved = enum_cls(normalize(status))
    if resolved not in terminal:
        allowed = ", ".join(s.value for s in terminal)
        raise ValueError(f"Status must be terminal: {allowed}")
    return resolved
