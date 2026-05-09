# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@docs/decision-framework.md

## Project Overview

uv workspace monorepo with three packages:

1. **trading-clients** — Shared API clients and endpoint definitions for Webull, Tradier, Finnhub, FMP, FRED, and Alpha Vantage. Pure library — no server or Lambda dependencies.
2. **trading-mcp** — MCP server that exposes brokerage operations, option chains, fundamentals, news, economic data, and sentiment as MCP tools. Depends on trading-clients + mcp[cli].
3. **option-monitor** — AWS Lambda service that monitors short option positions across Webull accounts, evaluates DTE-adjusted strike proximity thresholds, and sends Discord alerts. Depends on trading-clients + boto3 (no MCP dependency).

## Commands

```bash
uv sync --all-packages             # Install/sync all workspace packages
uv run --package trading-mcp trading-mcp  # Start the MCP server (stdio transport)
uv run ruff check packages/        # Lint all packages
uv run ruff format packages/       # Format all packages
uv run ty check packages/trading-clients/src/    # Type check trading-clients
uv run ty check packages/trading-mcp/src/        # Type check trading-mcp
uv run ty check packages/option-monitor/src/     # Type check option-monitor
uv run python packages/option-monitor/scripts/invoke_local.py --skip-clock  # Test monitor locally
```

