from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from trading_mcp.config import load_config
from trading_mcp.webull_client import WebullClient


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    config = load_config()
    client = WebullClient(config)
    yield {"client": client}


mcp = FastMCP("trading-mcp", lifespan=lifespan)


def _client(ctx: Context) -> WebullClient:
    return ctx.request_context.lifespan_context["client"]


# ── Account ──────────────────────────────────────────────────


@mcp.tool()
def get_account_profile(ctx: Context) -> dict:
    """Get account profile: account number, account type, and registration details."""
    return _client(ctx).get_account_profile()


@mcp.tool()
def get_account_balance(ctx: Context, currency: str = "USD") -> dict:
    """Get account balance: total assets, cash, buying power, market value, unrealized P&L.

    currency: the currency to report total assets in. Defaults to 'USD'.
    """
    return _client(ctx).get_account_balance(currency)


@mcp.tool()
def get_account_positions(ctx: Context) -> list[dict]:
    """Get all current portfolio holdings. Returns each position's symbol, instrument_id,
    quantity, cost basis, market value, and unrealized P&L. Automatically paginates to
    fetch all positions.
    """
    return _client(ctx).get_account_positions()


@mcp.tool()
def get_account_position_details(instrument_id: str, ctx: Context, size: int = 20) -> dict:
    """Get detailed position info for a specific instrument, including individual lots
    with open date, quantity, and cost basis per lot.

    instrument_id: the Webull instrument ID (get this from get_account_positions or
    get_instruments).
    size: max number of lots to return per page (default 20).
    """
    return _client(ctx).get_account_position_details(instrument_id, size)


# ── Orders ───────────────────────────────────────────────────


@mcp.tool()
def get_open_orders(ctx: Context, page_size: int = 100) -> dict:
    """Get all currently open/pending orders. Returns each order's client_order_id,
    instrument_id, side, order_type, qty, status, limit_price, and time in force.
    """
    return _client(ctx).get_open_orders(page_size)


@mcp.tool()
def get_today_orders(ctx: Context, page_size: int = 100) -> dict:
    """Get all orders placed today, including filled, cancelled, and pending.
    Returns each order's client_order_id, status, side, qty, filled_qty, and price.
    """
    return _client(ctx).get_today_orders(page_size)


@mcp.tool()
def get_order_detail(client_order_id: str, ctx: Context) -> dict:
    """Get full detail for a specific order including status, fill info, and timestamps.

    client_order_id: the unique order ID assigned when the order was placed.
    Use get_open_orders or get_today_orders to find client_order_ids.
    """
    return _client(ctx).get_order_detail(client_order_id)


@mcp.tool()
def get_order_history(
    ctx: Context,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 100,
) -> dict:
    """Get historical orders for up to the past 7 days. Includes filled, cancelled,
    and expired orders not shown in get_today_orders.

    start_date: earliest date to include (YYYY-MM-DD). Defaults to 7 days ago.
    end_date: latest date to include (YYYY-MM-DD). Defaults to today.
    """
    return _client(ctx).get_order_history(start_date, end_date, page_size)


# ── Stock Order Management ───────────────────────────────────


@mcp.tool()
def preview_order(new_orders: list[dict], ctx: Context) -> dict:
    """Preview a stock order before placing it. Returns estimated cost, margin impact,
    and buying power effect without actually submitting the order.

    Note: currently available for JP/HK accounts only — US support expected in the future.

    new_orders: list of order dicts. Each dict should contain:
      - instrument_id: str (get from get_instruments or get_security_detail)
      - side: 'BUY' or 'SELL'
      - order_type: 'MARKET', 'LIMIT', 'STOP', or 'STOP_LIMIT'
      - qty: int
      - tif: 'DAY', 'GTC', 'IOC', or 'FOK'
      - limit_price: str (required for LIMIT and STOP_LIMIT)
      - stop_price: str (required for STOP and STOP_LIMIT)
    """
    return _client(ctx).preview_order(new_orders)


