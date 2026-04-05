"""Response processing for Webull API endpoints.

Every API response passes through `process()` which applies two stages:

1. **Field filtering** — drop unneeded top-level keys to reduce token usage.
   Configure via FIELD_FILTERS (set of keys to keep, or None for passthrough).

2. **Transformation** — convert the response to a markdown table string so the
   model gets clean, structured, unambiguous output. This drastically reduces
   hallucinations compared to raw JSON. Configure via TRANSFORMERS.

Both stages are optional per endpoint. If neither is configured, the raw
response passes through unchanged.

Once the live API is available, inspect raw responses and populate the
filters and transformers below.
"""

from collections.abc import Callable
from typing import Any

# ── Markdown table helpers ───────────────────────────────────


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a markdown table from headers and rows."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        # Pad row to match header count
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _kv_table(data: dict, key_header: str = "Field", val_header: str = "Value") -> str:
    """Build a two-column key/value markdown table from a dict."""
    headers = [key_header, val_header]
    rows = [[str(k), str(v)] for k, v in data.items() if v is not None]
    return _md_table(headers, rows)


def _list_table(items: list[dict], columns: list[str] | None = None) -> str:
    """Build a markdown table from a list of dicts.

    If columns is provided, only those keys are included (in that order).
    Otherwise all keys from the first item are used.
    """
    if not items:
        return "(no data)"
    if columns is None:
        columns = list(items[0].keys())
    rows = [[str(item.get(c, "")) for c in columns] for item in items]
    return _md_table(columns, rows)


# ── Per-endpoint top-level field keep-sets ────────────────────
# Set to None (or omit) to pass through all fields.
# Example:
#   "/account/profile": {"account_number", "account_type"},

FIELD_FILTERS: dict[str, set[str] | None] = {
    # Account
    "/account/profile": None,
    "/account/balance": None,
    "/account/positions": None,
    "/account/position/details": None,
    # Orders (read)
    "/trade/orders/list-open": None,
    "/trade/orders/list-today": None,
    "/trade/order/detail": None,
    # Order management
    "/openapi/account/orders/history": None,
    "/openapi/account/orders/preview": None,
    "/trade/order/place": None,
    "/trade/order/replace": None,
    "/trade/order/cancel": None,
    "/openapi/account/orders/option/preview": None,
    "/openapi/account/orders/option/place": None,
    "/openapi/account/orders/option/replace": None,
    "/openapi/account/orders/option/cancel": None,
    # Trade info
    "/trade/calendar": None,
    "/trade/instrument": None,
    "/trade/security": None,
    "/trade/instrument/tradable/list": None,
    "/app/subscriptions/list": None,
    # Market data
    "/market-data/snapshot": None,
    "/instrument/list": None,
    "/market-data/bars": None,
    "/market-data/batch-bars": None,
    "/market-data/eod-bars": None,
    "/instrument/corp-action": None,
}


# ── Per-endpoint response transformers ───────────────────────
# Each transformer converts filtered API data into a markdown table string.
# Runs AFTER field filtering.
#
# TODO: Once live API access is available, inspect raw responses and
# implement transformers for each endpoint. Below are stubs based on
# the SDK demo field names. Adjust column names and field paths once
# real response shapes are confirmed.
#
# Pattern for a dict response (single object):
#   def _transform_profile(data: dict) -> str:
#       return _kv_table({
#           "Account Number": data.get("account_number"),
#           "Account Type": data.get("account_type"),
#       })
#
# Pattern for a list response (multiple items):
#   def _transform_positions(data: list[dict]) -> str:
#       rows = [
#           {
#               "Symbol": p.get("instrument", ""),
#               "Qty": p.get("quantity", ""),
#               "Cost Basis": p.get("total_cost", ""),
#               "Mkt Value": p.get("market_value", ""),
#               "P&L": p.get("unrealized_profit_loss", ""),
#               "P&L %": p.get("unrealized_profit_loss_rate", ""),
#           }
#           for p in data
#       ]
#       return _list_table(rows)

TRANSFORMERS: dict[str, Callable[[Any], Any]] = {}


def _apply_field_filter(data: Any, fields: set[str]) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields}
    if isinstance(data, list):
        return [
            {k: v for k, v in item.items() if k in fields}
            for item in data
            if isinstance(item, dict)
        ]
    return data


def process(path: str, data: Any) -> Any:
    """Filter and transform an API response based on its endpoint path."""
    # Stage 1: field filtering
    fields = FIELD_FILTERS.get(path)
    if fields is not None:
        data = _apply_field_filter(data, fields)

    # Stage 2: transform to markdown table
    transformer = TRANSFORMERS.get(path)
    if transformer is not None:
        data = transformer(data)

    return data
