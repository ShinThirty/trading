from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from trading_mcp.alphavantage_client import AlphaVantageClient
from trading_mcp.config import load_config
from trading_mcp.endpoints import alphavantage as av
from trading_mcp.endpoints import finnhub as fh
from trading_mcp.endpoints import fmp, fred
from trading_mcp.endpoints import tradier as t
from trading_mcp.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    CANCEL_ORDER,
    INSTRUMENTS,
    OPEN_ORDERS,
    ORDER_DETAIL,
    ORDER_HISTORY,
    PLACE_ORDER,
    POSITIONS,
    PREVIEW_ORDER,
    REPLACE_ORDER,
    AccountRequest,
    CancelOrderRequest,
    EmptyRequest,
    GetInstrumentsRequest,
    GetOpenOrdersRequest,
    GetOrderDetailRequest,
    GetOrderHistoryRequest,
    PlaceOrderRequest,
    PreviewOrderRequest,
    ReplaceOrderRequest,
)
from trading_mcp.finnhub_client import FinnhubClient
from trading_mcp.fmp_client import FmpClient
from trading_mcp.fred_client import FredClient
from trading_mcp.tradier_client import TradierClient
from trading_mcp.webull_client import WebullClient


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    config = load_config()
    ctx: dict[str, Any] = {"webull": WebullClient(config.webull)}
    if config.tradier:
        ctx["tradier"] = TradierClient(config.tradier)
    if config.finnhub:
        ctx["finnhub"] = FinnhubClient(config.finnhub)
    if config.fmp:
        ctx["fmp"] = FmpClient(config.fmp)
    if config.fred:
        ctx["fred"] = FredClient(config.fred)
    if config.alphavantage:
        ctx["alphavantage"] = AlphaVantageClient(config.alphavantage)
    try:
        yield ctx
    finally:
        for client in ctx.values():
            client._http.close()


mcp = FastMCP("trading-mcp", lifespan=lifespan)


# ── Client helpers ──────────────────────────────────────────


def _webull(ctx: Context) -> WebullClient:
    return ctx.request_context.lifespan_context["webull"]


def _tradier(ctx: Context) -> TradierClient:
    client = ctx.request_context.lifespan_context.get("tradier")
    if client is None:
        raise RuntimeError("Tradier not configured. Add [tradier] section to ~/.tradingrc")
    return client


def _finnhub(ctx: Context) -> FinnhubClient:
    client = ctx.request_context.lifespan_context.get("finnhub")
    if client is None:
        raise RuntimeError("Finnhub not configured. Add [finnhub] section to ~/.tradingrc")
    return client


def _fmp(ctx: Context) -> FmpClient:
    client = ctx.request_context.lifespan_context.get("fmp")
    if client is None:
        raise RuntimeError("FMP not configured. Add [fmp] section to ~/.tradingrc")
    return client


def _fred(ctx: Context) -> FredClient:
    client = ctx.request_context.lifespan_context.get("fred")
    if client is None:
        raise RuntimeError("FRED not configured. Add [fred] section to ~/.tradingrc")
    return client


def _alphavantage(ctx: Context) -> AlphaVantageClient:
    client = ctx.request_context.lifespan_context.get("alphavantage")
    if client is None:
        raise RuntimeError(
            "Alpha Vantage not configured. Add [alphavantage] section to ~/.tradingrc"
        )
    return client


def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    """Validate market state before placing an order."""
    tradier = ctx.request_context.lifespan_context.get("tradier")
    if tradier is None:
        return  # skip check if Tradier not configured
    state = tradier.get_clock().get("state", "closed")
    if order_type == "MARKET" and state != "open" and not extended_hours:
        raise RuntimeError(
            f"MARKET orders require regular hours (state: {state}). "
            "Use a LIMIT order, or wait for market open."
        )


