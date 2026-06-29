"""Operational watchdog — detect when the alerting fleet itself is broken.

Runs daily and surfaces four classes of failure:

  * **Lambda errors (24h)** — non-zero `AWS/Lambda.Errors` on dispatcher or
    interaction Lambdas. Watchers are supposed to `return []` on "no data",
    not raise; any error is a real bug worth investigating.

  * **Missed EventBridge invocations (10d)** — for each managed rule
    (one per watcher, including this one), check `AWS/Events.Invocations`.
    Zero invocations in 10 days catches both disabled daily rules (~3d gap
    over a long weekend) and missed weekly rules (7d cadence + margin).

  * **Pipeline.json staleness** — local trading-mcp publishes the active
    pipeline on every mutation. If the S3 object hasn't been touched in
    `PIPELINE_STALE_DAYS` days, the local sync may be down and ticker-aware
    watchers are operating on stale tickers. Missing object is treated as
    "not yet configured" (no alert) so first deploys stay quiet.

  * **DynamoDB health** — `describe_table` must succeed and report ACTIVE.
    If not, dedup state is broken and alerts will spam or drop silently.

Returns `[]` when everything looks healthy. Each alert is its own
`AlertEvent` so the user can mute one without muting the others.
"""

import logging
import os
from datetime import UTC, date, datetime, timedelta

from trading_alerts.config import AlertsConfig
from trading_alerts.event import AlertEvent

logger = logging.getLogger(__name__)
# Lambda's root logger defaults to WARNING; bump ours so watchdog INFO lines
# (e.g. "watchdog: emitted N ops event(s)") land in CloudWatch like the handler's.
logger.setLevel(logging.INFO)

# Includes "watchdog" so a missed self-run yesterday is reported today.
_TRIGGERS_TO_CHECK = (
    "naaim",
    "gex",
    "dix",
    "fomc",
    "gdp",
    "pce",
    "cpi",
    "nfp",
    "factset_ei",
    "qra",
    "beige_book",
    "wpsr",
    "tsmc_revenue",
    "material_8k",
    "activist_filing",
    "insider_buying",
    "watchdog",
)

_LAMBDA_FUNCTIONS = ("trading-alerts-dispatcher", "trading-alerts-interaction")

INVOCATION_LOOKBACK_DAYS = 10
LAMBDA_ERROR_LOOKBACK_HOURS = 24
PIPELINE_STALE_DAYS = 7

# Date-windowed watchers fire on a day-of-month range, so their EventBridge rule
# legitimately stays silent for longer than the default 10d between windows. Use
# a lookback past each one's real max inter-fire gap, or a normal quiet stretch
# gets flagged as a dead rule and re-alerts every day until the next window.
#   cpi          fires days 10-15  → ~26d max gap
#   pce          fires days 26-31  → ~27d max gap
#   tsmc_revenue fires days 5-20   → ~16d max gap
_INVOCATION_LOOKBACK_OVERRIDES = {
    "cpi": 35,
    "pce": 35,
    "tsmc_revenue": 35,
}


def _rule_name(trigger: str) -> str:
    # EventBridge rule names use dashes, not underscores (see terraform/main.tf).
    return "trading-alerts-" + trigger.replace("_", "-")


async def run(config: AlertsConfig) -> list[AlertEvent]:
    del config  # AWS creds come from the Lambda role / local default chain.
    import boto3

    today = date.today().isoformat()
    events: list[AlertEvent] = []
    cw = boto3.client("cloudwatch")

    err_event = _check_lambda_errors(cw, today)
    if err_event is not None:
        events.append(err_event)

    for trigger in _TRIGGERS_TO_CHECK:
        ev = _check_rule_invocations(cw, trigger, today)
        if ev is not None:
            events.append(ev)

    pipe_event = _check_pipeline_freshness(today)
    if pipe_event is not None:
        events.append(pipe_event)

    db_event = _check_dynamodb_health(today)
    if db_event is not None:
        events.append(db_event)

    logger.info("watchdog: emitted %d ops event(s)", len(events))
    return events


