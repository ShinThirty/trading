"""AlertEvent — the payload a watcher returns when a trigger fires."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlertEvent:
    """One alert from a watcher.

    The dedup_key uniquely identifies the alert *content* (e.g., a specific
    weekly NAAIM print, a specific day's GEX flip). If a watcher fires
    repeatedly with the same dedup_key — because the underlying data hasn't
    refreshed yet — the dispatcher recognizes the duplicate and skips
    re-posting.
    """

    dedup_key: str
    level: str  # "info", "warning", "critical"
    title: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    footer_text: str | None = None
    ttl_days: int = 14  # DynamoDB TTL horizon for the dedup record
