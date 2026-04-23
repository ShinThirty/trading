import sqlite3
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


def normalize_enums(data: dict, enum_fields: dict[str, tuple[type[StrEnum], callable]]) -> None:
    for field, (enum_cls, normalize) in enum_fields.items():
        value = data.get(field)
        if value is None:
            continue
        try:
            data[field] = enum_cls(normalize(value)).value
        except ValueError:
            allowed = ", ".join(m.value for m in enum_cls)
            raise ValueError(f"Invalid {field}: '{value}'. Allowed: {allowed}") from None