# ═══════════════════════════════════════════════════════════════
# WEBULL — Brokerage (Account, Orders, Market Data)
# ═══════════════════════════════════════════════════════════════

# ── Account ──────────────────────────────────────────────────


@mcp.tool()
def get_account_balance(ctx: Context, account_id: str | None = None) -> str:
    """Get account balance: net liquidation, cash, buying power, market value, day P&L,
    unrealized P&L, margin info.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(BALANCE, AccountRequest(client.resolve_account_id(account_id)))


@mcp.tool()
def get_account_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get all current portfolio holdings including option positions with full leg details
    (strike, expiration, option type, strategy). Returns each position's symbol, type,
    quantity, cost, last price, and unrealized P&L.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(POSITIONS, AccountRequest(client.resolve_account_id(account_id)))


# ── Orders ───────────────────────────────────────────────────


@mcp.tool()
def get_open_orders(ctx: Context, page_size: int = 50, account_id: str | None = None) -> str:
    """Get all currently open/pending orders (stocks, options, futures, crypto).
    Returns symbol, side, order_type, quantity, filled_quantity, price, status,
    and option leg details if applicable.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(
        OPEN_ORDERS,
        GetOpenOrdersRequest(client.resolve_account_id(account_id), page_size),
    )


@mcp.tool()
def get_today_orders(
    ctx: Context,
    page_size: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    account_id: str | None = None,
) -> str:
    """Get order history including filled, cancelled, and pending orders.

    start_date: start date (YYYY-MM-DD). Defaults to today.
    end_date: end date (YYYY-MM-DD). Defaults to today.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(
        ORDER_HISTORY,
        GetOrderHistoryRequest(
            client.resolve_account_id(account_id), page_size, start_date, end_date
        ),
    )


@mcp.tool()
def get_order_detail(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Get full detail for a specific order including status, fill info, timestamps,
    and option leg details.

    client_order_id: the unique order ID assigned when the order was placed.
    Use get_open_orders or get_today_orders to find client_order_ids.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(
        ORDER_DETAIL,
        GetOrderDetailRequest(client.resolve_account_id(account_id), client_order_id),
    )


# ── Order Management (unified for stocks + options) ─────────


@mcp.tool()
def preview_order(ctx: Context, new_orders: list[dict], account_id: str | None = None) -> str:
    """Preview an order before placing it. Returns estimated cost and transaction fees.
    Supports stocks, options (single-leg and multi-leg), futures, and crypto.

    new_orders: list of order dicts. Each dict should contain:
      - client_order_id: str (unique ID, max 32 chars)
      - combo_type: 'NORMAL' (or 'OTO', 'OCO', 'OTOCO' for combo orders)
      - symbol: ticker symbol (e.g. 'AAPL')
      - instrument_type: 'EQUITY', 'OPTION', 'FUTURES', or 'CRYPTO'
      - market: 'US'
      - side: 'BUY' or 'SELL'
      - order_type: 'MARKET', 'LIMIT', 'STOP_LOSS', or 'STOP_LOSS_LIMIT'
      - quantity: str (e.g. '10', supports fractional shares)
      - time_in_force: 'DAY', 'GTC', or 'IOC'
      - entrust_type: 'QTY' (or 'AMOUNT' for fractional/dollar-based)
      - limit_price: str (required for LIMIT orders)
      - stop_price: str (required for STOP_LOSS orders)
      - trading_session: 'CORE' (regular hours), 'ALL' (include extended), 'NIGHT'

    For options, also include:
      - option_strategy: 'SINGLE', 'VERTICAL', 'STRADDLE', 'STRANGLE', 'IRON_CONDOR', etc.
      - position_intent: 'BUY_TO_OPEN', 'BUY_TO_CLOSE', 'SELL_TO_OPEN', 'SELL_TO_CLOSE'
      - legs: list of leg dicts with: symbol, side, quantity, strike_price,
        option_expire_date (YYYY-MM-DD), option_type ('CALL' or 'PUT'),
        instrument_type ('OPTION'), market ('US')

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    # Preview uses the same request structure as place_order but via preview endpoint
    req = PreviewOrderRequest(
        account_id=client.resolve_account_id(account_id), **new_orders[0]
    )
    return client.post(PREVIEW_ORDER, req)


