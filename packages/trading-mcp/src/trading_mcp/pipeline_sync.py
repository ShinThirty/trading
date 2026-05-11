"""Publish the active pipeline universe to S3 for Lambda watchers.

SQLite (~/.trading/trading.db) remains the source of truth. After every
mutating pipeline_* tool, we serialize the active entries (status NOT IN
CLOSED/SHELVED/REMOVED/SKIP) and upload to s3://{PIPELINE_STATE_BUCKET}/
{PIPELINE_STATE_KEY}. Watchers fetch this object on cold start to filter
ticker-aware alerts to the active universe.

Best-effort: a failed S3 write logs a warning but never raises — local
mutations always succeed. The bucket / key are read from environment vars
so the publish is a silent no-op when unconfigured (e.g. local dev without
AWS, CI, or before the Terraform apply).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime

from trading_mcp.db.pipeline import list_entries

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_BUCKET_ENV = "PIPELINE_STATE_BUCKET"
_KEY_ENV = "PIPELINE_STATE_KEY"

# Internal columns the watcher universe doesn't need.
_EXCLUDED_FIELDS = frozenset({"id"})


def _serialize(entries: list[dict]) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entries": [{k: v for k, v in e.items() if k not in _EXCLUDED_FIELDS} for e in entries],
    }
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


_PROFILE_ENV = "PIPELINE_STATE_AWS_PROFILE"


def _put(bucket: str, key: str, body: bytes) -> None:
    import boto3

    profile = os.environ.get(_PROFILE_ENV, "personal")
    boto3.Session(profile_name=profile).client("s3").put_object(
        Bucket=bucket, Key=key, Body=body, ContentType="application/json"
    )


async def publish_pipeline_to_s3(conn: sqlite3.Connection) -> int:
    """Best-effort sync of active pipeline entries to S3.

    No-ops silently if PIPELINE_STATE_BUCKET / PIPELINE_STATE_KEY are unset.
    Logs a warning (does not raise) on any failure so the caller's mutation
    is never blocked.

    Returns the number of entries published, or 0 on no-op / failure.
    """
    bucket = os.environ.get(_BUCKET_ENV)
    key = os.environ.get(_KEY_ENV)
    if not bucket or not key:
        return 0

    try:
        entries = await list_entries(conn, include_closed=False)
        body = _serialize(entries)
        await asyncio.to_thread(_put, bucket, key, body)
        logger.debug("Published %d pipeline entries to s3://%s/%s", len(entries), bucket, key)
        return len(entries)
    except Exception as exc:
        logger.warning("Failed to publish pipeline to s3://%s/%s: %s", bucket, key, exc)
        return 0
