"""Alert state persistence — DynamoDB (Lambda) or in-memory (local).

Schema (DynamoDB table key = dedup_key):
    level             : str   — info / warning / critical
    last_notified_at  : int   — Unix epoch
    cooldown_until    : int   — Unix epoch (currently vestigial; reserved
                                for future re-notify scenarios)
    ttl_expire        : int   — Unix epoch; DynamoDB TTL auto-cleanup
    muted_until       : int   — Unix epoch; 0 = not muted
"""

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class AlertRecord:
    """One persisted alert. Absence of a record means "not yet sent"."""

    dedup_key: str
    level: str
    last_notified_at: float
    cooldown_until: float
    ttl_expire: int
    muted_until: float = 0


class AlertStore(Protocol):
    def get(self, dedup_key: str) -> AlertRecord | None: ...
    def put(self, record: AlertRecord) -> None: ...


class DynamoAlertStore:
    """Best-effort DynamoDB-backed alert state.

    Failures log errors but do not crash the watcher — we'd rather send a
    duplicate than miss an alert entirely.
    """

    def __init__(self, table_name: str) -> None:
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)

    def get(self, dedup_key: str) -> AlertRecord | None:
        try:
            resp = self._table.get_item(Key={"dedup_key": dedup_key})
            item = resp.get("Item")
            if not item:
                return None
            return AlertRecord(
                dedup_key=item["dedup_key"],
                level=item["level"],
                last_notified_at=float(item["last_notified_at"]),
                cooldown_until=float(item.get("cooldown_until", 0)),
                ttl_expire=int(item["ttl_expire"]),
                muted_until=float(item.get("muted_until", 0)),
            )
        except Exception:
            logger.exception("Failed to read alert state for %s", dedup_key)
            return None

    def put(self, record: AlertRecord) -> None:
        try:
            self._table.put_item(
                Item={
                    "dedup_key": record.dedup_key,
                    "level": record.level,
                    "last_notified_at": int(record.last_notified_at),
                    "cooldown_until": int(record.cooldown_until),
                    "ttl_expire": record.ttl_expire,
                    "muted_until": int(record.muted_until),
                }
            )
        except Exception:
            logger.exception("Failed to write alert state for %s", record.dedup_key)


class InMemoryAlertStore:
    """In-memory alert state for local testing (no DynamoDB required)."""

    def __init__(self) -> None:
        self._store: dict[str, AlertRecord] = {}

    def get(self, dedup_key: str) -> AlertRecord | None:
        return self._store.get(dedup_key)

    def put(self, record: AlertRecord) -> None:
        self._store[record.dedup_key] = record


def alert_store(table_name: str | None) -> AlertStore:
    """Pick the right backing store given an optional DynamoDB table name."""
    if table_name:
        return DynamoAlertStore(table_name)
    return InMemoryAlertStore()