@mcp.tool()
def place_order(
    ctx: Context,
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    client_order_id: str,
    time_in_force: str,
    instrument_type: str = "EQUITY",
    account_id: str | None = None,
    trading_session: str = "CORE",
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
    option_strategy: str | None = None,
    position_intent: str | None = None,
    legs: list[dict] | None = None,
) -> str:
    """Place an order for stocks or options.

    symbol: ticker symbol (e.g. 'AAPL'). No instrument_id lookup needed.
    side: 'BUY' or 'SELL'.
    order_type: 'MARKET', 'LIMIT', 'STOP_LOSS', or 'STOP_LOSS_LIMIT'.
    quantity: number of shares/contracts as string (e.g. '10', supports fractional).
    client_order_id: unique ID you generate (use a UUID, max 32 chars).
    time_in_force: 'DAY', 'GTC' (good til cancelled), or 'IOC'.
    instrument_type: 'EQUITY' (default) or 'OPTION'.
    trading_session: 'CORE' (regular hours, default), 'ALL' (include extended), 'NIGHT'.
    limit_price: required for LIMIT and STOP_LOSS_LIMIT orders (e.g. '150.50').
    stop_price: required for STOP_LOSS and STOP_LOSS_LIMIT orders (e.g. '148.00').
    trailing_type: 'AMOUNT' or 'PERCENTAGE' for trailing stop orders.
    trailing_stop_step: the trailing amount or percentage (e.g. '1.00').

    For options (instrument_type='OPTION'), also provide:
      option_strategy: 'SINGLE', 'VERTICAL', 'STRADDLE', 'STRANGLE', 'IRON_CONDOR', etc.
      position_intent: 'BUY_TO_OPEN', 'BUY_TO_CLOSE', 'SELL_TO_OPEN', 'SELL_TO_CLOSE'.
      legs: list of leg dicts, each with: symbol, side ('BUY'/'SELL'), quantity,
        strike_price, option_expire_date ('YYYY-MM-DD'), option_type ('CALL'/'PUT'),
        instrument_type ('OPTION'), market ('US').

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    _check_market(ctx, order_type, trading_session == "ALL")
    client = _webull(ctx)
    req = PlaceOrderRequest(
        account_id=client.resolve_account_id(account_id),
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        client_order_id=client_order_id,
        time_in_force=time_in_force,
        instrument_type=instrument_type,
        trading_session=trading_session,
        limit_price=limit_price,
        stop_price=stop_price,
        trailing_type=trailing_type,
        trailing_stop_step=trailing_stop_step,
        option_strategy=option_strategy,
        position_intent=position_intent,
        legs=legs,
    )
    return client.post(PLACE_ORDER, req)


@mcp.tool()
def replace_order(
    ctx: Context,
    client_order_id: str,
    quantity: str | None = None,
    order_type: str | None = None,
    time_in_force: str | None = None,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
    account_id: str | None = None,
) -> str:
    """Modify a pending order. Only price, quantity, type, and time_in_force can be changed.

    client_order_id: the unique order ID of the order to modify.
    quantity: new quantity (optional).
    order_type: new order type (optional).
    time_in_force: new TIF (optional).
    limit_price: new limit price (optional).
    stop_price: new stop price (optional).
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    req = ReplaceOrderRequest(
        account_id=client.resolve_account_id(account_id),
        client_order_id=client_order_id,
        quantity=quantity,
        order_type=order_type,
        time_in_force=time_in_force,
        limit_price=limit_price,
        stop_price=stop_price,
        trailing_type=trailing_type,
        trailing_stop_step=trailing_stop_step,
    )
    return client.post(REPLACE_ORDER, req)


