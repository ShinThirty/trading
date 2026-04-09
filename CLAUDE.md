# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@.claude/webull-api-docs.md

## Project Overview

uv workspace monorepo with three packages:

1. **trading-clients** — Shared API clients and endpoint definitions for Webull, Tradier, Finnhub, FMP, FRED, and Alpha Vantage. Pure library — no server or Lambda dependencies.
2. **trading-mcp** — MCP server that exposes brokerage operations, option chains, fundamentals, news, economic data, and sentiment as MCP tools. Depends on trading-clients + mcp[cli].
3. **option-monitor** — AWS Lambda service that monitors short option positions across Webull accounts, evaluates DTE-adjusted strike proximity thresholds, and sends Discord alerts. Depends on trading-clients + boto3 (no MCP dependency).

## Commands

```bash
uv sync --all-packages             # Install/sync all workspace packages
uv run trading-mcp                 # Start the MCP server (stdio transport)
uv run ruff check packages/        # Lint all packages
uv run ruff format packages/       # Format all packages
uv run ty check packages/trading-clients/src/    # Type check trading-clients
uv run ty check packages/trading-mcp/src/        # Type check trading-mcp
uv run ty check packages/option-monitor/src/     # Type check option-monitor
uv run python packages/option-monitor/scripts/invoke_local.py --skip-clock  # Test monitor locally
```

To add to Claude Code: `claude mcp add trading-mcp -- uv run trading-mcp`

## Architecture

```
trading-mcp/                             # monorepo root (uv workspace)
├── pyproject.toml                       # workspace definition + shared ruff config
├── CLAUDE.md
├── packages/
│   ├── trading-clients/                 # shared API client library
│   │   ├── pyproject.toml               # depends on: httpx[http2]
│   │   └── src/trading_clients/
│   │       ├── endpoint.py              # Endpoint dataclass + BaseClient (get/post/put/delete)
│   │       ├── table_helpers.py         # Markdown table builders
│   │       ├── config.py               # Loads credentials from ~/.tradingrc
│   │       ├── cache.py                 # In-memory TTL cache
│   │       ├── rate_limit.py            # Token bucket rate limiter
│   │       ├── webull_client.py         # HMAC-SHA1 auth, token mgmt
│   │       ├── tradier_client.py        # Bearer token auth
│   │       ├── finnhub_client.py        # API key auth
│   │       ├── fmp_client.py            # API key auth
│   │       ├── fred_client.py           # API key auth
│   │       ├── alphavantage_client.py   # API key auth
│   │       └── endpoints/               # Typed request/response models + Endpoint defs
│   │           ├── webull.py            # 11 endpoints (account, orders, instruments)
│   │           ├── tradier.py           # 19 endpoints (options, quotes, account, orders)
│   │           ├── finnhub.py           # 11 endpoints (news, earnings, financials)
│   │           ├── fmp.py               # 7 endpoints (financial statements, profiles)
│   │           ├── fred.py              # 4 endpoints (economic data series)
│   │           └── alphavantage.py      # 2 endpoints (sentiment, movers)
│   ├── trading-mcp/                     # MCP server (thin shell)
│   │   ├── pyproject.toml               # depends on: trading-clients + mcp[cli]
│   │   └── src/trading_mcp/
│   │       └── server.py                # FastMCP server, tool registration, lifespan
│   └── option-monitor/                  # Lambda monitoring service
│       ├── pyproject.toml               # depends on: trading-clients + boto3
│       ├── scripts/
│       │   └── invoke_local.py          # Local testing with ~/.tradingrc
│       └── src/option_monitor/
│           ├── handler.py               # Lambda entry point
│           ├── config.py                # MonitorConfig (Secrets Manager or ~/.tradingrc)
│           ├── discord.py               # Webhook notifications with rich embeds
│           └── monitor/
│               ├── positions.py         # Parse Webull positions → ShortOptionLeg
│               └── thresholds.py        # DTE-based proximity evaluation
├── terraform/                           # AWS infrastructure (Phase 2)
└── tests/                               # Test suite (Phase 2)
```

### Dependency Graph

```
trading-clients (httpx[http2])
  ├── trading-mcp (+ mcp[cli])
  └── option-monitor (+ boto3)
```

### Data Flow — MCP Server

```
MCP tool call (server.py)
  → creates typed Request (e.g. PlaceOrderRequest)
  → calls client.get/post/put/delete(ENDPOINT, request)
    → BaseClient resolves path templates (PathRequest)
    → client._request() handles auth, HTTP, caching, rate limiting
    → BaseClient._decode() extracts + transforms via response model
  → returns markdown string to FastMCP
```

### Data Flow — Option Monitor

```
EventBridge (cron, Mon-Fri 13:30-20:00 UTC)
  → Lambda handler
    → TradierClient.get(CLOCK) — market open check
    → WebullClient.get(ACCOUNT_LIST) — discover accounts
    → WebullClient.get(POSITIONS) — short option legs per account
    → TradierClient.get(QUOTES) — batch underlying prices
    → Threshold evaluation (DTE-adjusted proximity)
    → Discord webhook (warning/critical embeds)
```

