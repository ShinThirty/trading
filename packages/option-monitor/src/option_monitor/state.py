"""Alert state persistence — DynamoDB (Lambda) or in-memory (local)."""

import logging
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class AlertRecord:
    """A single alert state entry, maps to a DynamoDB item."""

    dedup_key: str  # PK: {account_id}:{symbol}-{strike}-{exp}-{type}
    level: str  # warning, critical, resolved
    last_notified_at: float  # Unix epoch
    cooldown_until: float  # Unix epoch (last_notified + cooldown)
    underlying_price: float
    proximity_pct: float
    dte: int
    ttl_expire: int  # Unix epoch, 7 days after option expiration
    muted_until: float = 0  # Unix epoch, 0 = not muted


class DynamoAlertStore:
    """Read/write alert state to DynamoDB.

    Operations are best-effort: failures log errors but don't crash the handler.
    This ensures alerts still fire even if DynamoDB is temporarily unavailable
    (may send duplicates, but won't miss alerts).
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
                cooldown_until=float(item["cooldown_until"]),
                underlying_price=float(item["underlying_price"]),
                proximity_pct=float(item["proximity_pct"]),
                dte=int(item["dte"]),
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
                    "underlying_price": Decimal(str(round(record.underlying_price, 4))),
                    "proximity_pct": Decimal(str(round(record.proximity_pct, 6))),
                    "dte": record.dte,
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