@mcp.tool()
def cancel_order(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending order (stock or option). The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable orders.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    req = CancelOrderRequest(client.resolve_account_id(account_id), client_order_id)
    return client.post(CANCEL_ORDER, req)


@mcp.tool()
def get_app_subscriptions(ctx: Context) -> str:
    """Get all Webull accounts linked to this API key: account ID, account number,
    type (MARGIN/CASH), and label (Individual Cash, Roth IRA, etc.).
    """
    return _webull(ctx).get(ACCOUNT_LIST, EmptyRequest())


# ── Webull Market Data ──────────────────────────────────────


@mcp.tool()
def get_instruments(ctx: Context, symbols: str, category: str = "US_STOCK") -> str:
    """Look up instrument details for symbols: instrument_id, exchange, currency,
    and trading attributes (shortable, fractionable, marginable).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA'). Max 100.
    category: 'US_STOCK' (default) or 'US_ETF'.
    """
    return _webull(ctx).get(INSTRUMENTS, GetInstrumentsRequest(symbols, category))



# ═══════════════════════════════════════════════════════════════
# TRADIER — Option Chains, Greeks, IV
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_option_expirations(ctx: Context, symbol: str) -> str:
    """Get all available option expiration dates for an underlying symbol.
    Use this first to discover which expirations are available before fetching
    the full chain.

    symbol: underlying ticker symbol (e.g. 'AAPL', 'SPY', 'TSLA').
    Returns a list of expiration dates as strings (YYYY-MM-DD).

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))


@mcp.tool()
def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.STRIKES, t.GetStrikesRequest(symbol, expiration))


@mcp.tool()
def get_option_chain(
    ctx: Context,
    symbol: str,
    expiration: str,
    greeks: bool = True,
) -> str:
    """Get the full option chain for an underlying symbol at a specific expiration.

    Returns all calls and puts with: bid/ask with sizes, last price, day change/%,
    volume, open interest, and optionally greeks (IV, delta, gamma, theta, vega, rho).

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    greeks: include greeks and IV per contract (default True).

    Typical workflow:
    1. get_option_expirations('AAPL') → list of dates
    2. get_option_chain('AAPL', '2026-04-17') → full chain with greeks

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks))


@mcp.tool()
def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.OPTION_LOOKUP, t.GetLookupRequest(underlying))


@mcp.tool()
def get_tradier_history(
    ctx: Context,
    symbol: str,
    interval: str = "daily",
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Get historical OHLCV pricing data. Works for both stocks AND option contracts.

    For option contracts, pass the OCC symbol (e.g. 'AAPL260417C00260000') — use
    get_option_lookup to discover available symbols.

    symbol: ticker or OCC option symbol.
    interval: 'daily', 'weekly', or 'monthly'.
    start: start date (YYYY-MM-DD). Defaults to beginning of available data.
    end: end date (YYYY-MM-DD). Defaults to today.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, interval, start, end))


@mcp.tool()
def search_symbols(ctx: Context, query: str, indexes: bool = False) -> str:
    """Search for stocks and ETFs by company name or partial symbol. Results are sorted
    by average volume (most liquid first). Useful for stock discovery.

    query: search term — company name or partial symbol (e.g. 'apple', 'semi', 'AI').
    indexes: set True to include index symbols in results.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.SEARCH, t.SearchRequest(query, indexes))


@mcp.tool()
def get_quote(ctx: Context, symbols: str, greeks: bool = False) -> str:
    """Get real-time quotes for stocks and/or option contracts.

    For stocks: last price, bid/ask with sizes, volume, day change/%, prev close,
    open/high/low, average volume, 52-week high/low.
    For options: last price, bid/ask with sizes, volume, day change/%, open interest,
    plus decoded strike/expiration/type from the OCC symbol.
    When greeks=True, option quotes additionally include: implied volatility (mid IV),
    delta, gamma, theta, vega, and rho.

    symbols: comma-separated ticker symbols or OCC option symbols. Can mix both in one
      call (e.g. 'AAPL,TSLA,AAPL260417C00260000'). Use get_option_lookup to find OCC
      symbols for options.
    greeks: include greeks and IV for option symbols (default False). Has no effect on
      stock symbols. Set True when evaluating option positions or comparing contracts.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbols, greeks))


