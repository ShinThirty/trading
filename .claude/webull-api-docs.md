# Webull OpenAPI Documentation

## Guides

### Getting Started
- [Welcome to Webull API](https://developer.webull.com/apis/docs.md): Platform overview covering trading APIs, market data services, OAuth integration, and tools for building trading applications and brokerage solutions.
- [About Webull](https://developer.webull.com/apis/docs/about.md): Company introduction and regulatory background.
- [About Webull OpenAPI](https://developer.webull.com/apis/docs/about-open-api.md): OpenAPI platform capabilities and features overview.
- [Getting Started](https://developer.webull.com/apis/docs/getting-started.md): Quick start guide for making your first API call.
- [SDKs and Tools](https://developer.webull.com/apis/docs/sdk.md): SDK installation, development tools, and example code for trading and market data integration.
- [Additional Resources](https://developer.webull.com/apis/docs/resources.md): Learning materials, blog updates, support channels, and regulatory disclosures.

### AI Friendly Resources
- [llms.txt](https://developer.webull.com/apis/docs/AI-friendly-Resources/llm.md): Machine-readable documentation for AI-assisted development with LLMs, RAG pipelines, and AI coding tools.

### Authentication
- [Authentication Overview](https://developer.webull.com/apis/docs/authentication/overview.md): Digest signature authentication using App Key and App Secret with security best practices.
- [Individual Application Process](https://developer.webull.com/apis/docs/authentication/IndividualApplicationAPI.md): Step-by-step guide for individual users to apply for API access and generate API keys.
- [Institution Application Process](https://developer.webull.com/apis/docs/authentication/apply.md): Institutional API application process, authorization workflow, and API key creation.
- [Signature](https://developer.webull.com/apis/docs/authentication/signature.md): HMAC-SHA1 signature generation, request composition, and required headers for API authentication.
- [Token](https://developer.webull.com/apis/docs/authentication/token.md): Token lifecycle management including creation, 2FA verification, status checks, storage, and usage in API requests.

### Market Data API
- [Market Data API Overview](https://developer.webull.com/apis/docs/market-data-api/overview.md): HTTP-based historical and real-time data retrieval (tick, snapshot, quotes, bars) for stocks, futures, crypto, and event contracts; MQTT streaming via WebSocket/TCP; rate limits and subscription requirements.
- [Market Data API Getting Started](https://developer.webull.com/apis/docs/market-data-api/getting-started.md): Quick start guide for SDK installation, API key setup, and requesting historical or real-time market data with code examples.
- [Data API](https://developer.webull.com/apis/docs/market-data-api/data-api.md): HTTP-based market data access covering supported markets and data types.
- [Data Streaming API](https://developer.webull.com/apis/docs/market-data-api/data-streaming-api.md): Real-time market data streaming via MQTT protocol implementation guide.
- [Subscribe Advanced Quotes](https://developer.webull.com/apis/docs/market-data-api/subscribe-quotes.md): Browser-based guide to purchase and activate advanced real-time market data subscriptions.
- [Market Data API FAQ](https://developer.webull.com/apis/docs/market-data-api/faq.md): Frequently asked questions about market data access and usage.

### Trading API
- [Trading API Overview](https://developer.webull.com/apis/docs/trade-api/overview.md): Core trading functionality and capabilities overview.
- [Trading API Getting Started](https://developer.webull.com/apis/docs/trade-api/getting-started.md): Quick start guide for trading API integration.
- [Trading API - Accounts](https://developer.webull.com/apis/docs/trade-api/account.md): Account management, balance queries, and account information retrieval.
- [Trading API - Stocks](https://developer.webull.com/apis/docs/trade-api/stock.md): Stock and ETF order placement, modification, cancellation, and status tracking.
- [Trading API - Options](https://developer.webull.com/apis/docs/trade-api/options.md): Options trading operations including single-leg and multi-leg strategies.
- [Trading API - Futures](https://developer.webull.com/apis/docs/trade-api/futures.md): Futures trading operations and contract management.
- [Trading API - Crypto](https://developer.webull.com/apis/docs/trade-api/crypto.md): Cryptocurrency trading functionality and digital asset operations.
- [Trading API - Event Contract](https://developer.webull.com/apis/docs/trade-api/event-contract.md): Event-based contract trading and prediction market operations.
- [Trading API - FAQs](https://developer.webull.com/apis/docs/trade-api/faq.md): Common questions and troubleshooting for trading API.

### Connect API
- [About Connect API](https://developer.webull.com/apis/docs/connect-api/about-connect-api.md): Connect API introduction and use cases for third-party integrations.
- [OAuth Integration Guide](https://developer.webull.com/apis/docs/connect-api/authentication.md): OAuth 2.0 implementation for user authorization and token management.

### Broker API
- [Broker API Getting Started](https://developer.webull.com/apis/docs/broker-api/getting-started.md): Getting started guide for broker-level API integration.

### General
- [Webull OpenAPI FAQs](https://developer.webull.com/apis/docs/faq.md): General frequently asked questions about Webull OpenAPI platform.

## API Reference

### Authentication & Token Management
- [Create Token](https://developer.webull.com/apis/docs/reference/create-token.md): Generate authentication tokens for API access.
- [Check Token](https://developer.webull.com/apis/docs/reference/check-token.md): Verify token validity and status.

### Market Data - Stock
- [Stock Tick](https://developer.webull.com/apis/docs/reference/tick.md): Real-time tick-by-tick trade data for stocks.
- [Stock Snapshot](https://developer.webull.com/apis/docs/reference/snapshot.md): Current market snapshot with latest prices and statistics.
- [Stock Quotes](https://developer.webull.com/apis/docs/reference/quotes.md): Real-time bid/ask quotes and market depth.
- [Stock Footprint](https://developer.webull.com/apis/docs/reference/footprint.md): Order flow and volume profile analysis data.
- [Stock Historical Bars](https://developer.webull.com/apis/docs/reference/historical-bars.md): Historical OHLCV candlestick data for multiple symbols.
- [Stock Historical Bars (Single Symbol)](https://developer.webull.com/apis/docs/reference/bars.md): Historical OHLCV candlestick data for a single symbol.

### Market Data - Futures
- [Futures Tick](https://developer.webull.com/apis/docs/reference/futures-tick.md): Real-time tick-by-tick trade data for futures contracts.
- [Futures Snapshot](https://developer.webull.com/apis/docs/reference/futures-snapshot.md): Current futures market snapshot with latest prices and open interest.
- [Futures Footprint](https://developer.webull.com/apis/docs/reference/futures-footprint.md): Futures order flow and volume profile analysis.
- [Futures Depth of Book](https://developer.webull.com/apis/docs/reference/futures-depth-of-book.md): Market depth data for futures contracts.
- [Futures Historical Bars](https://developer.webull.com/apis/docs/reference/futures-historical-bars.md): Historical OHLCV data for futures contracts.

### Market Data - Crypto
- [Crypto Snapshot](https://developer.webull.com/apis/docs/reference/crypto-snapshot.md): Current cryptocurrency market snapshot with latest prices.
- [Crypto Candlesticks](https://developer.webull.com/apis/docs/reference/crypto-bars.md): Historical OHLCV candlestick data for cryptocurrencies.

### Market Data - Event
- [Event Snapshot](https://developer.webull.com/apis/docs/reference/event-snapshot.md): Real-time snapshot for event contracts.
- [Event Depth](https://developer.webull.com/apis/docs/reference/event-depth.md): Market depth data for event contracts.
- [Event Bars](https://developer.webull.com/apis/docs/reference/event-bars.md): Historical candlestick data for event contracts.
- [Event Tick](https://developer.webull.com/apis/docs/reference/event-tick.md): Tick-by-tick trade data for event contracts.

### Market Data - Streaming
- [Subscribe](https://developer.webull.com/apis/docs/reference/subscribe.md): Subscribe to real-time market data streams via MQTT.
- [Unsubscribe](https://developer.webull.com/apis/docs/reference/unsubscribe.md): Unsubscribe from real-time market data streams.

### Instruments & Symbols
- [Get Stock Instrument](https://developer.webull.com/apis/docs/reference/instrument-list.md): List of available stock symbols and instrument details.
- [Get Crypto Instrument](https://developer.webull.com/apis/docs/reference/crypto-instrument-list.md): List of available cryptocurrency trading pairs.
- [Get Instrument Code](https://developer.webull.com/apis/docs/reference/futures-products.md): Available futures product categories and specifications.
- [Get Instrument by Code](https://developer.webull.com/apis/docs/reference/futures-instrument-list-by-code.md): Query futures contracts by product code.
- [Get Instrument by Symbol](https://developer.webull.com/apis/docs/reference/futures-instrument-list.md): Query futures contracts by symbol.
- [Get Event Contract Categories](https://developer.webull.com/apis/docs/reference/event-categories-list.md): List available event contract categories.
- [Get Event Contract Series](https://developer.webull.com/apis/docs/reference/event-series-list.md): List available event contract series for prediction markets.
- [Get Event Contract Events](https://developer.webull.com/apis/docs/reference/event-events-list.md): Query event contract events within a series.
- [Get Event Contract Instrument](https://developer.webull.com/apis/docs/reference/event-market-list.md): Query specific event contract instruments and details.

### Account Management
- [Account List](https://developer.webull.com/apis/docs/reference/account-list.md): Retrieve list of user accounts and account IDs.
- [Account Balance](https://developer.webull.com/apis/docs/reference/account-balance.md): Query account balance, buying power, and cash details.
- [Account Positions](https://developer.webull.com/apis/docs/reference/account-position.md): Retrieve current positions and holdings.

### Order Management - Trading
- [Preview Order](https://developer.webull.com/apis/docs/reference/common-order-preview.md): Preview order details and estimated costs before placement.
- [Place Order](https://developer.webull.com/apis/docs/reference/common-order-place.md): Submit new orders for stocks, options, futures, or crypto.
- [Batch Place Orders](https://developer.webull.com/apis/docs/reference/order-batch-place.md): Submit multiple orders in a single batch request.
- [Replace Order](https://developer.webull.com/apis/docs/reference/common-order-replace.md): Modify existing open orders (price, quantity, etc.).
- [Cancel Order](https://developer.webull.com/apis/docs/reference/common-order-cancel.md): Cancel pending or open orders.

### Order Management - Query
- [Order History](https://developer.webull.com/apis/docs/reference/order-history.md): Query historical order records and execution details.
- [Open Orders](https://developer.webull.com/apis/docs/reference/order-open.md): Retrieve list of current open orders.
- [Order Detail](https://developer.webull.com/apis/docs/reference/order-detail.md): Get detailed information for a specific order.

### Trade Events
- [Subscribe Trade Events](https://developer.webull.com/apis/docs/reference/custom/subscribe-trade-events.md): Subscribe to real-time order status change notifications via gRPC.
- [Subscribe Position Events](https://developer.webull.com/apis/docs/reference/custom/subscribe-position-events.md): Subscribe to real-time position change notifications via gRPC.

### Connect API (OAuth)
- [Get Authorization Code](https://developer.webull.com/apis/docs/reference/connect-api/get-authorization-code.md): Initiate OAuth flow to obtain user authorization code.
- [Create & Refresh Token](https://developer.webull.com/apis/docs/reference/connect-api/create-and-refresh-token.md): Exchange authorization code for access token and refresh expired tokens.

## Changelog
- [Documentation Changelog](https://developer.webull.com/apis/docs/changelog.md): Track updates, new features, and changes to the API documentation.

---

## Base URLs

### Production Environment
- HTTP API: `api.webull.com`
- Trading message push: `events-api.webull.com`
- Market data message push: `data-api.webull.com`

### Test Environment
- HTTP API: `us-openapi-alb.uat.webullbroker.com`
- Trading message push: `us-openapi-events.uat.webullbroker.com`

## Official SDKs

### Python
```bash
pip3 install --upgrade webull-openapi-python-sdk
```

### Java (Maven)
```xml
<dependency>
    <groupId>com.webull.openapi</groupId>
    <artifactId>webull-openapi-java-sdk</artifactId>
    <version>1.0.3</version>
</dependency>
```
