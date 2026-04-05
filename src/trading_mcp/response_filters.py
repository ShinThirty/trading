"""Response processing for Webull API endpoints.

Every API response passes through `process()` which applies two stages:

1. **Field filtering** — drop unneeded top-level keys to reduce token usage.
   Configure via FIELD_FILTERS (set of keys to keep, or None for passthrough).

2. **Transformation** — reshape, rename, flatten, or enrich data so the model
   gets clean, self-explanatory output. Configure via TRANSFORMERS (a function
   that receives the filtered response and returns the final output).

Both stages are optional per endpoint. If neither is configured, the raw
response passes through unchanged.

Once the live API is available, inspect raw responses and populate the
filters and transformers below.
"""

from collections.abc import Callable
from typing import Any

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
# Map endpoint path to a function(data) -> transformed_data.
# Runs AFTER field filtering. Use this to reshape, rename fields,
# flatten nested structures, or add computed values.
#
# Example:
#   def _transform_balance(data: dict) -> dict:
#       return {
#           "total_assets": data.get("total_asset"),
#           "cash": data.get("total_cash"),
#           "market_value": data.get("total_market_value"),
#           "day_pnl": data.get("total_profit_loss"),
#           "total_pnl": data.get("history_profit_loss"),
#       }
#   TRANSFORMERS["/account/balance"] = _transform_balance
#
# Example (list of items):
#   def _transform_positions(data: list[dict]) -> list[dict]:
#       return [
#           {
#               "symbol": p.get("instrument", {}).get("symbol"),
#               "qty": p.get("quantity"),
#               "cost_basis": p.get("total_cost"),
#               "market_value": p.get("market_value"),
#               "pnl": p.get("unrealized_profit_loss"),
#               "pnl_pct": p.get("unrealized_profit_loss_rate"),
#           }
#           for p in data
#       ]
#   TRANSFORMERS["/account/positions"] = _transform_positions

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

    # Stage 2: transformation
    transformer = TRANSFORMERS.get(path)
    if transformer is not None:
        data = transformer(data)

    return data