@mcp.tool()
def get_timesales(
    ctx: Context,
    symbol: str,
    interval: str = "5min",
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Get intraday time-and-sales tick data for a stock or option contract.
    Higher granularity than historical bars — useful for intraday analysis and charting.

    Returns: timestamp, last trade price, OHLC, and volume per interval.

    symbol: ticker or OCC option symbol (e.g. 'AAPL' or 'AAPL260417C00260000').
    interval: tick interval — '1min', '5min', '15min'. Default '5min'.
    start: start datetime (YYYY-MM-DD HH:MM). Defaults to market open today.
    end: end datetime (YYYY-MM-DD HH:MM). Defaults to now.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.TIMESALES, t.GetTimesalesRequest(symbol, interval, start, end))


@mcp.tool()
def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.CLOCK, t.EmptyRequest())


# ── Tradier Account ─────────────────────────────────────────


@mcp.tool()
def get_tradier_profile(ctx: Context) -> str:
    """Get Tradier user profile with all linked accounts. Returns account number,
    type, classification, option level, and day trader status for each account.

    Use this to find your Tradier account_id.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.PROFILE, t.EmptyRequest())


@mcp.tool()
def get_tradier_balances(ctx: Context, account_id: str | None = None) -> str:
    """Get Tradier account balance: total equity, cash, market value, option value,
    buying power.

    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(t.BALANCES, t.AccountIdRequest(client.resolve_account_id(account_id)))


@mcp.tool()
def get_tradier_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get current positions in a Tradier account: symbol, quantity, cost basis,
    and date acquired.

    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(t.POSITIONS, t.AccountIdRequest(client.resolve_account_id(account_id)))


@mcp.tool()
def get_tradier_orders(
    ctx: Context,
    status: str | None = None,
    page: int | None = None,
    limit: int | None = None,
    account_id: str | None = None,
) -> str:
    """Get orders in a Tradier account.

    status: filter by status — 'pending', 'open', 'partially_filled', 'filled',
      'rejected', 'cancelled'. Omit for all.
    page: page number for pagination.
    limit: max results per page.
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(
        t.ORDERS,
        t.GetOrdersRequest(client.resolve_account_id(account_id), status, page, limit),
    )


@mcp.tool()
def get_tradier_order_detail(ctx: Context, order_id: str, account_id: str | None = None) -> str:
    """Get full detail for a specific Tradier order.

    order_id: the numeric order ID (from get_tradier_orders).
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(
        t.ORDER_DETAIL,
        t.GetOrderDetailRequest(client.resolve_account_id(account_id), order_id),
    )


@mcp.tool()
def get_tradier_gainloss(
    ctx: Context,
    page: int | None = None,
    limit: int | None = None,
    sort_by: str | None = None,
    sort: str | None = None,
    account_id: str | None = None,
) -> str:
    """Get realized gain/loss for all closed positions in a Tradier account.

    Returns: symbol, quantity, open/close dates, term (short/long), cost, proceeds,
    gain/loss amount and percentage.

    sort_by: 'closedate', 'opendate', 'symbol', or 'gainloss'.
    sort: 'asc' or 'desc'.
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(
        t.GAINLOSS,
        t.GetGainLossRequest(client.resolve_account_id(account_id), page, limit, sort_by, sort),
    )


@mcp.tool()
def get_tradier_account_history(
    ctx: Context,
    page: int | None = None,
    limit: int | None = None,
    activity_type: str | None = None,
    account_id: str | None = None,
) -> str:
    """Get account activity history: trades, dividends, fees, transfers, etc.

    activity_type: filter by type — 'trade', 'option', 'ach', 'wire', 'dividend',
      'fee', 'tax', 'journal', 'check', 'transfer', 'adjustment'. Omit for all.
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.get(
        t.ACCOUNT_HISTORY,
        t.GetAccountHistoryRequest(
            client.resolve_account_id(account_id), page, limit, activity_type
        ),
    )


