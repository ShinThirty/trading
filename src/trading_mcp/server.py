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
    """Get account profile information (account number, type)."""
    return _client(ctx).get_account_profile()


@mcp.tool()
def get_account_balance(ctx: Context, currency: str = "USD") -> dict:
    """Get account balance including total assets, cash, market value, and P&L."""
    return _client(ctx).get_account_balance(currency)


@mcp.tool()
def get_account_positions(ctx: Context) -> list[dict]:
    """Get all current holdings with cost basis, market value, and P&L."""
    return _client(ctx).get_account_positions()


@mcp.tool()
def get_account_position_details(instrument_id: str, ctx: Context, size: int = 20) -> dict:
    """Get detailed position info for a specific instrument."""
    return _client(ctx).get_account_position_details(instrument_id, size)


# ── Orders ───────────────────────────────────────────────────


@mcp.tool()
def get_open_orders(ctx: Context, page_size: int = 100) -> dict:
    """Get all currently open/pending orders."""
    return _client(ctx).get_open_orders(page_size)


@mcp.tool()
def get_today_orders(ctx: Context, page_size: int = 100) -> dict:
    """Get all orders placed today."""
    return _client(ctx).get_today_orders(page_size)


@mcp.tool()
def get_order_detail(client_order_id: str, ctx: Context) -> dict:
    """Get detail for a specific order by its client order ID."""
    return _client(ctx).get_order_detail(client_order_id)


# ── Stock Order Management ───────────────────────────────────


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
    """Place a stock order. side: BUY/SELL. order_type: MARKET/LIMIT/STOP/STOP_LIMIT."""
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
    """Modify a pending stock order. Same params as place_order, using existing client_order_id."""
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
    """Cancel a pending stock order by its client order ID."""
    return _client(ctx).cancel_order(client_order_id)


# ── Option Order Management ──────────────────────────────────


@mcp.tool()
def preview_option(new_orders: list[dict], ctx: Context) -> dict:
    """Preview an option order before placing. Returns estimated cost, margin impact, etc."""
    return _client(ctx).preview_option(new_orders)


@mcp.tool()
def place_option(new_orders: list[dict], ctx: Context) -> dict:
    """Place a single-leg option order. new_orders is a list with one order dict."""
    return _client(ctx).place_option(new_orders)


@mcp.tool()
def replace_option(modify_orders: list[dict], ctx: Context) -> dict:
    """Modify a pending option order."""
    return _client(ctx).replace_option(modify_orders)


@mcp.tool()
def cancel_option(client_order_id: str, ctx: Context) -> dict:
    """Cancel a pending option order by its client order ID."""
    return _client(ctx).cancel_option(client_order_id)


# ── Trade Info ───────────────────────────────────────────────


@mcp.tool()
def get_trade_calendar(market: str, start: str, end: str, ctx: Context) -> dict:
    """Get trading calendar (market open/close days). Dates as YYYY-MM-DD."""
    return _client(ctx).get_trade_calendar(market, start, end)


@mcp.tool()
def get_trade_instrument_detail(instrument_id: str, ctx: Context) -> dict:
    """Get tradeable instrument detail by instrument ID."""
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
    """Look up security detail. For options, set instrument_type, strike_price, init_exp_date."""
    return _client(ctx).get_security_detail(
        symbol, market, instrument_super_type, instrument_type, strike_price, init_exp_date
    )


@mcp.tool()
def get_tradeable_instruments(ctx: Context, page_size: int = 100) -> dict:
    """List all tradeable instruments (paginated)."""
    return _client(ctx).get_tradeable_instruments(page_size)


@mcp.tool()
def get_app_subscriptions(ctx: Context) -> dict:
    """Get your API app subscription info."""
    return _client(ctx).get_app_subscriptions()


# ── Market Data ──────────────────────────────────────────────


@mcp.tool()
def get_quote(symbols: str, ctx: Context) -> list[dict]:
    """Get snapshot quotes for symbols (comma-separated, e.g. 'AAPL,TSLA')."""
    return _client(ctx).get_quote(symbols)


@mcp.tool()
def get_instruments(symbols: str, ctx: Context) -> list[dict]:
    """Look up instrument IDs, exchange, and currency for symbols (comma-separated)."""
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
    """Get historical candlestick bars. timespan: m1, m5, m15, m30, h1, h2, h4, d1, w1."""
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
    """Get historical bars for multiple symbols at once (comma-separated)."""
    return _client(ctx).get_batch_historical_bars(
        symbols, timespan, count, category, trading_sessions
    )


@mcp.tool()
def get_eod_bars(instrument_ids: str, date: str, ctx: Context, count: int = 1) -> dict:
    """Get end-of-day bars. instrument_ids comma-separated, date as YYYY-MM-DD."""
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
    """Get corporate actions (dividends, splits, etc.) for instruments. Dates as YYYY-MM-DD."""
    return _client(ctx).get_corp_actions(
        instrument_ids, event_types, start_date, end_date, page_number, page_size
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
