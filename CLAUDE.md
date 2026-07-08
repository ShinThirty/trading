# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@docs/decision-framework.md

## Project Overview

uv workspace monorepo with four packages:

1. **trading-clients** — Shared API clients, endpoint definitions, and pure-computation helpers for Webull, Tradier, Finnhub, FMP, FRED, Alpha Vantage, Reddit, and many more providers. Also contains standalone math modules (BSM pricing, options analytics, technical indicators, regime classification). Pure library — no server or Lambda dependencies.
2. **trading-mcp** — MCP server that exposes brokerage operations, option chains, fundamentals, news, economic data, and sentiment as MCP tools. Depends on trading-clients + mcp[cli]. Publishes the active pipeline universe to S3 on every mutation so Lambda watchers can filter to pipeline names.
3. **trading-alerts** — AWS Lambda fleet of 14 trigger-based market/macro alert watchers. Per-watcher EventBridge schedules invoke a single dispatcher Lambda; each watcher emits AlertEvents that post to Discord with mute buttons + DynamoDB-backed dedup. Depends on trading-clients + boto3 + pynacl (no MCP dependency).
4. **trading-scalper** — Local **paper** entry-detector for intraday SPY/QQQ options scalps (see [docs/scalper-automation.md](docs/scalper-automation.md)). Pivoted 2026-06-12 from the old assist-only stop-enforcer once Webull desktop's native option bracket (1st-Trigger Stop + OCO stop/target) made the auto-stop redundant. New job: (1) **prompt** when the underlying triggers a blessed session-plan level — a *confirmed* setup, not a bare touch: `SetupDetector` + `Notifier` are **GEX-regime-aware**, branching on each level's `mode` (`fade` = touch-and-reject at a gamma wall in +GEX; `break` = cross-with-follow-through in −GEX), gated on lean (by trade *direction*) and on the tape agreeing with the option's call/put, with a spread gate on the paper fill. Two further modes render the verdict a bare `break` can't — `reversal` (a *failed* break: cross-out that snaps back inside → trade the snap-back, opposite the attempt) and `retest` (a *confirmed* break that pulls back to the wall and resumes → the patient continuation) — driven by a per-wall `BreakoutTracker` (`breakout.py`) and gated on **geometry + lean only, never tape** (a wall = a `reversal` row + a `retest` row at one price+side; the tracker is level-source-agnostic so ORB/VWAP/stop-cluster sources plug in later). A `break` level **arms** only after the detector has *witnessed* price on the pre-break side, and a stream-gap guard (`gap_s`) drops all arming (and the verdict trackers' cross-timers) on a suspend/disconnect — so a daemon that slept through the actual cross can't wake up and fire at the extended top (downtime-safe break entries). The plan's walls + zero-gamma flip come from `get_gamma_profile` (signed per-strike dollar gamma off the Tradier chain; `trading_clients.options.gamma_exposure_profile`); (2) on every confirmed prompt **auto-execute the same option bracket** — entry + OCO stop-loss/take-profit — in an in-memory `PaperBroker.place_bracket`; (3) **persist** fills + a realized-P&L summary (`PaperPersister` → `~/.trading/scalp/paper/{date}.jsonl` + `-summary.json`) so the detector's track record is reviewable. Paper-only — there is no live-order path; the old `RiskReducingOnly` invariant is gone (the daemon now *opens*), replaced by a zero-real-capital safety story. Two ports: `MarketDataFeed` (Tradier streaming) + `BrokerExecution` (`PaperBroker`). The session plan is a dated, hand-editable YAML naming an option `contract` + `mode` (fade/break/reversal/retest) per level (levels/lean/mode hot-reload; a new contract mid-session needs a restart). `cli.build_session` is the composition root behind the `trading-scalper` entry point; `--demo-setup CONTRACT[:QTY[:PRICE]]` runs the loop offline. Removed in the pivot: `AutoStop`/`PositionWatcher`, `DisciplineEngine`, the `RiskReducingOnly` guard, and the live exit-only `WebullBroker` (recoverable from git if live-autonomy is revisited). Roadmap: Tastytrade DXLink greeks feed (the one real data upgrade); autonomous live entry only after a long paper track record. Depends on trading-clients[streaming] + pyyaml.

## Commands

```bash
uv sync --all-packages             # Install/sync all workspace packages
uv run --package trading-mcp trading-mcp  # Start the MCP server (stdio transport)
uv run ruff check packages/        # Lint all packages
uv run ruff format packages/       # Format all packages
uv run ty check packages/trading-clients/src/    # Type check trading-clients
uv run ty check packages/trading-mcp/src/        # Type check trading-mcp
uv run ty check packages/trading-alerts/src/     # Type check trading-alerts
uv run python packages/trading-alerts/scripts/invoke_local.py --list             # List wired watchers
uv run python packages/trading-alerts/scripts/invoke_local.py --trigger naaim    # Run a watcher locally
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
│   │       ├── tradier_stream_client.py # Tradier streaming transport (session create + WebSocket + pure wire parsing); production-only. [streaming] extra
│   │       ├── market_stream.py         # Provider-neutral streaming value types (Quote/Trade/TimeSale) — what any feed emits
│   │       ├── finnhub_client.py        # API key auth
│   │       ├── fmp_client.py            # API key auth
│   │       ├── fred_client.py           # API key auth
│   │       ├── alphavantage_client.py   # API key auth
│   │       ├── eia_client.py            # API key auth (EIA Open Data v2)
│   │       ├── factset_client.py        # No auth, identifies via User-Agent (FactSet Earnings Insight PDF; pdfplumber)
│   │       ├── tastytrade_client.py     # OAuth2 refresh token auth
│   │       ├── fool_client.py           # No auth (Motley Fool sitemap+page scrape)
│   │       ├── morningstar_client.py    # Playwright-based scraper (earnings transcripts; AWS WAF bypass via webdriver mask); takes PlaywrightHost
│   │       ├── edgar_client.py          # No auth, identifies via User-Agent (SEC EDGAR)
│   │       ├── bls_client.py            # No auth, identifies via User-Agent (BLS press releases)
│   │       ├── bea_client.py            # No auth, identifies via User-Agent (BEA press releases)
│   │       ├── fed_client.py            # No auth, identifies via User-Agent (FOMC statements)
│   │       ├── cftc_client.py           # No auth (CFTC publicreporting Socrata JSON)
│   │       ├── polymarket_client.py     # No auth (Polymarket gamma-api event/market data)
│   │       ├── kalshi_client.py         # No auth (Kalshi elections-api event/market data)
│   │       ├── twse_client.py           # No auth (TWSE OpenAPI t187ap05_L listed-company monthly revenue feed)
│   │       ├── treasury_client.py       # No auth, identifies via User-Agent (Treasury QRA Policy Statement)
│   │       ├── freightos_client.py      # No auth, identifies via User-Agent (Freightos Baltic Index lane pages)
│   │       ├── portwatch_client.py      # No auth, identifies via User-Agent (IMF PortWatch ArcGIS chokepoint data)
│   │       ├── beige_book_client.py     # No auth, identifies via User-Agent (Fed Beige Book)
│   │       ├── squeeze_metrics_client.py # No auth (SqueezeMetrics public DIX/GEX CSV)
│   │       ├── naaim_client.py          # No auth (NAAIM since-inception XLSX history); Cloudflare Bot Mgmt 403s httpx, so routes discovery+download through the shared Playwright browser context when a host is present (httpx fallback for Lambda)
│   │       ├── reddit_client.py         # Reddit JSON API (search, subreddit, post); httpx fetch + Playwright-minted loid cookie (anonymous .json is 403-blocked); takes PlaywrightHost
│   │       ├── playwright_host.py       # Shared Chromium process (one Browser, many isolated Contexts) used by all Playwright-backed clients
│   │       ├── sentiment_client.py      # Playwright-based scraper (CBOE p/c, AAII); takes PlaywrightHost
│   │       ├── bsm.py                   # Black-Scholes-Merton option pricing (pure math, no I/O)
│   │       ├── btc_regime.py            # BTC macro regime classification (pure functions)
│   │       ├── indicators.py            # Technical analysis indicators on OHLCV bars (pure functions)
│   │       ├── options.py               # Options analytics: expected move, HV, strategy P&L (pure functions)
│   │       ├── options_multi_exp.py     # Multi-expiration strategy analysis: calendars, diagonals, PMCC (uses BSM for far leg)
│   │       ├── portfolio.py             # Multi-account portfolio aggregation (Webull + Tradier + TastyTrade APIs + Fidelity CSV)
│   │       ├── regime.py                # Market regime classification from pre-fetched data (pure functions)
│   │       └── endpoints/               # Typed request/response models + Endpoint defs
│   │           ├── webull.py            # 11 endpoints (account, orders, instruments)
│   │           ├── tradier.py           # 13 endpoints (options, quotes + read-only account: profile, balances, positions, orders)
│   │           ├── finnhub.py           # 11 endpoints (news, earnings, financials)
│   │           ├── fmp.py               # 8 endpoints (financial statements, profiles, sector perf)
│   │           ├── fred.py              # 4 endpoints (economic data series)
│   │           ├── alphavantage.py      # 2 endpoints (sentiment, movers)
│   │           ├── eia.py               # 1 endpoint (single-series fetch by series_id; v2 /seriesid)
│   │           ├── factset.py           # FactsetEarningsInsightResponse — narrative + parsed S&P 500 metrics
│   │           ├── tastytrade.py        # 10 endpoints (IV metrics, backtesting, watchlists, dividends + read-only account: accounts, balances, positions, orders)
│   │           ├── fool.py              # 2 endpoints (monthly sitemap, transcript page)
│   │           ├── morningstar.py       # 1 endpoint (earnings call transcript by exchange + ticker)
│   │           ├── edgar.py             # 5 endpoints (ticker map, submissions, filing index, doc, Form 4)
│   │           │                        #   + 10-K/10-Q section anchors, risk-factor splitter & Jaccard diff
│   │           │                        #   + S-1/F-1/424B catalog-driven section extractor (line-anchored,
│   │           │                        #   last-match-wins; handles both domestic + foreign-issuer prospectuses)
│   │           ├── bls.py               # 2 endpoints (Employment Situation, CPI press releases)
│   │           ├── bea.py               # 2 endpoints (current releases index, PCE press release)
│   │           ├── fed.py               # 3 endpoints (FOMC calendar, FOMC statement, FOMC minutes section-split)
│   │           ├── cftc.py              # 3 endpoints (TFF / Disaggregated / Legacy COT reports)
│   │           ├── polymarket.py        # 2 endpoints (event by slug, list events by tag) + shared models
│   │           ├── kalshi.py            # 1 endpoint (event by ticker with nested markets)
│   │           ├── twse.py              # 1 endpoint (listed-company monthly revenue feed, JSON)
│   │           ├── treasury.py          # 3 endpoints (QRA most-recent index, archive index, statement page)
│   │           ├── freight.py           # 2 endpoints (Freightos FBX lane page + IMF PortWatch chokepoints query) with FBX_LANES + CHOKEPOINTS catalogs
│   │           ├── beige_book.py        # 2 endpoints (release index, National Summary by period)
│   │           ├── squeeze_metrics.py   # 1 endpoint (DIX/GEX daily history CSV)
│   │           ├── naaim.py             # NaaimHistoryResponse (XLSX-parsed weekly history with z-score)
│   │           ├── prediction_market.py # Shared PredictionEvent / PredictionOutcome types
│   │           ├── reddit.py            # 3 endpoints (search, subreddit listing, post + comments)
│   │           ├── sentiment.py         # 3 endpoints (CBOE equity p/c, AAII, NAAIM)
│   │           └── yahoo.py             # Response models for Yahoo Finance (via yfinance)
│   ├── trading-mcp/                     # MCP server (composed via fastmcp mount)
│   │   ├── pyproject.toml               # depends on: trading-clients + fastmcp + yfinance
│   │   └── src/trading_mcp/
│   │       ├── server.py                # Lifespan, parent FastMCP, mount() calls, dependency middleware
│   │       ├── helpers.py               # Client extractors, shared helpers (_retry, etc.)
│   │       ├── dependencies.py          # Dependency enum + DependencyRegistry + middleware:
│   │       │                            #   tools declare hard deps via meta=depends(Dependency.X); a call
│   │       │                            #   needing a degraded dep is blocked with a clean ToolError
│   │       ├── yfinance_helper.py       # Shared yfinance namespace (_yfc) for fundamentals + screens
│   │       ├── pipeline_sync.py         # Best-effort S3 publish of active pipeline on every mutation
│   │       ├── db/                      # SQLite database layer (~/.trading/trading.db)
│   │       │   ├── __init__.py          # Connection, shared utilities
│   │       │   ├── pipeline.py          # Pipeline table schema, enums, async CRUD
│   │       │   ├── rolls.py             # Rolls table schema, enums, async CRUD
│   │       │   ├── decisions.py         # Option decisions table schema, enums, async CRUD
│   │       │   └── twse_revenue.py      # TWSE monthly revenue cache (TSMC + future TW tickers)
│   │       └── tools/                   # Subdomain-organized tool modules
│   │           ├── account.py           # Balances, positions, orders, instruments, portfolio aggregates (Webull + Tradier + TastyTrade read-only)
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
│   │           ├── prediction_markets.py # Polymarket + Kalshi by-key fetcher and cross-source compare
│   │           ├── tsmc.py              # TSMC monthly revenue via TWSE OpenAPI + SQLite history cache
│   │           ├── treasury.py          # QRA Policy Statement texture (latest + prior for diff)
│   │           ├── freight.py           # Container freight signals: FBX lane prices + chokepoint transit volumes
│   │           ├── beige_book.py        # Fed Beige Book National Summary + 12 district highlights
│   │           ├── squeeze_metrics.py   # SqueezeMetrics DIX (dark-pool flow) + GEX (dealer gamma)
│   │           ├── naaim.py             # NAAIM Exposure Index history with 52w z-score / percentile
│   │           ├── eia.py               # EIA Weekly Petroleum Status Report (stocks, refinery util, retail gasoline)
│   │           ├── factset.py           # FactSet Earnings Insight (S&P 500 beat rates, blended growth, forward EPS, P/E, sector revisions)
│   │           ├── backtest.py          # TastyTrade option strategy backtests
│   │           ├── earnings.py          # Earnings call transcript (walks PROVIDERS registry) + press release (EDGAR 8-K)
│   │           ├── transcript_providers.py  # TranscriptProvider registry: Fool, Morningstar; add new providers here
│   │           ├── edgar.py             # Generic EDGAR primitives: filings index, content fetch,
│   │           │                        #   10-K/10-Q section extract, risk-factor diff, 8-K exhibit,
│   │           │                        #   pipeline-wide filings sweep
│   │           ├── ipo.py               # S-1/F-1/424B prospectus tools: latest-filing locator,
│   │           │                        #   named-section reader, customer-concentration extractor.
│   │           │                        #   Powers the /ipo skill (pre-profit speculative-growth gate run).
│   │           ├── signals.py           # Conviction, sizing, hedge, entry signals
│   │           ├── pipeline.py          # Pipeline ticker CRUD
│   │           ├── pipeline_catalysts.py # Pipeline catalyst CRUD
│   │           ├── rolls.py             # Option roll tracking CRUD
│   │           └── decisions.py         # Option decision tracking CRUD
│   └── trading-alerts/                  # Lambda watcher-fleet service
│       ├── pyproject.toml               # depends on: trading-clients + boto3 + pynacl
│       ├── Makefile                     # deploy/destroy/credentials/test automation
│       ├── terraform/                   # AWS infrastructure (self-contained)
│       │   ├── main.tf                  # Dispatcher Lambda, DynamoDB, S3 pipeline-state bucket,
│       │   │                            #   per-watcher EventBridge rules, IAM, SSM, interaction Lambda
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── scripts/
│       │   ├── invoke_local.py          # Local watcher runner (--list / --trigger)
│       │   ├── build_lambda.sh          # Build Lambda deployment ZIP
│       │   └── register_commands.py     # Register Discord slash commands
│       └── src/trading_alerts/
│           ├── handler.py               # Lambda dispatcher: routes EventBridge
│           │                            #   {"trigger": "..."} → WATCHERS[name]()
│           ├── config.py                # AlertsConfig (SSM Parameter Store or ~/.tradingrc)
│           ├── discord.py               # send_embed() generic embed sender + mute buttons
│           ├── event.py                 # AlertEvent dataclass (watcher return type)
│           ├── dispatch.py              # dispatch(): dedup → Discord post → DynamoDB persist
│           ├── state.py                 # AlertRecord, AlertStore Protocol, Dynamo + InMemory
│           ├── interaction.py           # Discord interaction handler (mute buttons,
│           │                            #   /unmute, /muted)
│           ├── pipeline_state.py        # Read active pipeline from S3; module-level cache per container
│           └── watchers/
│               ├── naaim.py             # NAAIM Exposure Index crowding (|z| >= 1.5)
│               ├── gex.py               # GEX regime (sign flip + 1m percentile extreme)
│               ├── dix.py               # DIX single-day move (dark-pool short ratio spike)
│               ├── tsmc_revenue.py      # TSMC monthly revenue new-release detection
│               ├── wpsr.py              # EIA WPSR new-release detection (Wed 10:30 ET)
│               ├── beige_book.py        # Fed Beige Book new-release detection
│               ├── qra.py               # Treasury QRA Policy Statement new-release detection
│               ├── factset_ei.py        # FactSet Earnings Insight weekly PDF new-release detection
│               ├── nfp.py               # BLS Employment Situation (NFP) new-release detection
│               ├── cpi.py               # BLS CPI new-release detection
│               ├── pce.py               # BEA PCE new-release detection
│               ├── gdp.py               # BEA GDP new-release detection
│               ├── fomc.py              # FOMC statement new-release detection
│               └── fomc_minutes.py      # FOMC minutes new-release detection (3 weeks post-meeting)
└── tests/                               # Test suite (Phase 2)
```

### Dependency Graph

```
trading-clients (httpx[http2])
  ├── trading-mcp (+ fastmcp + yfinance)
  ├── trading-alerts (+ boto3 + pynacl)
  └── trading-scalper (+ pyyaml; paper entry-detector; uses trading-clients[streaming])
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

### Data Flow — Trading Alerts

```
EventBridge (per-watcher cron rule)
  → sends {"trigger": "<name>"} to dispatcher Lambda
    → handler.py looks up WATCHERS[name] and runs it
      → ticker-aware watchers call pipeline_state.get_pipeline() on cold start
          → fetches active pipeline from s3://trading-alerts-state-{account_id}/pipeline.json
          → result cached for container lifetime; returns [] if unset/missing
      → watcher fetches data (NAAIM XLSX, SqueezeMetrics CSV, BLS press release, …)
      → evaluates threshold; returns list[AlertEvent]
    → for each event, dispatch() checks dedup (DynamoDB get_item)
      → if new: send_embed() to Discord + persist AlertRecord
      → if duplicate or muted: skip
```

A separate Lambda (function URL, no auth — Discord verifies via Ed25519
signature) handles button clicks (`mute:<seconds>:<dedup_key>`) and the
`/unmute` and `/muted` slash commands by mutating the same DynamoDB table.

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
| **Tradier** | Option chains, greeks, IV, quotes; read-only account (profile, balances, positions, orders) folded into the portfolio aggregation; **streaming market data** (top-of-book quote + trade + timesale via WebSocket) powering the scalper feed — production-only | Bearer token |
| **Finnhub** | News, earnings calendar, key metrics | API key |
| **FMP** | Financial statements, company profiles, sector performance | API key |
| **FRED** | Macroeconomic data (CPI, GDP, VIX, rates) | API key |
| **Alpha Vantage** | News sentiment, top market movers | API key |
| **EIA** | Weekly Petroleum Status Report — crude/product stocks, refinery utilization, retail gasoline. WPSR Wed 10:30 ET. Used during oil-price / inflation events; informs CPI energy, consumer demand destruction, Fed policy path. | API key (free, [register](https://www.eia.gov/opendata/register.php)) |
| **TastyTrade** | IV rank/percentile, backtesting, watchlists, dividends; read-only account (accounts, balances, positions, orders) folded into the portfolio aggregation | OAuth2 refresh token |
| **Yahoo Finance** | Stock screener, institutional ownership | None (via yfinance) |
| **Motley Fool** | Earnings call transcripts (scraped, primary source) | None |
| **Morningstar** | Earnings call transcripts (Playwright fallback for tickers Fool misses — small caps, foreign issuers). URL is `/stocks/{xase\|xnys\|xnas}/{ticker}/earnings-transcript`; AWS WAF JS challenge requires headless-Chromium with `navigator.webdriver` mask. | None (Playwright) |
| **SEC EDGAR** | All filings: tier-classified recent-filings index (10-Q/10-K/8-K/13D/Form 4/S-3/DEF 14A/etc.); cleaned section extraction (MD&A, risk factors, segments, cash-flow narrative, business overview); 10-K Item 1A risk-factor diff vs prior year; 8-K Ex 99.x exhibit fetch; pipeline-wide filings sweep | None (User-Agent only) |
| **BLS** | Employment Situation / CPI press release narrative | None (User-Agent only) |
| **BEA** | Personal Income and Outlays (PCE) press release narrative | None (User-Agent only) |
| **Federal Reserve** | FOMC statements (latest + prior for language diff); FOMC minutes released ~3 weeks post-meeting, split into named sections (staff outlook, Participants' Views "a few/several/many/most" language, policy actions) with prior-meeting comparison; Beige Book National Summary + 12 district highlights (8x/year, ~2 weeks pre-FOMC) | None (User-Agent only) |
| **CFTC** | Commitments of Traders (COT) — speculator positioning across SPX, NDX, VIX, 10Y, Gold, WTI | None (Socrata JSON) |
| **Polymarket** | Prediction-market implied probabilities (FOMC, elections, macro) — by event slug | None (gamma-api JSON) |
| **Kalshi** | Prediction-market implied probabilities (CFTC-regulated US exchange) — by event ticker | None (elections-api JSON) |
| **TWSE** | Listed-company monthly revenue via openapi.twse.com.tw t187ap05_L feed — leading indicator for the global semi cycle via TSMC (2330), released ~10th of each month. History accumulates in `~/.trading/trading.db`. | None (JSON, polite User-Agent) |
| **Treasury** | Quarterly Refunding Announcement (QRA) Policy Statement — auction sizes, bill-vs-coupon mix, buyback program, and forward guidance. Released 4x/year (early Feb / May / Aug / Nov), Wednesday 8:30 AM after Monday's borrowing estimate. | None (User-Agent only) |
| **Freightos** | Freightos Baltic Index (FBX) — weekly container freight prices per lane (USD/FEU). Published Fridays. Used for geopolitical-risk rerouting confirmation. | None (User-Agent only) |
| **IMF PortWatch** | Daily chokepoint vessel transit volumes (Suez, Bab el-Mandeb, Hormuz, Panama, Cape of Good Hope, Bosporus, Malacca and 21 more). ArcGIS REST. ~5-day publish lag. | None (User-Agent only) |
| **SqueezeMetrics** | DIX (dark-pool dollar-weighted short ratio of S&P 500 components) + GEX (dealer net gamma in $) — daily history CSV powering the public /monitor/dix chart | None (User-Agent only) |
| **CBOE** | Equity put/call ratio (daily) | None (Playwright, realistic browser context) |
| **AAII** | Investor sentiment survey bull/neutral/bear (weekly) | None (Playwright, realistic browser context) |
| **NAAIM** | Active manager equity exposure index — full since-inception history with 52w z-score / percentile (latest entry replaces the prior Playwright scrape) | None (XLSX). naaim.org sits behind Cloudflare Bot Management (keys on TLS fingerprint, intermittently 403s httpx), so the MCP client routes discovery + download through the shared Playwright browser context; falls back to httpx (degraded) when no host, e.g. the Lambda watcher |
| **FactSet** | Earnings Insight weekly PDF (S&P 500 beat rates, surprise magnitudes, blended growth, forward EPS by quarter + CY, forward 12M P/E with 5y/10y context, sector revisions, beat/miss reaction asymmetry). Published Friday afternoon ET. The institutional benchmark for earnings season tone. | None (httpx + polite User-Agent; pdfplumber) |
| **Reddit** | Subreddit search, hot/top/new listings, and individual post + comments — used for sentiment reading on specific tickers or themes via `search_reddit`, `get_subreddit_posts`, `get_reddit_post` tools | None (JSON API; anonymous `.json` is 403-blocked, so httpx rides a `loid` cookie minted once via the shared Playwright Chromium and re-minted on 403) |

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

[eia]
api_key = <your_api_key>

[tastytrade]
client_secret = <your_oauth_client_secret>
refresh_token = <your_oauth_refresh_token>

[discord]
bot_token      = <discord_bot_token>       # used by trading-alerts to post embeds
channel_id     = <discord_channel_id>      # the channel alerts post to
public_key     = <discord_app_public_key>  # interaction handler signature verification
application_id = <discord_application_id>  # /unmute and /muted slash command registration
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
- MCP server calls `.to_output()` on response models; trading-alerts watchers access typed fields directly
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