# ── Tradier Order Management ───────────────────────────────


@mcp.tool()
def place_tradier_order(ctx: Context, order_params: dict, account_id: str | None = None) -> str:
    """Place an order on Tradier. Supports equity, option, multileg, combo, and
    advanced order types (OTO, OCO, OTOCO).

    order_params: dict with order parameters. The 'class' field determines the type.

    EQUITY order:
      {"class": "equity", "symbol": "AAPL", "side": "buy", "quantity": "10",
       "type": "limit", "price": "250.00", "duration": "day"}
      side: 'buy', 'sell', 'sell_short', 'buy_to_cover'

    OPTION order:
      {"class": "option", "symbol": "AAPL", "option_symbol": "AAPL260417C00260000",
       "side": "buy_to_open", "quantity": "1", "type": "limit", "price": "4.50",
       "duration": "day"}
      side: 'buy_to_open', 'buy_to_close', 'sell_to_open', 'sell_to_close'

    MULTILEG order (e.g. vertical spread, up to 4 legs):
      {"class": "multileg", "symbol": "AAPL", "type": "debit", "price": "1.50",
       "duration": "day",
       "option_symbol[0]": "AAPL260417C00255000", "side[0]": "buy_to_open",
       "quantity[0]": "1",
       "option_symbol[1]": "AAPL260417C00265000", "side[1]": "sell_to_open",
       "quantity[1]": "1"}
      type: 'market', 'debit', 'credit', 'even'

    PREVIEW: add "preview": "true" to any order to validate without executing.
    Returns estimated commission, cost, and margin impact.

    type: 'market', 'limit', 'stop', 'stop_limit'
    duration: 'day', 'gtc', 'pre' (pre-market), 'post' (after-hours)
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    """
    client = _tradier(ctx)
    params = {k: str(v) for k, v in order_params.items()}
    return client.post(
        t.PLACE_ORDER,
        t.PlaceOrderRequest(client.resolve_account_id(account_id), params),
    )


@mcp.tool()
def modify_tradier_order(
    ctx: Context,
    order_id: str,
    modifications: dict,
    account_id: str | None = None,
) -> str:
    """Modify a pending Tradier order. Only price, stop, type, and duration can be changed.

    order_id: the numeric order ID (from get_tradier_orders).
    modifications: dict of fields to change. Example:
      {"type": "limit", "price": "255.00", "duration": "gtc"}
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    """
    client = _tradier(ctx)
    params = {k: str(v) for k, v in modifications.items()}
    return client.put(
        t.MODIFY_ORDER,
        t.ModifyOrderRequest(client.resolve_account_id(account_id), order_id, params),
    )


@mcp.tool()
def cancel_tradier_order(ctx: Context, order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending Tradier order.

    order_id: the numeric order ID (from get_tradier_orders).
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    """
    client = _tradier(ctx)
    return client.delete(
        t.CANCEL_ORDER,
        t.CancelOrderRequest(client.resolve_account_id(account_id), order_id),
    )


# ═══════════════════════════════════════════════════════════════
# FINNHUB — News, Earnings Calendar, Economic Calendar
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_company_news(
    ctx: Context, symbol: str, from_date: str, to_date: str, limit: int = 20
) -> str:
    """Get recent news articles for a specific company.

    symbol: ticker symbol (e.g. 'AAPL').
    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.COMPANY_NEWS, fh.CompanyNewsRequest(symbol, from_date, to_date))


