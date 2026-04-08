# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@.claude/webull-api-docs.md

## Project Overview

MCP server for trading stocks and options on Webull, with integrated market analysis data from multiple providers. Exposes brokerage operations, option chains with greeks, fundamentals, news, economic data, and sentiment as MCP tools for use with Claude.

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
├── config.py              # Loads credentials from ~/.tradingrc (all providers)
├── webull_client.py       # Webull REST API with HMAC-SHA1 signing + TTL cache
├── tradier_client.py      # Tradier API — option chains, greeks, IV
├── finnhub_client.py      # Finnhub API — news, earnings, economic calendar, financials
├── fmp_client.py          # FMP API — income statement, balance sheet, cash flow, metrics
├── fred_client.py         # FRED API — macroeconomic data series (CPI, GDP, VIX, etc.)
├── alphavantage_client.py # Alpha Vantage API — news sentiment, top movers
├── response_filters.py    # Per-endpoint field filtering + markdown table transformation
└── server.py              # FastMCP server, tool registration, lifespan
```

**Data flow:** MCP tool call → `server.py` (extracts client from lifespan context) → `*_client.py` (HTTP request to provider) → returns data to FastMCP. Webull responses additionally pass through `response_filters.process()` for field filtering and markdown table transformation.

All clients are created once during server lifespan startup. Only Webull is required — other providers are optional and tools will return a clear error if the provider isn't configured.

### Provider Roles

| Provider | Role | Auth |
|---|---|---|
| **Webull** (required) | Brokerage: account, orders, positions, quotes, bars | HMAC-SHA1 + token |
| **Tradier** | Option chains with greeks + IV | Bearer token |
| **Finnhub** | News, earnings calendar, economic calendar, key metrics | API key |
| **FMP** | Financial statements, company profiles, valuation metrics | API key |
| **FRED** | Macroeconomic data (CPI, GDP, rates, VIX, yield curve) | API key |
| **Alpha Vantage** | News sentiment scoring, top market movers | API key |

### No Webull SDK

We call the Webull REST API directly instead of using `webull-python-sdk-*` packages. The SDK pins ancient versions of grpcio/protobuf that don't build on Python 3.12+. The API auth is straightforward HMAC-SHA1 signing implemented in `webull_client.py`.

## Credentials

Stored in `~/.tradingrc` (INI format). Only `[webull]` is required — other sections are optional:

```ini
[webull]
app_key = <your_app_key>
app_secret = <your_app_secret>
account_id = <optional_default_account_id>
region_id = us
token = <auto-managed, created on first use>

[tradier]
api_token = <your_sandbox_or_production_token>
sandbox = true

[finnhub]
api_key = <your_api_key>

[fmp]
api_key = <your_api_key>

[fred]
api_key = <your_api_key>