def _check_lambda_errors(cw, today: str) -> AlertEvent | None:
    end = datetime.now(UTC)
    start = end - timedelta(hours=LAMBDA_ERROR_LOOKBACK_HOURS)
    queries = [
        {
            "Id": f"q{i}",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/Lambda",
                    "MetricName": "Errors",
                    "Dimensions": [{"Name": "FunctionName", "Value": fn}],
                },
                "Period": 3600,
                "Stat": "Sum",
            },
            "ReturnData": True,
            "Label": fn,
        }
        for i, fn in enumerate(_LAMBDA_FUNCTIONS)
    ]
    try:
        resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    except Exception as exc:
        logger.warning("cloudwatch get_metric_data (errors) failed: %s", exc)
        return None

    counts: dict[str, int] = {}
    for r in resp.get("MetricDataResults", []):
        counts[r.get("Label", r.get("Id", "?"))] = int(sum(r.get("Values", []) or []))
    total = sum(counts.values())
    if total == 0:
        return None

    fields = [
        {"name": "Window", "value": f"last {LAMBDA_ERROR_LOOKBACK_HOURS}h", "inline": True},
        {"name": "Total", "value": str(total), "inline": True},
    ]
    for fn, c in counts.items():
        fields.append({"name": fn, "value": str(c), "inline": True})

    return AlertEvent(
        dedup_key=f"ops:watchdog:lambda_errors:{today}",
        level="warning",
        title=f"[OPS] Lambda errors detected ({total} in last {LAMBDA_ERROR_LOOKBACK_HOURS}h)",
        fields=fields,
        footer_text="trading-alerts watchdog — check CloudWatch logs",
        ttl_days=2,
    )


def _check_rule_invocations(cw, trigger: str, today: str) -> AlertEvent | None:
    rule = _rule_name(trigger)
    lookback_days = _INVOCATION_LOOKBACK_OVERRIDES.get(trigger, INVOCATION_LOOKBACK_DAYS)
    end = datetime.now(UTC)
    start = end - timedelta(days=lookback_days)
    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/Events",
            MetricName="Invocations",
            Dimensions=[{"Name": "RuleName", "Value": rule}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
        )
    except Exception as exc:
        logger.warning("cloudwatch get_metric_statistics for %s failed: %s", rule, exc)
        return None

    total = int(sum(d.get("Sum", 0) for d in resp.get("Datapoints", []) or []))
    if total > 0:
        return None

    return AlertEvent(
        dedup_key=f"ops:watchdog:no_invocations:{rule}:{today}",
        level="critical",
        title=f"[OPS] {trigger}: no invocations in last {lookback_days}d",
        fields=[
            {"name": "Trigger", "value": trigger, "inline": True},
            {"name": "Rule", "value": rule, "inline": True},
            {"name": "Window", "value": f"{lookback_days}d", "inline": True},
        ],
        footer_text="trading-alerts watchdog — EventBridge rule may be disabled",
        ttl_days=2,
    )


def _check_pipeline_freshness(today: str) -> AlertEvent | None:
    bucket = os.environ.get("PIPELINE_STATE_BUCKET")
    key = os.environ.get("PIPELINE_STATE_KEY")
    if not bucket or not key:
        return None

    import boto3

    try:
        head = boto3.client("s3").head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        # Missing object on first deploy = nothing to alert about.
        logger.info("pipeline.json head_object failed (treating as missing): %s", exc)
        return None

    last_modified = head["LastModified"]
    if last_modified.tzinfo is None:
        last_modified = last_modified.replace(tzinfo=UTC)
    age = datetime.now(UTC) - last_modified
    if age.days < PIPELINE_STALE_DAYS:
        return None

    return AlertEvent(
        dedup_key=f"ops:watchdog:pipeline_stale:{today}",
        level="warning",
        title=f"[OPS] pipeline.json is {age.days}d old",
        fields=[
            {"name": "Bucket", "value": bucket, "inline": False},
            {"name": "Key", "value": key, "inline": True},
            {
                "name": "Last Modified",
                "value": last_modified.strftime("%Y-%m-%d %H:%M UTC"),
                "inline": True,
            },
            {"name": "Age", "value": f"{age.days}d", "inline": True},
        ],
        footer_text="trading-alerts watchdog — local trading-mcp publish may be down",
        ttl_days=2,
    )


def _check_dynamodb_health(today: str) -> AlertEvent | None:
    table = os.environ.get("DYNAMODB_TABLE")
    if not table:
        return None

    import boto3

    try:
        resp = boto3.client("dynamodb").describe_table(TableName=table)
    except Exception as exc:
        return AlertEvent(
            dedup_key=f"ops:watchdog:dynamodb:{today}",
            level="critical",
            title="[OPS] DynamoDB describe_table failed",
            fields=[
                {"name": "Table", "value": table, "inline": True},
                {"name": "Error", "value": f"```{exc!s}```"[:1024], "inline": False},
            ],
            footer_text="trading-alerts watchdog",
            ttl_days=2,
        )

    status = resp.get("Table", {}).get("TableStatus", "UNKNOWN")
    if status == "ACTIVE":
        return None

    return AlertEvent(
        dedup_key=f"ops:watchdog:dynamodb:{today}",
        level="critical",
        title=f"[OPS] DynamoDB table not ACTIVE (status: {status})",
        fields=[
            {"name": "Table", "value": table, "inline": True},
            {"name": "Status", "value": status, "inline": True},
        ],
        footer_text="trading-alerts watchdog",
        ttl_days=2,
    )