@mcp.tool()
def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.MARKET_NEWS, fh.MarketNewsRequest(category))


@mcp.tool()
def get_economic_calendar(ctx: Context, from_date: str, to_date: str) -> str:
    """Get upcoming economic events: FOMC meetings, CPI releases, jobs reports, GDP, etc.

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).

    Note: requires Finnhub premium plan. Free tier returns 403.
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.ECONOMIC_CALENDAR, fh.DateRangeRequest(from_date, to_date))


@mcp.tool()
def get_earnings_calendar(ctx: Context, from_date: str, to_date: str, limit: int = 50) -> str:
    """Get upcoming and recent earnings reports. Automatically filters out micro-caps.

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    limit: max number of entries to return (default 50).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.EARNINGS_CALENDAR, fh.DateRangeRequest(from_date, to_date))


@mcp.tool()
def get_basic_financials(ctx: Context, symbol: str) -> str:
    """Get key financial metrics: P/E, P/B, EPS, dividend yield, 52-week high/low,
    market cap, beta, ROE, debt/equity.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol))


@mcp.tool()
def get_eps_estimates(ctx: Context, symbol: str) -> str:
    """Get analyst EPS estimates for upcoming quarters: average, high, low, and number
    of analysts.

    symbol: ticker symbol (e.g. 'AAPL').

    Note: requires Finnhub premium plan. Free tier returns 403.
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.EPS_ESTIMATES, fh.SymbolRequest(symbol))


@mcp.tool()
def get_recommendation_trends(ctx: Context, symbol: str) -> str:
    """Get analyst recommendation trends: counts of strong buy, buy, hold, sell, and
    strong sell ratings by month.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.RECOMMENDATIONS, fh.SymbolRequest(symbol))


@mcp.tool()
def get_price_target(ctx: Context, symbol: str) -> str:
    """Get analyst consensus price target: high, low, mean, and median target prices.

    symbol: ticker symbol (e.g. 'AAPL').

    Note: requires Finnhub premium plan. Free tier returns 403.
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.PRICE_TARGET, fh.SymbolRequest(symbol))


@mcp.tool()
def get_insider_transactions(ctx: Context, symbol: str, limit: int = 20) -> str:
    """Get recent insider transactions: buys, sells, and grants by company officers
    and directors.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: max number of transactions to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.INSIDER_TRANSACTIONS, fh.SymbolRequest(symbol))


@mcp.tool()
def get_dividends(ctx: Context, symbol: str, from_date: str, to_date: str) -> str:
    """Get dividend history: ex-date, pay date, record date, and amount.

    symbol: ticker symbol (e.g. 'AAPL').
    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).

    Note: requires Finnhub premium plan. Use get_dividend_history (FMP) as free alternative.
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.DIVIDENDS, fh.DividendsRequest(symbol, from_date, to_date))


@mcp.tool()
def get_company_peers(ctx: Context, symbol: str) -> str:
    """Get a list of peer/competitor symbols for a company.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.PEERS, fh.SymbolRequest(symbol))


# ═══════════════════════════════════════════════════════════════
# FMP — Fundamental Financial Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_company_profile(ctx: Context, symbol: str) -> str:
    """Get company profile: name, price, market cap, beta, avg volume, last dividend,
    52-week range, sector, industry, exchange, and CEO.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.PROFILE, fmp.SymbolRequest(symbol))


@mcp.tool()
def get_income_statement(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get income statement: revenue, gross profit, operating income, net income, EPS, EBITDA.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.INCOME_STATEMENT, fmp.FinancialRequest(symbol, period, limit))


@mcp.tool()
def get_balance_sheet(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get balance sheet: total assets, liabilities, equity, cash, debt.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.BALANCE_SHEET, fmp.FinancialRequest(symbol, period, limit))


