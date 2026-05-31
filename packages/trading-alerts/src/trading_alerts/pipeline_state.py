"""Read the pipeline snapshot published by trading-mcp.

The local trading-mcp pipeline_* tools publish active entries to
s3://{PIPELINE_STATE_BUCKET}/{PIPELINE_STATE_KEY} on every mutation.
Ticker-aware watchers call get_pipeline() on cold start to filter their
universe to the active pipeline.

Module-level cache: fetched once per Lambda container (~15 min lifetime),
then reused for every warm invocation. New container = fresh fetch. No TTL
needed — container churn is the natural refresh.

Tolerates the missing-object case (returns []) so the first deploy works
before the local sync has ever run.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_BUCKET_ENV = "PIPELINE_STATE_BUCKET"
_KEY_ENV = "PIPELINE_STATE_KEY"

_cache: list[dict[str, Any]] | None = None


def get_pipeline() -> list[dict[str, Any]]:
    """Return active pipeline entries from S3, cached for container lifetime.

    Each entry is a dict carrying ticker / intent / status / pipeline / tier
    / conviction / priority / earnings_date / thesis / watch_items
    / numeric snapshots. Watchers can filter by any field (e.g. only fire on
    high-conviction names).

    Returns [] if the bucket / key env vars are unset, the object does not
    exist, or the fetch fails — never raises.
    """
    global _cache
    if _cache is not None:
        return _cache

    bucket = os.environ.get(_BUCKET_ENV)
    key = os.environ.get(_KEY_ENV)
    if not bucket or not key:
        logger.warning("%s / %s not set; pipeline filter unavailable", _BUCKET_ENV, _KEY_ENV)
        _cache = []
        return _cache

    try:
        import boto3

        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        payload = json.loads(body)
        _cache = payload.get("entries", [])
        logger.info("Loaded %d pipeline entries from s3://%s/%s", len(_cache), bucket, key)
    except Exception as exc:
        logger.warning("Failed to load pipeline from s3://%s/%s: %s", bucket, key, exc)
        _cache = []

    return _cache


def get_pipeline_tickers() -> set[str]:
    """Convenience: just the active ticker symbols, uppercased."""
    return {e["ticker"].upper() for e in get_pipeline() if e.get("ticker")}


def reset_cache() -> None:
    """Test hook — drop the module-level cache so the next call re-fetches."""
    global _cache
    _cache = None
