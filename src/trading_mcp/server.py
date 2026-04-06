from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from trading_mcp.alphavantage_client import AlphaVantageClient
from trading_mcp.config import load_config
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


# ═══════════════════════════════════════════════════════════════
# WEBULL — Brokerage (Account, Orders, Market Data)
# ═══════════════════════════════════════════════════════════════

# ── Account ──────────────────────────────────────────────────


@mcp.tool()
def get_account_profile(ctx: Context, account_id: str | None = None) -> str:
    """Get account profile: account number, account type, and registration details.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    Use get_app_subscriptions to list all accounts and their IDs.
    """
    return _webull(ctx).get_account_profile(account_id)


@mcp.tool()
def get_account_balance(ctx: Context, currency: str = "USD", account_id: str | None = None) -> str:
    """Get account balance: total assets, cash, buying power, market value, unrealized P&L.

    currency: the currency to report total assets in. Defaults to 'USD'.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).get_account_balance(currency, account_id)


@mcp.tool()
def get_account_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get all current portfolio holdings. Returns each position's symbol, instrument_id,
    quantity, cost basis, market value, and unrealized P&L. Automatically paginates to
    fetch all positions.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).get_account_positions(account_id)


# ── Orders ───────────────────────────────────────────────────


@mcp.tool()
def get_open_orders(ctx: Context, page_size: int = 100, account_id: str | None = None) -> str:
    """Get all currently open/pending orders. Returns each order's client_order_id,
    instrument_id, side, order_type, qty, status, limit_price, and time in force.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).get_open_orders(page_size, account_id=account_id)