To add to Claude Code: `claude mcp add trading-mcp -- uv run --package trading-mcp trading-mcp`

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
│   │       ├── tastytrade_client.py     # OAuth2 refresh token auth
│   │       ├── fool_client.py           # No auth (Motley Fool sitemap+page scrape)
│   │       ├── edgar_client.py          # No auth, identifies via User-Agent (SEC EDGAR)
│   │       ├── bls_client.py            # No auth, identifies via User-Agent (BLS press releases)
│   │       ├── bea_client.py            # No auth, identifies via User-Agent (BEA press releases)
│   │       ├── fed_client.py            # No auth, identifies via User-Agent (FOMC statements)
│   │       ├── cftc_client.py           # No auth (CFTC publicreporting Socrata JSON)
│   │       ├── sentiment_client.py      # Playwright-based scraper (CBOE p/c, AAII, NAAIM)
│   │       └── endpoints/               # Typed request/response models + Endpoint defs
│   │           ├── webull.py            # 11 endpoints (account, orders, instruments)
│   │           ├── tradier.py           # 19 endpoints (options, quotes, account, orders)
│   │           ├── finnhub.py           # 11 endpoints (news, earnings, financials)
│   │           ├── fmp.py               # 8 endpoints (financial statements, profiles, sector perf)
│   │           ├── fred.py              # 4 endpoints (economic data series)
│   │           ├── alphavantage.py      # 2 endpoints (sentiment, movers)
│   │           ├── tastytrade.py        # 5 endpoints (IV metrics, backtesting, watchlists, dividends)
│   │           ├── fool.py              # 2 endpoints (monthly sitemap, transcript page)
│   │           ├── edgar.py             # 4 endpoints (ticker map, submissions, filing index, doc)
│   │           ├── bls.py               # 2 endpoints (Employment Situation, CPI press releases)
│   │           ├── bea.py               # 2 endpoints (current releases index, PCE press release)
│   │           ├── fed.py               # 2 endpoints (FOMC calendar, FOMC statement)
│   │           ├── cftc.py              # 3 endpoints (TFF / Disaggregated / Legacy COT reports)
│   │           ├── sentiment.py         # 3 endpoints (CBOE equity p/c, AAII, NAAIM)
│   │           └── yahoo.py             # Response models for Yahoo Finance (via yfinance)
│   ├── trading-mcp/                     # MCP server (composed via fastmcp mount)
│   │   ├── pyproject.toml               # depends on: trading-clients + fastmcp + yfinance
│   │   └── src/trading_mcp/
│   │       ├── server.py                # Lifespan, parent FastMCP, mount() calls
│   │       ├── helpers.py               # Client extractors, shared helpers (_retry, etc.)
│   │       ├── yfinance_helper.py       # Shared yfinance namespace (_yfc) for fundamentals + screens
│   │       ├── db/                      # SQLite database layer (~/.trading/trading.db)
│   │       │   ├── __init__.py          # Connection, shared utilities
│   │       │   ├── pipeline.py          # Pipeline table schema, enums, async CRUD
│   │       │   ├── rolls.py             # Rolls table schema, enums, async CRUD
│   │       │   └── decisions.py         # Option decisions table schema, enums, async CRUD
│   │       └── tools/                   # Subdomain-organized tool modules
│   │           ├── account.py           # Balances, positions, instruments, portfolio aggregates
│   │           ├── orders.py            # Place/preview/replace/cancel orders, order history
│   │           ├── quotes.py            # Stock/option quotes, history, intraday, technicals, clock
│   │           ├── options.py           # Chains, expected move, strategy/roll analysis,
│   │           │                        #   IV metrics, comparators, projection grid, CC overlay
│   │           ├── fundamentals.py      # Financials, profile, EPS estimates, ownership,
│   │           │                        #   insider activity, informed-flow scanner
│   │           ├── calendar.py          # Earnings, dividends, upcoming economic releases
│   │           ├── macro.py             # FRED series, sector performance, market regime
│   │           ├── news.py              # Company/market news, sentiment, Reddit, YouTube
│   │           ├── screens.py           # Yahoo screens, top movers, watchlists, short stats
│   │           ├── crypto.py            # Crypto quotes/history, BTC entry signals
│   │           ├── cn_market.py         # China A-share quotes, financials, fund flow (AKShare)
│   │           ├── cftc.py              # CFTC COT positioning (single contract + extremes scan)
│   │           ├── backtest.py          # TastyTrade option strategy backtests
│   │           ├── earnings.py          # Earnings call transcript (Fool) + press release (EDGAR 8-K)
│   │           ├── signals.py           # Conviction, sizing, hedge, entry signals
│   │           ├── pipeline.py          # Pipeline ticker CRUD
│   │           ├── pipeline_catalysts.py # Pipeline catalyst CRUD
│   │           ├── rolls.py             # Option roll tracking CRUD
│   │           └── decisions.py         # Option decision tracking CRUD
│   └── option-monitor/                  # Lambda monitoring service
│       ├── pyproject.toml               # depends on: trading-clients + boto3 + pynacl
│       ├── Makefile                     # deploy/destroy/credentials/test automation
│       ├── terraform/                   # AWS infrastructure (self-contained)
│       │   ├── main.tf                  # Lambda, DynamoDB, EventBridge, IAM, SSM
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── scripts/
│       │   ├── invoke_local.py          # Local testing with ~/.tradingrc
│       │   ├── build_lambda.sh          # Build Lambda deployment ZIP
│       │   └── register_commands.py     # Register Discord slash commands
│       └── src/option_monitor/
│           ├── handler.py               # Lambda entry point
│           ├── config.py                # MonitorConfig (SSM Parameter Store or ~/.tradingrc)
│           ├── discord.py               # Bot messaging with rich embeds + mute buttons
│           ├── state.py                 # DynamoDB alert state read/write
│           ├── interaction.py           # Discord interaction handler (buttons + slash commands)
│           └── monitor/
│               ├── positions.py         # Parse Webull positions → ShortOptionLeg
│               ├── thresholds.py        # DTE-based proximity evaluation
│               └── alerts.py            # PagerDuty-inspired alert state machine
└── tests/                               # Test suite (Phase 2)
```

### Dependency Graph

```
trading-clients (httpx[http2])
  ├── trading-mcp (+ fastmcp + yfinance)
  └── option-monitor (+ boto3)