[alphavantage]
api_key = <your_api_key>
```

## Webull API (v2)

All Webull endpoints use the v2 API (`x-version: v2` header). Stock and option orders are unified into a single endpoint.

- **Trade/Account host:** `api.webull.com`
- **Market data host:** `data-api.webull.com`
- **Auth:** HMAC-SHA1 signature over sorted headers + URI + query params + MD5(body). Headers: `x-app-key`, `x-timestamp`, `x-signature-version`, `x-signature-algorithm`, `x-signature-nonce`, `x-signature`. Plus `x-version: v2` and `x-access-token` (not in signing).
- **Token lifecycle:** Tokens are created via `POST /openapi/auth/token/create`. Default expiry: 15 days of inactivity. New tokens have `PENDING` status and must be verified in the Webull App (Menu > Messages > OpenAPI Notifications). On 401, the client auto-creates a new token, saves to `~/.tradingrc`, and raises with verification instructions.
- **Unified order endpoint:** Stock and option orders both use `/openapi/trade/order/place`. Options use `instrument_type: "OPTION"` + `legs[]` array. Orders use `symbol` directly (no `instrument_id` lookup needed).
- **v2 endpoint paths:** All endpoints use `/openapi/` prefix: `/openapi/account/list`, `/openapi/assets/balance`, `/openapi/assets/positions`, `/openapi/trade/order/*`, `/openapi/instrument/stock/list`, `/openapi/market-data/stock/bars`, `/openapi/market-data/stock/snapshot`.
- **Timespan format:** Historical bars use `M1` (1 min), `M5`, `M15`, `M30`, `M60` (1 hour), `M120`, `M240`, `D` (daily), `W` (weekly), `M` (monthly), `Y` (yearly).
- **HTTP/2:** The httpx client is configured with `http2=True`.
- **Multi-account:** All account-specific methods accept an optional `account_id` parameter. Resolution order: explicit param > config default > error with instructions. Use `get_app_subscriptions()` to list all accounts.
- **Caching:** GET requests are cached in-memory with per-endpoint TTLs configured in `CACHE_TTLS` (webull_client.py). Static metadata: 1 hour. Historical bars: 5 min. Account state: 60s. Orders: 30s. Live quotes: not cached.

## Response Processing

All API responses pass through `process(key, data)` in `response_filters.py`, which applies two stages:

1. **Field filtering (`FIELD_FILTERS`)** — maps key to a set of top-level keys to keep. `None` means passthrough. Only used for Webull endpoints currently.
2. **Transformation (`TRANSFORMERS`)** — maps key to a function that converts data into a **markdown table string**. This is critical for reducing hallucinations — the model parses tables far more reliably than nested JSON.

Keys use the API path for Webull endpoints (e.g. `"/openapi/assets/balance"`) and a namespaced logical key for external providers (e.g. `"tradier:chain"`, `"finnhub:company-news"`).

Helper functions in `response_filters.py`:
- `_kv_table(data)` — for single-object responses (e.g. company profile → two-column Field/Value table)
- `_list_table(items, columns)` — for list responses (e.g. option chain → one row per contract)
- `_md_table(headers, rows)` — low-level builder for custom layouts
- `_fmt_number(val, decimals)` — format numbers with commas and fixed decimals
- `_fmt_large(val)` — format large numbers as B/M/K (e.g. 2.5T, 150.3B, 42.1M)
- `_unix_to_date(ts)` — convert unix timestamps to `YYYY-MM-DD HH:MM`

## Conventions

- All MCP tools are defined in `server.py` and delegate to client methods
- Each provider has its own client file with a simple HTTP wrapper
- Client helper functions in server.py (`_webull()`, `_tradier()`, etc.) extract the client from lifespan context and raise a clear error if the provider isn't configured
- Ruff rules: E, F, I (isort), UP (pyupgrade). Line length: 100.

### Adding a New API Provider

Follow these steps to integrate a new data provider:

1. **Config** (`config.py`): Add a frozen dataclass for the provider's credentials (e.g. `NewProviderConfig`). Add it as an optional field on `AppConfig`. Parse it from `~/.tradingrc` in `load_config()` if the section exists.

2. **Client** (`newprovider_client.py`): Create a client class with:
   - `__init__` taking the config dataclass, creating an `httpx.Client` and a `TTLCache` (from `cache.py`)
   - A `_get()` method that handles auth (add API key to params or headers), caching (check/store with `cache_key`), and calls `process()` from `response_filters.py` on the result
   - One public method per API endpoint, each passing a logical key to `process()` (e.g. `"provider:endpoint-name"`)
   - A module-level `CACHE_TTLS` dict mapping cache keys to TTL in seconds. Use 0 or omit for no caching. Exclude API keys/tokens from cache keys.

3. **Response transformers** (`response_filters.py`): For each endpoint, add a transformer function that converts the raw response to a markdown table string using the helper functions (`_kv_table`, `_list_table`, `_fmt_number`, `_fmt_large`). Register it in the `TRANSFORMERS` dict with the same logical key used in the client.

4. **Server** (`server.py`):
   - Import the client class and add a `_newprovider(ctx)` helper that extracts it from lifespan context (raising `RuntimeError` with setup instructions if not configured)
   - In the `lifespan()` function, create the client if the config section exists
   - Add `@mcp.tool()` functions with detailed docstrings covering: what the tool returns, what each parameter means with valid values, where to get required IDs, and a note that it requires the provider's config section

5. **Docs** (`CLAUDE.md`): Add the provider to the Architecture file tree, Provider Roles table, and Credentials example.