@mcp.tool()
def get_today_orders(ctx: Context, page_size: int = 100, account_id: str | None = None) -> str:
    """Get all orders placed today, including filled, cancelled, and pending.
    Returns each order's client_order_id, status, side, qty, filled_qty, and price.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).get_today_orders(page_size, account_id=account_id)


@mcp.tool()
def get_order_detail(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Get full detail for a specific order including status, fill info, and timestamps.

    client_order_id: the unique order ID assigned when the order was placed.
    Use get_open_orders or get_today_orders to find client_order_ids.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).get_order_detail(client_order_id, account_id)


# ── Stock Order Management ───────────────────────────────────


@mcp.tool()
def preview_order(ctx: Context, new_orders: list[dict], account_id: str | None = None) -> str:
    """Preview a stock order before placing it. Returns estimated cost, margin impact,
    and buying power effect without actually submitting the order.

    Note: currently available for JP/HK accounts only — US support expected in the future.

    new_orders: list of order dicts. Each dict should contain:
      - instrument_id: str (get from get_instruments)
      - side: 'BUY' or 'SELL'
      - order_type: 'MARKET', 'LIMIT', 'STOP', or 'STOP_LIMIT'
      - qty: int
      - tif: 'DAY', 'GTC', 'IOC', or 'FOK'
      - limit_price: str (required for LIMIT and STOP_LIMIT)
      - stop_price: str (required for STOP and STOP_LIMIT)
    """
    return _webull(ctx).preview_order(new_orders, account_id)


@mcp.tool()
def place_order(
    ctx: Context,
    instrument_id: str,
    side: str,
    order_type: str,
    qty: int,
    client_order_id: str,
    tif: str,
    account_id: str | None = None,
    extended_hours_trading: bool = False,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
) -> str:
    """Place a stock order.

    instrument_id: Webull instrument ID (get from get_instruments).
    side: 'BUY' or 'SELL'.
    order_type: 'MARKET', 'LIMIT', 'STOP', or 'STOP_LIMIT'.
    qty: number of shares.
    client_order_id: unique ID you generate for this order (use a UUID).
    tif: time in force — 'DAY', 'GTC' (good til cancelled), 'IOC', or 'FOK'.
    extended_hours_trading: set True to allow pre/post-market execution.
    limit_price: required for LIMIT and STOP_LIMIT orders (e.g. '150.50').
    stop_price: required for STOP and STOP_LIMIT orders (e.g. '148.00').
    trailing_type: 'AMOUNT' or 'PERCENTAGE' for trailing stop orders.
    trailing_stop_step: the trailing amount or percentage (e.g. '1.00' or '2.5').
    """
    return _webull(ctx).place_order(
        {
            "client_order_id": client_order_id,
            "instrument_id": instrument_id,
            "qty": qty,
            "side": side,
            "tif": tif,
            "extended_hours_trading": extended_hours_trading,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "trailing_type": trailing_type,
            "trailing_stop_step": trailing_stop_step,
        },
        account_id,
    )


@mcp.tool()
def replace_order(
    ctx: Context,
    client_order_id: str,
    instrument_id: str,
    side: str,
    order_type: str,
    qty: int,
    tif: str,
    account_id: str | None = None,
    extended_hours_trading: bool = False,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
) -> str:
    """Modify a pending stock order that has not yet been filled. Provide the existing
    client_order_id of the order to modify, along with the full updated order parameters.

    All fields from place_order apply. You must re-specify all order parameters, not just
    the ones you want to change. The order must still be in a pending/open state.
    """
    return _webull(ctx).replace_order(
        {
            "client_order_id": client_order_id,
            "instrument_id": instrument_id,
            "qty": qty,
            "side": side,
            "tif": tif,
            "extended_hours_trading": extended_hours_trading,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "trailing_type": trailing_type,
            "trailing_stop_step": trailing_stop_step,
        },
        account_id,
    )


@mcp.tool()
def cancel_order(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending stock order. The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable orders.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).cancel_order(client_order_id, account_id)


# ── Option Order Management ──────────────────────────────────


@mcp.tool()
def preview_option(ctx: Context, new_orders: list[dict], account_id: str | None = None) -> str:
    """Preview an option order before placing it. Returns estimated cost, margin impact,
    and buying power effect without actually submitting the order.

    Note: currently available for HK accounts only — US support expected in the future.

    new_orders: list of order groups. Each group is a dict containing:
      - orders: list of leg dicts, each with:
          - instrument_id: str (resolve via get_security_detail with instrument_super_type
            ='OPTION', instrument_type='CALL_OPTION' or 'PUT_OPTION', strike_price,
            and init_exp_date)
          - side: 'BUY' or 'SELL'
          - order_type: 'MARKET' or 'LIMIT'
          - qty: int (number of contracts)
          - limit_price: str (required for LIMIT orders, price per contract)
      - tif: 'DAY' or 'GTC'

    Single-leg example: [{"orders": [{"instrument_id": "...", "side": "BUY",
      "order_type": "LIMIT", "qty": 1, "limit_price": "3.50"}], "tif": "DAY"}]

    Multi-leg (e.g. vertical spread): one group with multiple legs at different strikes.
    """
    return _webull(ctx).preview_option(new_orders, account_id)


@mcp.tool()
def place_option(ctx: Context, new_orders: list[dict], account_id: str | None = None) -> str:
    """Place an option order (single-leg or multi-leg).

    Note: currently available for HK accounts only — US support expected in the future.

    new_orders: list of order groups. Each group is a dict containing:
      - orders: list of leg dicts, each with:
          - instrument_id: str (resolve via get_security_detail with instrument_super_type
            ='OPTION', instrument_type='CALL_OPTION' or 'PUT_OPTION', strike_price,
            and init_exp_date)
          - side: 'BUY' or 'SELL'
          - order_type: 'MARKET' or 'LIMIT'
          - qty: int (number of contracts)
          - limit_price: str (required for LIMIT orders, price per contract)
      - tif: 'DAY' or 'GTC'

    Single-leg example: [{"orders": [{"instrument_id": "...", "side": "BUY",
      "order_type": "LIMIT", "qty": 1, "limit_price": "3.50"}], "tif": "DAY"}]

    Multi-leg (e.g. bull call spread): use one group with two legs — buy the lower
    strike call and sell the higher strike call, same expiration.
    """
    return _webull(ctx).place_option(new_orders, account_id)


@mcp.tool()
def replace_option(ctx: Context, modify_orders: list[dict], account_id: str | None = None) -> str:
    """Modify a pending option order that has not yet been filled.

    modify_orders: list of modification dicts. Each dict should contain:
      - client_order_id: str (the ID of the existing order to modify)
      - orders: list of updated leg dicts (same structure as place_option)
      - tif: 'DAY' or 'GTC'
    All order parameters must be re-specified, not just the changed ones.
    """
    return _webull(ctx).replace_option(modify_orders, account_id)


@mcp.tool()
def cancel_option(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending option order. The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable option orders.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    return _webull(ctx).cancel_option(client_order_id, account_id)


# ── Trade Info ───────────────────────────────────────────────


@mcp.tool()
def get_trade_calendar(ctx: Context, market: str, start: str, end: str) -> str:
    """Get trading calendar showing which days the market is open or closed.

    market: market code, e.g. 'US' for US stock exchanges.
    start: start date (YYYY-MM-DD).
    end: end date (YYYY-MM-DD).
    Returns a list of dates with their open/closed status.
    """
    return _webull(ctx).get_trade_calendar(market, start, end)


@mcp.tool()
def get_trade_instrument_detail(ctx: Context, instrument_id: str) -> str:
    """Get detailed instrument metadata by instrument ID, including symbol, exchange,
    currency, instrument type, and trading status.

    instrument_id: the Webull instrument ID (get from get_instruments, get_security_detail,
    or get_account_positions).
    """
    return _webull(ctx).get_trade_instrument_detail(instrument_id)


@mcp.tool()
def get_app_subscriptions(ctx: Context) -> str:
    """Get API app subscription details: subscription ID, status, plan type, and
    which market data feeds are active.
    """
    return _webull(ctx).get_app_subscriptions()


# ── Webull Market Data ──────────────────────────────────────


@mcp.tool()
def get_quote(ctx: Context, symbols: str) -> str:
    """Get real-time snapshot quotes: last price, bid/ask, volume, day change, and
    52-week high/low.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA,MSFT').
    Results are not cached — each call fetches live data.
    """
    return _webull(ctx).get_quote(symbols)


@mcp.tool()
def get_instruments(ctx: Context, symbols: str) -> str:
    """Look up instrument IDs, exchange, currency, and instrument type for symbols.
    Use this to resolve ticker symbols to instrument_ids needed by other tools
    (place_order, get_historical_bars, get_eod_bars, etc.).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA').
    category: 'US_STOCK' (default), 'US_OPTION', 'HK_STOCK', etc.
    """
    return _webull(ctx).get_instruments(symbols)


@mcp.tool()
def get_historical_bars(
    ctx: Context,
    symbol: str,
    timespan: str,
    count: int = 200,
    category: str = "US_STOCK",
    trading_sessions: str | None = None,
) -> str:
    """Get historical OHLCV candlestick bars for a single symbol.

    symbol: ticker symbol (e.g. 'AAPL').
    timespan: bar interval — 'M1' (1 min), 'M5', 'M15', 'M30', 'M60' (1 hour),
      'M120' (2 hours), 'M240' (4 hours), 'D' (daily), 'W' (weekly), 'M' (monthly),
      'Y' (yearly).
    count: number of bars to return (default 200, max varies by timespan).
    category: 'US_STOCK' (default), 'US_OPTION', 'HK_STOCK', etc.
    trading_sessions: set to 'pre_market', 'after_hours', or 'pre_market,after_hours'
      to include extended hours data. Omit for regular hours only.
    """
    return _webull(ctx).get_historical_bars(symbol, timespan, count, category, trading_sessions)


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
    return _tradier(ctx).get_option_expirations(symbol)


@mcp.tool()
def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_option_strikes(symbol, expiration)


@mcp.tool()
def get_option_chain(
    ctx: Context,
    symbol: str,
    expiration: str,
    greeks: bool = True,
) -> str:
    """Get the full option chain for an underlying symbol at a specific expiration.
    Returns all calls and puts with bid/ask, last price, volume, open interest,
    and optionally greeks (delta, gamma, theta, vega, rho) and implied volatility.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    greeks: include greeks and IV per contract (default True).

    Typical workflow:
    1. get_option_expirations('AAPL') → list of dates
    2. get_option_chain('AAPL', '2026-04-17') → full chain with greeks

    Note: Tradier sandbox data is delayed ~15 minutes.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_option_chain(symbol, expiration, greeks)