@mcp.tool()
def get_cash_flow(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get cash flow statement: operating cash flow, capex, free cash flow, dividends, buybacks.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.CASH_FLOW, fmp.FinancialRequest(symbol, period, limit))


@mcp.tool()
def get_key_metrics(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get key financial metrics: EV/EBITDA, ROE, ROA, current ratio, debt/equity, FCF yield.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.KEY_METRICS, fmp.FinancialRequest(symbol, period, limit))


@mcp.tool()
def get_dividend_history(ctx: Context, symbol: str) -> str:
    """Get full dividend payment history: ex-date, pay date, record date, amount.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.DIVIDEND_HISTORY, fmp.SymbolRequest(symbol))


@mcp.tool()
def get_fmp_earnings_calendar(ctx: Context, symbol: str, limit: int = 5) -> str:
    """Get earnings history: date, EPS estimate/actual, revenue estimate/actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.EARNINGS, fmp.EarningsRequest(symbol, limit))


# ═══════════════════════════════════════════════════════════════
# FRED — Macroeconomic Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_economic_data(
    ctx: Context, series_id: str, limit: int = 12, sort_order: str = "desc"
) -> str:
    """Get historical values for a FRED economic data series.

    series_id: FRED series ID. Common: 'CPIAUCSL' (CPI), 'GDP', 'UNRATE',
      'FEDFUNDS', 'T10Y2Y' (yield curve), 'VIXCLS' (VIX), 'PAYEMS' (payrolls),
      'UMCSENT' (sentiment), 'DGS10' (10Y yield).
    limit: number of most recent observations (default 12).
    sort_order: 'desc' (newest first) or 'asc'.

    Requires [fred] section in ~/.tradingrc.
    """
    req = fred.GetObservationsRequest(series_id, limit, sort_order)
    return _fred(ctx).get(fred.OBSERVATIONS, req)


@mcp.tool()
def get_fred_series_info(ctx: Context, series_id: str) -> str:
    """Get metadata for a FRED series: title, frequency, units, seasonal adjustment.

    series_id: FRED series ID (e.g. 'CPIAUCSL', 'GDP', 'VIXCLS').
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.SERIES_INFO, fred.SeriesIdRequest(series_id))


@mcp.tool()
def get_upcoming_economic_releases(ctx: Context, limit: int = 20) -> str:
    """Get upcoming FRED data release dates: when CPI, GDP, jobs report will be published.

    limit: number of upcoming releases to return (default 20).
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.RELEASES, fred.GetReleasesRequest(limit))


@mcp.tool()
def search_fred_series(ctx: Context, query: str, limit: int = 10) -> str:
    """Search for FRED economic data series by keyword.

    query: search terms (e.g. 'inflation', 'housing starts', 'consumer credit').
    limit: max results to return (default 10).

    Use the returned series_id with get_economic_data to fetch actual values.
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.SEARCH, fred.SearchRequest(query, limit))


# ═══════════════════════════════════════════════════════════════
# ALPHA VANTAGE — News Sentiment, Market Movers
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_news_sentiment(
    ctx: Context,
    tickers: str | None = None,
    topics: str | None = None,
    limit: int = 10,
) -> str:
    """Get news articles with AI-generated sentiment scores per ticker.

    tickers: comma-separated symbols to filter by (e.g. 'AAPL,TSLA'). Omit for broad news.
    topics: comma-separated topic filters — 'earnings', 'ipo', 'mergers_and_acquisitions',
      'financial_markets', 'technology', etc. Omit for all topics.
    limit: max articles to return (default 10, max 50).

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return _alphavantage(ctx).get(av.SENTIMENT, av.SentimentRequest(tickers, topics, limit=limit))


@mcp.tool()
def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks.

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return _alphavantage(ctx).get(av.MOVERS, av.MoversRequest())


# ═══════════════════════════════════════════════════════════════


def main():
    mcp.run()


if __name__ == "__main__":
    main()
