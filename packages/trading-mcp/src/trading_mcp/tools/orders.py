"""Order placement, modification, cancellation, and history."""

from fastmcp import Context, FastMCP
from trading_clients.endpoints.webull import (
    CANCEL_ORDER,
    OPEN_ORDERS,
    ORDER_DETAIL,
    ORDER_HISTORY,
    PLACE_ORDER,
    PREVIEW_ORDER,
    REPLACE_ORDER,
    CancelOrderRequest,
    GetOpenOrdersRequest,
    GetOrderDetailRequest,
    GetOrderHistoryRequest,
    PlaceOrderRequest,
    PreviewOrderRequest,
    ReplaceOrderRequest,
)

from trading_mcp.helpers import _check_market, _webull

mcp = FastMCP("orders-tools")


@mcp.tool()
async def get_open_orders(ctx: Context, account_id: str, page_size: int = 50) -> str:
    """Get all currently open/pending orders (stocks, options, futures, crypto).
    Returns symbol, side, order_type, quantity, filled_quantity, price, status,
    and option leg details if applicable.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    return (
        await client.get(
            OPEN_ORDERS,
            GetOpenOrdersRequest(client.ensure_account_id(account_id), page_size),
        )
    ).to_output()


@mcp.tool()
async def get_order_history(
    ctx: Context,
    account_id: str,
    page_size: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
) -> str:
    """Get order history including filled, cancelled, and pending orders.

    Supports any date range — use for reviewing past trades, not just today's orders.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    page_size: max number of orders to return (default 50).
    start_date: start date (YYYY-MM-DD). Defaults to today.
    end_date: end date (YYYY-MM-DD). Defaults to today.
    status: filter by order status (FILLED, CANCELLED, FAILED, PENDING). Case-insensitive.
    """
    client = _webull(ctx)
    response = await client.get(
        ORDER_HISTORY,
        GetOrderHistoryRequest(
            client.ensure_account_id(account_id), page_size, start_date, end_date
        ),
    )
    if status:
        response = response.filter_by_status(status)
    return response.to_output()


@mcp.tool()
async def get_order_detail(ctx: Context, client_order_id: str, account_id: str) -> str:
    """Get full detail for a specific order including status, fill info, timestamps,
    and option leg details.

    client_order_id: the unique order ID assigned when the order was placed.
    Use get_open_orders or get_today_orders to find client_order_ids.
    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    return (
        await client.get(
            ORDER_DETAIL,
            GetOrderDetailRequest(client.ensure_account_id(account_id), client_order_id),
        )
    ).to_output()


@mcp.tool()
async def preview_order(ctx: Context, new_orders: list[dict], account_id: str) -> str:
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

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    req = PreviewOrderRequest(account_id=client.ensure_account_id(account_id), **new_orders[0])
    return (await client.post(PREVIEW_ORDER, req)).to_output()


@mcp.tool()
async def place_order(
    ctx: Context,
    account_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    client_order_id: str,
    time_in_force: str,
    instrument_type: str = "EQUITY",
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

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    await _check_market(ctx, order_type, trading_session == "ALL")
    client = _webull(ctx)
    req = PlaceOrderRequest(
        account_id=client.ensure_account_id(account_id),
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
    return (await client.post(PLACE_ORDER, req)).to_output()


@mcp.tool()
async def replace_order(
    ctx: Context,
    account_id: str,
    client_order_id: str,
    quantity: str | None = None,
    order_type: str | None = None,
    time_in_force: str | None = None,
    limit_price: str | None = None,
    stop_price: str | None = None,
    trailing_type: str | None = None,
    trailing_stop_step: str | None = None,
) -> str:
    """Modify a pending order. Only price, quantity, type, and time_in_force can be changed.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    client_order_id: the unique order ID of the order to modify.
    quantity: new quantity (optional).
    order_type: new order type (optional).
    time_in_force: new TIF (optional).
    limit_price: new limit price (optional).
    stop_price: new stop price (optional).
    """
    client = _webull(ctx)
    req = ReplaceOrderRequest(
        account_id=client.ensure_account_id(account_id),
        client_order_id=client_order_id,
        quantity=quantity,
        order_type=order_type,
        time_in_force=time_in_force,
        limit_price=limit_price,
        stop_price=stop_price,
        trailing_type=trailing_type,
        trailing_stop_step=trailing_stop_step,
    )
    return (await client.post(REPLACE_ORDER, req)).to_output()


@mcp.tool()
async def cancel_order(ctx: Context, account_id: str, client_order_id: str) -> str:
    """Cancel a pending order (stock or option). The order must still be open/unfilled.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable orders.
    """
    client = _webull(ctx)
    req = CancelOrderRequest(client.ensure_account_id(account_id), client_order_id)
    return (await client.post(CANCEL_ORDER, req)).to_output()