@mcp.tool()
def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_option_lookup(underlying)


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
    return _tradier(ctx).get_history(symbol, interval, start, end)


@mcp.tool()
def search_symbols(ctx: Context, query: str, indexes: bool = False) -> str:
    """Search for stocks and ETFs by company name or partial symbol. Results are sorted
    by average volume (most liquid first). Useful for stock discovery.

    query: search term — company name or partial symbol (e.g. 'apple', 'semi', 'AI').
    indexes: set True to include index symbols in results.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).search_symbols(query, indexes)


@mcp.tool()
def get_tradier_quote(ctx: Context, symbols: str, greeks: bool = False) -> str:
    """Get real-time quotes for stocks or option contracts. When greeks=True, option
    quotes include delta, gamma, theta, vega, and implied volatility.

    symbols: comma-separated ticker symbols or OCC option symbols
      (e.g. 'AAPL,TSLA' or 'AAPL260417C00260000').
    greeks: include greeks and IV for option symbols (default False).

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_quotes(symbols, greeks)


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

    symbol: ticker or OCC option symbol (e.g. 'AAPL' or 'AAPL260417C00260000').
    interval: tick interval — '1min', '5min', '15min'. Default '5min'.
    start: start datetime (YYYY-MM-DD HH:MM). Defaults to market open today.
    end: end datetime (YYYY-MM-DD HH:MM). Defaults to now.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_timesales(symbol, interval, start, end)