```

### Data Flow — MCP Server

```
MCP tool call (tools/*.py)
  → creates typed Request (e.g. PlaceOrderRequest)
  → calls client.get/post/put/delete(ENDPOINT, request)
    → BaseClient resolves path templates (PathRequest)
    → client._request() handles auth, HTTP, caching, rate limiting
    → BaseClient._decode() extracts + transforms via response model
  → returns formatted string via .to_output() to FastMCP
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
    → Alert state machine (dedup/cooldown/muting via DynamoDB)
    → Discord bot messaging (warning/critical embeds + mute buttons)
```

### BaseClient Methods

- `get(endpoint, request) -> ResponseModel` — returns typed response model
- `post/put/delete(endpoint, request) -> ResponseModel` — returns typed response model
- `close()` — closes the underlying HTTP client

### Layered Design (inspired by Sarama)

1. **Request mixins** (`endpoint.py`): `PathRequest`, `ParamsRequest`, `BodyRequest` — the three ways data is sent in HTTP. Request models compose these to express their contract.
2. **Endpoint definitions** (`endpoints/*.py`): Each endpoint bundles its path, cache TTL, rate key, response model, optional extract function, and optional `base_url` override. Response models have `from_response()` + `to_output()`.
3. **Client transport** (`*_client.py`): Thin HTTP wrappers. Each extends `BaseClient` and implements `_request()` with provider-specific auth.
4. **Server tools** (`tools/*.py`): MCP tool functions create typed requests and call `client.get/post(ENDPOINT, request)`.

### Provider Roles

| Provider | Role | Auth |
|---|---|---|
| **Webull** (required) | Brokerage: account, orders, positions | HMAC-SHA1 + token |
| **Tradier** | Option chains, greeks, IV, quotes, account | Bearer token |
| **Finnhub** | News, earnings calendar, key metrics | API key |
| **FMP** | Financial statements, company profiles, sector performance | API key |
| **FRED** | Macroeconomic data (CPI, GDP, VIX, rates) | API key |
| **Alpha Vantage** | News sentiment, top market movers | API key |
| **TastyTrade** | IV rank/percentile, backtesting, watchlists, dividends | OAuth2 refresh token |
| **Yahoo Finance** | Stock screener, institutional ownership | None (via yfinance) |
| **Motley Fool** | Earnings call transcripts (scraped) | None |
| **SEC EDGAR** | 8-K earnings press releases (Item 2.02 Exhibit 99.x) | None (User-Agent only) |
| **BLS** | Employment Situation / CPI press release narrative | None (User-Agent only) |
| **BEA** | Personal Income and Outlays (PCE) press release narrative | None (User-Agent only) |
| **Federal Reserve** | FOMC statements (latest + prior for language diff) | None (User-Agent only) |
| **CFTC** | Commitments of Traders (COT) — speculator positioning across SPX, NDX, VIX, 10Y, Gold, WTI | None (Socrata JSON) |
| **CBOE** | Equity put/call ratio (daily) | None (Playwright, realistic browser context) |
| **AAII** | Investor sentiment survey bull/neutral/bear (weekly) | None (Playwright, realistic browser context) |
| **NAAIM** | Active manager equity exposure index (weekly) | None (Playwright, realistic browser context) |

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

[tastytrade]
client_secret = <your_oauth_client_secret>
refresh_token = <your_oauth_refresh_token>

[discord]
webhook_url = <discord_webhook_url_for_option_monitor>
```

## Google Workspace

Use `xmxu00@gmail.com` as the `user_google_email` for all Google Workspace MCP tools (Drive, Docs, Sheets, Calendar).

## Webull API (v2)

All Webull endpoints use the v2 API (`x-version: v2` header). Stock and option orders are unified into a single endpoint.

- **Host:** `api.webull.com` (all endpoints)
- **Auth:** HMAC-SHA1 signature over sorted headers + URI + query params + MD5(body). Headers: `x-app-key`, `x-timestamp`, `x-signature-version`, `x-signature-algorithm`, `x-signature-nonce`, `x-signature`. Plus `x-version: v2` and `x-access-token` (not in signing).
- **Token lifecycle:** Tokens are created via `POST /openapi/auth/token/create`. Default expiry: 15 days of inactivity. New tokens have `PENDING` status and must be verified in the Webull App (Menu > Messages > OpenAPI Notifications). On 401 errors, use the `refresh_webull_token` MCP tool to create a new token and follow the verification instructions.
- **Unified order endpoint:** Stock and option orders both use `/openapi/trade/order/place`. Options use `instrument_type: "OPTION"` + `legs[]` array. Orders use `symbol` directly (no `instrument_id` lookup needed).
- **v2 endpoint paths:** All endpoints use `/openapi/` prefix: `/openapi/account/list`, `/openapi/assets/balance`, `/openapi/assets/positions`, `/openapi/trade/order/*`, `/openapi/instrument/stock/list`.
- **HTTP/2:** The httpx client is configured with `http2=True`.
- **Multi-account:** All account-specific methods accept an optional `account_id` parameter. Resolution order: explicit param > config default > error with instructions. Use `get_app_subscriptions()` to list all accounts.

## Conventions

- MCP tools are split by domain in `tools/*.py` and mounted to the parent server via `fastmcp.mount()`
- Each provider has its own client file (thin transport) and endpoint file (typed models) in trading-clients
- Client helper functions in `helpers.py` (`_webull()`, `_tradier()`, etc.) extract the client from `ctx.lifespan_context` and raise a clear error if the provider isn't configured
- MCP server calls `.to_output()` on response models; option-monitor accesses typed fields directly
- Ruff rules: E, F, I (isort), UP (pyupgrade). Line length: 100.
- **Never do manual math.** Always delegate calculations (P&L, PEG, returns, Greeks, position sizing, etc.) to MCP tools. If no suitable MCP tool exists, flag it to the user instead of computing by hand — manual math is error-prone and unverifiable.

### Output Format Convention

Response models implement `to_output()` (not `to_markdown()`) to produce LLM-friendly text. Choose the format based on data shape:

- **Markdown table** (`list_table`/`kv_table`): Multi-column comparison data where column alignment aids readability (option chains, quotes, financial statements, IV metrics, earnings, orders, positions).
- **CSV / inline**: Single-column lists or simple key-value pairs (expirations, strikes, symbols, peers, FRED observations, dividend dates, watchlists).
- **Custom text**: Complex multi-section responses (backtest results, top movers).

Rule of thumb: if it has 3+ columns that benefit from side-by-side comparison, use a table. Otherwise use comma-separated inline format to minimize LLM context usage.

### Adding a New API Provider

1. **Config** (`trading-clients/config.py`): Add a frozen dataclass for the provider's credentials. Add it as an optional field on `AppConfig`. Parse it from `~/.tradingrc` in `load_config()`.

2. **Endpoints** (`trading-clients/endpoints/newprovider.py`): Define for each endpoint:
   - A **request model** (dataclass extending `ParamsRequest`, `BodyRequest`, and/or `PathRequest`)
   - A **response model** (dataclass with `from_response(data)` classmethod and `to_output()` method)
   - An **Endpoint** constant with path, cache_ttl, rate_key, response_model, optional extract function, and optional base_url

3. **Client** (`trading-clients/newprovider_client.py`): Create a class extending `BaseClient` with:
   - `__init__` taking the config, creating `httpx.Client`, `TTLCache`, `RateLimiter`
   - `_request()` method handling auth (API key in params/headers), caching, rate limiting

4. **Helpers** (`trading-mcp/helpers.py`): Add `_newprovider(ctx)` extractor function.

5. **Tools** (`trading-mcp/tools/newprovider.py`):
   - Create a `FastMCP` subserver instance
   - Add `@mcp.tool()` functions that create typed requests and call `client.get(ENDPOINT, request)`

6. **Server** (`trading-mcp/server.py`):
   - In `lifespan()`, create the client if config section exists
   - Mount the new subserver: `mcp.mount(newprovider_mcp)`

7. **Docs** (`CLAUDE.md`): Add the provider to the Architecture file tree and Provider Roles table.