### BaseClient Methods

- `get(endpoint, request) -> ResponseModel` — returns typed response model
- `post/put/delete(endpoint, request) -> ResponseModel` — returns typed response model
- `close()` — closes the underlying HTTP client

### Layered Design (inspired by Sarama)

1. **Request mixins** (`endpoint.py`): `PathRequest`, `ParamsRequest`, `BodyRequest` — the three ways data is sent in HTTP. Request models compose these to express their contract.
2. **Endpoint definitions** (`endpoints/*.py`): Each endpoint bundles its path, cache TTL, rate key, response model, and optional extract function. Response models have `from_response()` + `to_markdown()`.
3. **Client transport** (`*_client.py`): Thin HTTP wrappers. Each extends `BaseClient` and implements `_request()` with provider-specific auth.
4. **Server tools** (`server.py`): MCP tool functions create typed requests and call `client.get/post(ENDPOINT, request)`.

### Provider Roles

| Provider | Role | Auth |
|---|---|---|
| **Webull** (required) | Brokerage: account, orders, positions | HMAC-SHA1 + token |
| **Tradier** | Option chains, greeks, IV, quotes, account | Bearer token |
| **Finnhub** | News, earnings calendar, key metrics | API key |
| **FMP** | Financial statements, company profiles | API key |
| **FRED** | Macroeconomic data (CPI, GDP, VIX, rates) | API key |
| **Alpha Vantage** | News sentiment, top market movers | API key |

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

[discord]
webhook_url = <discord_webhook_url_for_option_monitor>
```

## Webull API (v2)

All Webull endpoints use the v2 API (`x-version: v2` header). Stock and option orders are unified into a single endpoint.

- **Host:** `api.webull.com` (all endpoints)
- **Auth:** HMAC-SHA1 signature over sorted headers + URI + query params + MD5(body). Headers: `x-app-key`, `x-timestamp`, `x-signature-version`, `x-signature-algorithm`, `x-signature-nonce`, `x-signature`. Plus `x-version: v2` and `x-access-token` (not in signing).
- **Token lifecycle:** Tokens are created via `POST /openapi/auth/token/create`. Default expiry: 15 days of inactivity. New tokens have `PENDING` status and must be verified in the Webull App (Menu > Messages > OpenAPI Notifications). On 401, the client auto-creates a new token, saves to `~/.tradingrc`, and raises with verification instructions.
- **Unified order endpoint:** Stock and option orders both use `/openapi/trade/order/place`. Options use `instrument_type: "OPTION"` + `legs[]` array. Orders use `symbol` directly (no `instrument_id` lookup needed).
- **v2 endpoint paths:** All endpoints use `/openapi/` prefix: `/openapi/account/list`, `/openapi/assets/balance`, `/openapi/assets/positions`, `/openapi/trade/order/*`, `/openapi/instrument/stock/list`.
- **HTTP/2:** The httpx client is configured with `http2=True`.
- **Multi-account:** All account-specific methods accept an optional `account_id` parameter. Resolution order: explicit param > config default > error with instructions. Use `get_app_subscriptions()` to list all accounts.

## Conventions

- All MCP tools are defined in `server.py` and delegate to `client.get/post(ENDPOINT, request)`
- Each provider has its own client file (thin transport) and endpoint file (typed models) in trading-clients
- Client helper functions in server.py (`_webull()`, `_tradier()`, etc.) extract the client from lifespan context and raise a clear error if the provider isn't configured
- MCP server calls `.to_markdown()` on response models; option-monitor accesses typed fields directly
- Ruff rules: E, F, I (isort), UP (pyupgrade). Line length: 100.

### Adding a New API Provider

1. **Config** (`trading-clients/config.py`): Add a frozen dataclass for the provider's credentials. Add it as an optional field on `AppConfig`. Parse it from `~/.tradingrc` in `load_config()`.

2. **Endpoints** (`trading-clients/endpoints/newprovider.py`): Define for each endpoint:
   - A **request model** (dataclass extending `ParamsRequest`, `BodyRequest`, and/or `PathRequest`)
   - A **response model** (dataclass with `from_response(data)` classmethod and `to_markdown()` method)
   - An **Endpoint** constant with path, cache_ttl, rate_key, response_model, and optional extract function

3. **Client** (`trading-clients/newprovider_client.py`): Create a class extending `BaseClient` with:
   - `__init__` taking the config, creating `httpx.Client`, `TTLCache`, `RateLimiter`
   - `_request()` method handling auth (API key in params/headers), caching, rate limiting

4. **Server** (`trading-mcp/server.py`):
   - Import endpoints and add `_newprovider(ctx)` helper
   - In `lifespan()`, create the client if config section exists
   - Add `@mcp.tool()` functions that create typed requests and call `client.get(ENDPOINT, request)`

5. **Docs** (`CLAUDE.md`): Add the provider to the Architecture file tree and Provider Roles table.