@mcp.tool()
def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_clock()


# ── Tradier Account ─────────────────────────────────────────


@mcp.tool()
def get_tradier_profile(ctx: Context) -> str:
    """Get Tradier user profile with all linked accounts. Returns account number,
    type, classification, option level, and day trader status for each account.

    Use this to find your Tradier account_id.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_user_profile()


@mcp.tool()
def get_tradier_balances(ctx: Context, account_id: str | None = None) -> str:
    """Get Tradier account balance: total equity, cash, market value, option value,
    buying power.

    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_tradier_balances(account_id)


@mcp.tool()
def get_tradier_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get current positions in a Tradier account: symbol, quantity, cost basis,
    and date acquired.

    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_tradier_positions(account_id)


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
    return _tradier(ctx).get_tradier_orders(status, page, limit, account_id)


@mcp.tool()
def get_tradier_order_detail(ctx: Context, order_id: str, account_id: str | None = None) -> str:
    """Get full detail for a specific Tradier order.

    order_id: the numeric order ID (from get_tradier_orders).
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_tradier_order_detail(order_id, account_id)


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

    sort_by: 'closedate', 'opendate', 'symbol', or 'gainloss'.
    sort: 'asc' or 'desc'.
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get_tradier_gainloss(page, limit, sort_by, sort, account_id)


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
    return _tradier(ctx).get_tradier_history(page, limit, activity_type, account_id)


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
    params = {k: str(v) for k, v in order_params.items()}
    return _tradier(ctx).place_tradier_order(params, account_id)


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
    params = {k: str(v) for k, v in modifications.items()}
    return _tradier(ctx).modify_tradier_order(order_id, params, account_id)


@mcp.tool()
def cancel_tradier_order(ctx: Context, order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending Tradier order.

    order_id: the numeric order ID (from get_tradier_orders).
    account_id: Tradier account number. Omit to use the default from ~/.tradingrc.
    """
    return _tradier(ctx).cancel_tradier_order(order_id, account_id)


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
    Returns a list of articles with headline, source, and datetime.

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_company_news(symbol, from_date, to_date, limit)


@mcp.tool()
def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).
    Returns a list of articles with headline, source, and datetime.

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_market_news(category, limit)


@mcp.tool()
def get_economic_calendar(ctx: Context, from_date: str, to_date: str) -> str:
    """Get upcoming economic events: FOMC meetings, CPI releases, jobs reports, GDP, etc.

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    Returns events with: event name, country, date/time, actual value, estimate,
    previous value, and impact level (low/medium/high).

    Note: requires Finnhub premium plan. Free tier returns 403.
    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_economic_calendar(from_date, to_date)


@mcp.tool()
def get_earnings_calendar(ctx: Context, from_date: str, to_date: str, limit: int = 50) -> str:
    """Get upcoming and recent earnings reports. Automatically filters out micro-caps
    (companies with no analyst coverage).

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    limit: max number of entries to return (default 50).
    Returns each report's symbol, date, EPS actual, EPS estimate, revenue actual,
    revenue estimate, and reporting time (bmo=before market open, amc=after market close).

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_earnings_calendar(from_date, to_date, limit)


