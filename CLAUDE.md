# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP server for trading stocks and options on Webull. Exposes Webull brokerage data and order management as MCP tools for use with Claude. Supports stock orders and option orders (single-leg and multi-leg strategies like spreads, iron condors, etc.).

## Commands

```bash
uv sync                        # Install/sync all dependencies
uv run trading-mcp             # Start the MCP server (stdio transport)
uv run ruff check src/         # Lint
uv run ruff format src/        # Format
uv run ty check src/           # Type check
```

To add to Claude Code: `claude mcp add trading-mcp -- uv run trading-mcp`

## Architecture

```
src/trading_mcp/
├── config.py            # Loads credentials from ~/.webullrc (INI format, [webull] section)
├── webull_client.py     # Direct HTTP calls to Webull API with HMAC-SHA1 signing
├── response_filters.py  # Per-endpoint field filtering + markdown table transformation
└── server.py            # FastMCP server definition, tool registration, lifespan
```

**Data flow:** MCP tool call → `server.py` (extracts client from lifespan context) → `webull_client.py` (signed HTTP request to Webull) → `response_filters.process()` (filter fields, then transform to markdown table) → returns string to FastMCP.

The `WebullClient` is created once during server lifespan startup and shared across all tool invocations via FastMCP's lifespan context pattern.

### No Webull SDK

We call the Webull REST API directly instead of using `webull-python-sdk-*` packages. The SDK pins ancient versions of grpcio/protobuf that don't build on Python 3.12+. The API auth is straightforward HMAC-SHA1 signing implemented in `webull_client.py`.

## Credentials

Stored in `~/.webullrc`:
```ini
[webull]
app_key = <your_app_key>
app_secret = <your_app_secret>
account_id = <your_account_id>
region_id = us
```

## Webull API

- **Trade/Account host:** `api.webull.com`
- **Market data host:** `usquotes-api.webullfintech.com`
- **Option order endpoints** use different paths (`/openapi/account/orders/option/*`) and pass `account_id` as a query param (not in body). Stock order endpoints (`/trade/order/*`) pass `account_id` in the POST body.
- **Auth:** HMAC-SHA1 signature over sorted headers + URI + query params + MD5(body). Headers: `x-api-key`, `x-api-timestamp`, `x-api-sign-version`, `x-api-sign-algorithm`, `x-api-nonce`, `x-api-signature`.
- **Option API regional availability:** The option order endpoints (`/openapi/account/orders/option/*`) are documented as **HK-only** in the Webull SDK docs (v0.1.18, Sep 2025). Stock order endpoints (`/trade/order/*`) have no region restriction and work for US. The `new_orders` body structure supports both single-leg and multi-leg strategies (nested `orders` list per entry). When US API access is available, test the option endpoints — US support may have been added since the docs were last updated. Do not remove the option tools; they're ready for when US support lands.

## Response Processing

Webull API responses contain many fields that waste tokens and can confuse the model. All responses pass through a two-stage pipeline in `response_filters.py` via `process()`:

1. **Field filtering (`FIELD_FILTERS`)** — maps endpoint path to a set of top-level keys to keep. `None` means passthrough (current default for all endpoints).
2. **Transformation (`TRANSFORMERS`)** — maps endpoint path to a function that converts the filtered data into a **markdown table string**. This is critical for reducing hallucinations — the model parses tables far more reliably than nested JSON.

Helper functions in `response_filters.py`:
- `_kv_table(data)` — for single-object responses (e.g. account profile → two-column Field/Value table)
- `_list_table(items, columns)` — for list responses (e.g. positions → one row per holding)
- `_md_table(headers, rows)` — low-level builder for custom layouts

When adding a new endpoint or updating processing, inspect the raw API response first, then:
- Populate the keep-set in `FIELD_FILTERS` with only the fields needed.
- Add a transformer in `TRANSFORMERS` that returns a markdown table string.

## Conventions

- All MCP tools are defined in `server.py` and delegate to `WebullClient` methods
- `WebullClient` methods return markdown table strings (once transformers are populated) or raw dicts/lists (passthrough)
- New tools should follow the same pattern: `@mcp.tool()` in server.py → method in webull_client.py → filter + transformer in response_filters.py
- Ruff rules: E, F, I (isort), UP (pyupgrade). Line length: 100.