@mcp.tool()
def place_order(
    instrument_id: str,
    side: str,
    order_type: str,
    qty: int,
    client_order_id: str,
    tif: str,
    ctx: Context,
    extended_hours_trading: bool = False,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
) -> dict:
    """Place a stock order.

    instrument_id: Webull instrument ID (get from get_instruments or get_security_detail).
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
    return _client(ctx).place_order(
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
        }
    )


@mcp.tool()
def replace_order(
    client_order_id: str,
    instrument_id: str,
    side: str,
    order_type: str,
    qty: int,
    tif: str,
    ctx: Context,
    extended_hours_trading: bool = False,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
) -> dict:
    """Modify a pending stock order that has not yet been filled. Provide the existing
    client_order_id of the order to modify, along with the full updated order parameters.

    All fields from place_order apply. You must re-specify all order parameters, not just
    the ones you want to change. The order must still be in a pending/open state.
    """
    return _client(ctx).replace_order(
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
        }
    )


@mcp.tool()
def cancel_order(client_order_id: str, ctx: Context) -> dict:
    """Cancel a pending stock order. The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable orders.
    """
    return _client(ctx).cancel_order(client_order_id)


# ── Option Order Management ──────────────────────────────────


@mcp.tool()
def preview_option(new_orders: list[dict], ctx: Context) -> dict:
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
    return _client(ctx).preview_option(new_orders)


@mcp.tool()
def place_option(new_orders: list[dict], ctx: Context) -> dict:
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
    return _client(ctx).place_option(new_orders)


@mcp.tool()
def replace_option(modify_orders: list[dict], ctx: Context) -> dict:
    """Modify a pending option order that has not yet been filled.

    modify_orders: list of modification dicts. Each dict should contain:
      - client_order_id: str (the ID of the existing order to modify)
      - orders: list of updated leg dicts (same structure as place_option)
      - tif: 'DAY' or 'GTC'
    All order parameters must be re-specified, not just the changed ones.
    """
    return _client(ctx).replace_option(modify_orders)


@mcp.tool()
def cancel_option(client_order_id: str, ctx: Context) -> dict:
    """Cancel a pending option order. The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable option orders.
    """
    return _client(ctx).cancel_option(client_order_id)


# ── Trade Info ───────────────────────────────────────────────


@mcp.tool()
def get_trade_calendar(market: str, start: str, end: str, ctx: Context) -> dict:
    """Get trading calendar showing which days the market is open or closed.

    market: market code, e.g. 'US' for US stock exchanges.
    start: start date (YYYY-MM-DD).
    end: end date (YYYY-MM-DD).
    Returns a list of dates with their open/closed status.
    """
    return _client(ctx).get_trade_calendar(market, start, end)


@mcp.tool()
def get_trade_instrument_detail(instrument_id: str, ctx: Context) -> dict:
    """Get detailed instrument metadata by instrument ID, including symbol, exchange,
    currency, instrument type, and trading status.

    instrument_id: the Webull instrument ID (get from get_instruments, get_security_detail,
    or get_account_positions).
    """
    return _client(ctx).get_trade_instrument_detail(instrument_id)


@mcp.tool()
def get_security_detail(
    symbol: str,
    ctx: Context,
    market: str = "US",
    instrument_super_type: str | None = None,
    instrument_type: str | None = None,
    strike_price: str | None = None,
    init_exp_date: str | None = None,
) -> dict:
    """Look up a security and get its instrument_id, which is required for placing orders
    and querying position details.

    For stocks: just provide the symbol (e.g. 'AAPL').
    For option contracts: also set:
      - instrument_super_type: 'OPTION'
      - instrument_type: 'CALL_OPTION' or 'PUT_OPTION'
      - strike_price: strike as a string (e.g. '150.00')
      - init_exp_date: expiration date (YYYY-MM-DD, e.g. '2026-04-17')

    This is the primary way to resolve an option contract to its instrument_id.
    The Webull API does not have an option chain endpoint, so you must know the
    underlying symbol, strike, and expiration to look up a specific contract.

    market: market code, defaults to 'US'.
    """
    return _client(ctx).get_security_detail(
        symbol, market, instrument_super_type, instrument_type, strike_price, init_exp_date
    )


@mcp.tool()
def get_tradeable_instruments(ctx: Context, page_size: int = 100) -> dict:
    """List all instruments available for trading on the account, paginated.
    Returns instrument IDs, symbols, and instrument types. Useful for discovering
    what securities are tradeable.
    """
    return _client(ctx).get_tradeable_instruments(page_size)


@mcp.tool()
def get_app_subscriptions(ctx: Context) -> dict:
    """Get API app subscription details: subscription ID, status, plan type, and
    which market data feeds are active.
    """
    return _client(ctx).get_app_subscriptions()


# ── Market Data ──────────────────────────────────────────────


@mcp.tool()
def get_quote(symbols: str, ctx: Context) -> list[dict]:
    """Get real-time snapshot quotes: last price, bid/ask, volume, day change, and
    52-week high/low.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA,MSFT').
    Results are not cached — each call fetches live data.
    """
    return _client(ctx).get_quote(symbols)


@mcp.tool()
def get_instruments(symbols: str, ctx: Context) -> list[dict]:
    """Look up instrument IDs, exchange, currency, and instrument type for symbols.
    Use this to resolve ticker symbols to instrument_ids needed by other tools
    (place_order, get_historical_bars, get_eod_bars, etc.).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA').
    category: 'US_STOCK' (default), 'US_OPTION', 'HK_STOCK', etc.
    """
    return _client(ctx).get_instruments(symbols)


@mcp.tool()
def get_historical_bars(
    symbol: str,
    timespan: str,
    ctx: Context,
    count: int = 200,
    category: str = "US_STOCK",
    trading_sessions: str | None = None,
) -> dict:
    """Get historical OHLCV candlestick bars for a single symbol.

    symbol: ticker symbol (e.g. 'AAPL').
    timespan: bar interval — 'm1' (1 min), 'm5', 'm15', 'm30', 'h1', 'h2', 'h4',
      'd1' (daily), 'w1' (weekly).
    count: number of bars to return (default 200, max varies by timespan).
    category: 'US_STOCK' (default), 'US_OPTION', 'HK_STOCK', etc.
    trading_sessions: set to 'pre_market', 'after_hours', or 'pre_market,after_hours'
      to include extended hours data. Omit for regular hours only.
    """
    return _client(ctx).get_historical_bars(symbol, timespan, count, category, trading_sessions)


@mcp.tool()
def get_batch_historical_bars(
    symbols: str,
    timespan: str,
    ctx: Context,
    count: int = 200,
    category: str = "US_STOCK",
    trading_sessions: str | None = None,
) -> dict:
    """Get historical OHLCV bars for multiple symbols in a single request.
    Same bar data as get_historical_bars but batched.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA,MSFT').
    timespan: bar interval — 'm1', 'm5', 'm15', 'm30', 'h1', 'h2', 'h4', 'd1', 'w1'.
    count: number of bars per symbol (default 200).
    category: 'US_STOCK' (default), 'US_OPTION', 'HK_STOCK', etc.
    trading_sessions: 'pre_market', 'after_hours', or both, to include extended hours.
    """
    return _client(ctx).get_batch_historical_bars(
        symbols, timespan, count, category, trading_sessions
    )


@mcp.tool()
def get_eod_bars(instrument_ids: str, date: str, ctx: Context, count: int = 1) -> dict:
    """Get end-of-day OHLCV bars (daily close data).

    instrument_ids: comma-separated Webull instrument IDs (not ticker symbols — resolve
      via get_instruments first).
    date: the date to start from (YYYY-MM-DD).
    count: number of trading days of data to return (default 1).
    """
    return _client(ctx).get_eod_bars(instrument_ids, date, count)


@mcp.tool()
def get_corp_actions(
    instrument_ids: str,
    ctx: Context,
    event_types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page_number: int = 1,
    page_size: int = 50,
) -> dict:
    """Get corporate actions for instruments: dividends, stock splits, mergers, spinoffs, etc.

    instrument_ids: comma-separated Webull instrument IDs (resolve via get_instruments).
    event_types: filter by type — comma-separated from 'DIVIDEND', 'SPLIT',
      'MERGER', 'SPINOFF', etc. Omit to get all types.
    start_date: earliest event date (YYYY-MM-DD). Omit for no lower bound.
    end_date: latest event date (YYYY-MM-DD). Omit for no upper bound.
    """
    return _client(ctx).get_corp_actions(
        instrument_ids, event_types, start_date, end_date, page_number, page_size
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