@mcp.tool()
def get_basic_financials(ctx: Context, symbol: str) -> str:
    """Get key financial metrics: P/E ratio, P/B ratio, EPS, dividend yield, 52-week
    high/low, market cap, beta, ROE, debt/equity, and dozens more.

    symbol: ticker symbol (e.g. 'AAPL').
    Returns a dict with 'metric' (current values) and 'series' (quarterly/annual history).

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_basic_financials(symbol)


@mcp.tool()
def get_eps_estimates(ctx: Context, symbol: str) -> str:
    """Get analyst EPS estimates for upcoming quarters: average, high, low, and number
    of analysts.

    symbol: ticker symbol (e.g. 'AAPL').

    Note: requires Finnhub premium plan. Free tier returns 403.
    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_eps_estimates(symbol)


@mcp.tool()
def get_recommendation_trends(ctx: Context, symbol: str) -> str:
    """Get analyst recommendation trends: counts of strong buy, buy, hold, sell, and
    strong sell ratings by month.

    symbol: ticker symbol (e.g. 'AAPL').

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_recommendation_trends(symbol)


@mcp.tool()
def get_price_target(ctx: Context, symbol: str) -> str:
    """Get analyst consensus price target: high, low, mean, and median target prices.

    symbol: ticker symbol (e.g. 'AAPL').

    Note: requires Finnhub premium plan. Free tier returns 403.
    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_price_target(symbol)


@mcp.tool()
def get_insider_transactions(ctx: Context, symbol: str, limit: int = 20) -> str:
    """Get recent insider transactions: buys, sells, and grants by company officers
    and directors. Insider buying is one of the strongest bullish signals.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: max number of transactions to return (default 20).

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_insider_transactions(symbol, limit)


@mcp.tool()
def get_dividends(ctx: Context, symbol: str, from_date: str, to_date: str) -> str:
    """Get dividend history for a specific company: ex-date, pay date, record date, and amount.
    Essential for covered call strategies — avoid selling calls through ex-dividend dates.

    symbol: ticker symbol (e.g. 'AAPL').
    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).

    Note: requires Finnhub premium plan. Free tier returns 403.
    Use get_dividend_history (FMP) as a free alternative.
    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_dividends(symbol, from_date, to_date)


@mcp.tool()
def get_company_peers(ctx: Context, symbol: str) -> str:
    """Get a list of peer/competitor symbols for a company, useful for comparative
    valuation analysis.

    symbol: ticker symbol (e.g. 'AAPL').

    Rate limit: 60 requests/min (shared across all Finnhub tools).
    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get_company_peers(symbol)


# ═══════════════════════════════════════════════════════════════
# FMP — Fundamental Financial Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_company_profile(ctx: Context, symbol: str) -> str:
    """Get company profile: name, price, market cap, beta, avg volume, last dividend,
    52-week range, sector, industry, exchange, and CEO.

    symbol: ticker symbol (e.g. 'AAPL').

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_company_profile(symbol)


@mcp.tool()
def get_income_statement(
    ctx: Context,
    symbol: str,
    period: str = "annual",
    limit: int = 4,
) -> str:
    """Get income statement: revenue, gross profit, operating income, net income, EPS,
    EBITDA, and all line items.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_income_statement(symbol, period, limit)


@mcp.tool()
def get_balance_sheet(
    ctx: Context,
    symbol: str,
    period: str = "annual",
    limit: int = 4,
) -> str:
    """Get balance sheet: total assets, liabilities, equity, cash, debt, inventory,
    and all line items.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_balance_sheet(symbol, period, limit)


@mcp.tool()
def get_cash_flow(
    ctx: Context,
    symbol: str,
    period: str = "annual",
    limit: int = 4,
) -> str:
    """Get cash flow statement: operating cash flow, capex, free cash flow, dividends
    paid, share buybacks, and all line items.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_cash_flow(symbol, period, limit)


@mcp.tool()
def get_key_metrics(
    ctx: Context,
    symbol: str,
    period: str = "annual",
    limit: int = 4,
) -> str:
    """Get key financial metrics over time: revenue per share, net income per share,
    P/E, P/B, P/S, EV/EBITDA, debt/equity, ROE, ROA, current ratio, and more.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_key_metrics(symbol, period, limit)


@mcp.tool()
def get_dividend_history(ctx: Context, symbol: str) -> str:
    """Get full dividend payment history for a specific company: ex-date, pay date,
    record date, declaration date, dividend amount, and adjusted dividend.

    symbol: ticker symbol (e.g. 'AAPL').

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_dividend_history(symbol)


@mcp.tool()
def get_fmp_earnings_calendar(
    ctx: Context,
    symbol: str,
    limit: int = 5,
) -> str:
    """Get earnings history for a specific company from FMP: date, EPS estimate, EPS actual,
    revenue estimate, revenue actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5, max 5 on free tier).

    Rate limit: 250 requests/day (shared across all FMP tools).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get_earnings_calendar(symbol, limit)


# ═══════════════════════════════════════════════════════════════
# FRED — Macroeconomic Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_economic_data(
    ctx: Context,
    series_id: str,
    limit: int = 12,
    sort_order: str = "desc",
) -> str:
    """Get historical values for a FRED economic data series.

    series_id: FRED series ID. Common series:
      - 'CPIAUCSL' — Consumer Price Index (CPI, monthly)
      - 'GDP' — Gross Domestic Product (quarterly)
      - 'UNRATE' — Unemployment Rate (monthly)
      - 'FEDFUNDS' — Federal Funds Rate (monthly)
      - 'T10Y2Y' — 10Y-2Y Treasury Yield Spread (daily, yield curve)
      - 'VIXCLS' — CBOE VIX Volatility Index (daily)
      - 'PAYEMS' — Nonfarm Payrolls (monthly)
      - 'UMCSENT' — Consumer Sentiment (monthly)
      - 'DGS10' — 10-Year Treasury Yield (daily)
    limit: number of most recent observations to return (default 12).
    sort_order: 'desc' (newest first) or 'asc' (oldest first).

    Use search_fred_series to find other series by keyword.
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get_series_observations(series_id, limit, sort_order)


@mcp.tool()
def get_fred_series_info(ctx: Context, series_id: str) -> str:
    """Get metadata for a FRED series: title, frequency, units, seasonal adjustment,
    last updated date, and description.

    series_id: FRED series ID (e.g. 'CPIAUCSL', 'GDP', 'VIXCLS').

    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get_series_info(series_id)


@mcp.tool()
def get_upcoming_economic_releases(ctx: Context, limit: int = 20) -> str:
    """Get upcoming FRED data release dates: when the next CPI, GDP, jobs report,
    and other economic data will be published.

    limit: number of upcoming releases to return (default 20).

    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get_upcoming_releases(limit)


@mcp.tool()
def search_fred_series(ctx: Context, query: str, limit: int = 10) -> str:
    """Search for FRED economic data series by keyword. Returns series ID, title,
    frequency, units, and description for each match.

    query: search terms (e.g. 'inflation', 'housing starts', 'consumer credit').
    limit: max results to return (default 10).

    Use the returned series_id with get_economic_data to fetch actual values.
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).search_series(query, limit)


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

    Each article includes: title, summary, source, url, overall_sentiment_score (-1 to 1),
    overall_sentiment_label (Bearish/Somewhat-Bearish/Neutral/Somewhat-Bullish/Bullish),
    and per-ticker sentiment with relevance scores.

    tickers: comma-separated symbols to filter by (e.g. 'AAPL,TSLA'). Omit for broad news.
    topics: comma-separated topic filters — 'earnings', 'ipo', 'mergers_and_acquisitions',
      'financial_markets', 'economy_fiscal', 'economy_monetary', 'economy_macro',
      'energy_transportation', 'finance', 'technology', etc. Omit for all topics.
    limit: max articles to return (default 10, max 50).

    Rate limit: 25 requests/day (shared across all Alpha Vantage tools). Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return _alphavantage(ctx).get_news_sentiment(tickers, topics, limit=limit)


@mcp.tool()
def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks. Each entry includes ticker, price, change amount, change %, and volume.

    Rate limit: 25 requests/day (shared across all Alpha Vantage tools). Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return _alphavantage(ctx).get_top_gainers_losers()


# ═══════════════════════════════════════════════════════════════


def main():
    mcp.run()


if __name__ == "__main__":
    main()
