from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import options as opts
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.config import load_config
from trading_clients.endpoints import alphavantage as av
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import fmp, fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
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
from trading_clients.endpoints.yahoo import ScreenerResponse
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fred_client import FredClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient

from trading_mcp import yahoo as yfc


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
    if config.tastytrade:
        ctx["tastytrade"] = TastyTradeClient(config.tastytrade)
    try:
        yield ctx
    finally:
        for client in ctx.values():
            client.close()


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


def _tastytrade(ctx: Context) -> TastyTradeClient:
    client = ctx.request_context.lifespan_context.get("tastytrade")
    if client is None:
        raise RuntimeError(
            "TastyTrade not configured. Add [tastytrade] section to ~/.tradingrc "
            "with client_secret and refresh_token."
        )
    return client


def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    """Validate market state before placing an order."""
    tradier = ctx.request_context.lifespan_context.get("tradier")
    if tradier is None:
        return  # skip check if Tradier not configured
    clock = tradier.get(t.CLOCK, t.EmptyRequest())
    state = clock.data.get("state", "closed")
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
    return client.get(BALANCE, AccountRequest(client.resolve_account_id(account_id))).to_output()


@mcp.tool()
def get_account_positions(ctx: Context, account_id: str | None = None) -> str:
    """Get all current portfolio holdings including option positions with full leg details
    (strike, expiration, option type, strategy). Returns each position's symbol, type,
    quantity, cost, last price, and unrealized P&L.

    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    return client.get(POSITIONS, AccountRequest(client.resolve_account_id(account_id))).to_output()


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
    ).to_output()


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
    ).to_output()


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
    ).to_output()


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
    req = PreviewOrderRequest(account_id=client.resolve_account_id(account_id), **new_orders[0])
    return client.post(PREVIEW_ORDER, req).to_output()


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
    return client.post(PLACE_ORDER, req).to_output()


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
    return client.post(REPLACE_ORDER, req).to_output()


@mcp.tool()
def cancel_order(ctx: Context, client_order_id: str, account_id: str | None = None) -> str:
    """Cancel a pending order (stock or option). The order must still be open/unfilled.

    client_order_id: the unique order ID from when the order was placed.
    Use get_open_orders to find cancellable orders.
    account_id: Webull account ID. Omit to use the default from ~/.tradingrc.
    """
    client = _webull(ctx)
    req = CancelOrderRequest(client.resolve_account_id(account_id), client_order_id)
    return client.post(CANCEL_ORDER, req).to_output()


@mcp.tool()
def get_app_subscriptions(ctx: Context) -> str:
    """Get all Webull accounts linked to this API key: account ID, account number,
    type (MARGIN/CASH), and label (Individual Cash, Roth IRA, etc.).
    """
    return _webull(ctx).get(ACCOUNT_LIST, EmptyRequest()).to_output()


@mcp.tool()
def get_portfolio_summary(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Get a consolidated view across ALL Webull accounts and optionally Fidelity.

    Iterates all Webull accounts (Roth IRA, Individual Cash, Margin, etc.),
    fetches balance and positions for each, and aggregates into one summary.
    Optionally includes Fidelity positions from exported CSVs.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit to show Webull only.

    Note: fetches Webull data sequentially to respect rate limits (~1 req/second).
    """
    import tempfile

    from trading_clients.portfolio import (
        AccountSummary,
        PortfolioSummary,
        compact_portfolio_summary,
        format_portfolio_summary,
        parse_fidelity_folder,
    )

    client = _webull(ctx)
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}

    # 1. Discover all Webull accounts
    account_list = client.get(ACCOUNT_LIST, EmptyRequest())
    if not account_list.accounts:
        errors["Webull"] = "No accounts found"

    # 2. Fetch balance + positions for each Webull account
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", acct.get("account_type", aid))
        atype = acct.get("account_type", "")

        try:
            bal = client.get(BALANCE, AccountRequest(aid))
        except Exception as e:
            errors[label] = str(e)
            continue

        sf = _safe_float
        nlv = sf(bal.net_liquidation)
        cash = sf(bal.cash_balance)
        mv = sf(bal.market_value)

        try:
            pos_resp = client.get(POSITIONS, AccountRequest(aid))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        summaries.append(
            AccountSummary(
                account_id=aid,
                label=label,
                broker="Webull",
                account_type=atype,
                nlv=nlv,
                cash=cash,
                market_value=mv,
                day_pnl=sf(bal.day_pnl),
                unrealized_pnl=sf(bal.unrealized_pnl),
                positions=positions,
            )
        )

    # 3. Parse Fidelity CSVs if folder provided
    if fidelity_folder:
        try:
            summaries.extend(parse_fidelity_folder(fidelity_folder))
        except Exception as e:
            errors["Fidelity"] = str(e)

    portfolio = PortfolioSummary(summaries, errors)
    full_output = format_portfolio_summary(portfolio)

    # Save full details to temp file, return compact summary
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", prefix="portfolio_", delete=False)
    f.write(full_output)
    f.close()

    return compact_portfolio_summary(portfolio, f.name)


def _safe_float(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


@mcp.tool()
def get_portfolio_greeks(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Get aggregate portfolio Greeks (delta, theta, gamma, vega) across all accounts.

    Fetches all option positions from Webull (and optionally Fidelity CSVs),
    constructs OCC symbols, batch-quotes Greeks from Tradier, and aggregates
    per-underlying and portfolio-wide.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit for Webull only.

    Requires [webull] and [tradier] sections in ~/.tradingrc.
    """
    import tempfile

    from trading_clients.portfolio import (
        format_greeks_compact,
        format_greeks_detail,
        parse_fidelity_folder,
    )

    webull = _webull(ctx)
    tradier = _tradier(ctx)

    # 1. Collect all positions across accounts
    all_positions: list[dict] = []
    account_list = webull.get(ACCOUNT_LIST, EmptyRequest())
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        try:
            all_positions.extend(webull.get(POSITIONS, AccountRequest(aid)).to_normalized())
        except Exception:
            continue

    if fidelity_folder:
        for acct in parse_fidelity_folder(fidelity_folder):
            all_positions.extend(acct.positions)

    # 2. Build OCC symbols for all option positions
    option_positions = [p for p in all_positions if p.get("is_option")]
    if not option_positions:
        return "(no option positions found)"

    occ_set: set[str] = set()
    for p in option_positions:
        occ_set.add(opts.build_occ(p["underlying"], p["expiration"], p["option_type"], p["strike"]))

    # 3. Batch quote Greeks from Tradier
    greeks_by_symbol: dict[str, dict] = {}
    quote_resp = tradier.get(t.QUOTES, t.GetQuotesRequest(",".join(occ_set), greeks=True))
    for q in quote_resp.quotes:
        greeks = q.get("greeks") or {}
        if greeks:
            greeks_by_symbol[q.get("symbol", "")] = greeks

    # 4. Aggregate and format
    result = opts.aggregate_greeks(all_positions, greeks_by_symbol)

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", prefix="greeks_", delete=False)
    f.write(format_greeks_detail(result["totals"], result["by_underlying"]))
    f.close()

    return format_greeks_compact(result["totals"], len(option_positions), f.name)


# ── Webull Market Data ──────────────────────────────────────


@mcp.tool()
def get_instruments(ctx: Context, symbols: str, category: str = "US_STOCK") -> str:
    """Look up instrument details for symbols: instrument_id, exchange, currency,
    and trading attributes (shortable, fractionable, marginable).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA'). Max 100.
    category: 'US_STOCK' (default) or 'US_ETF'.
    """
    return _webull(ctx).get(INSTRUMENTS, GetInstrumentsRequest(symbols, category)).to_output()


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
    return _tradier(ctx).get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol)).to_output()


@mcp.tool()
def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.STRIKES, t.GetStrikesRequest(symbol, expiration)).to_output()


@mcp.tool()
def get_option_chain(
    ctx: Context,
    symbol: str,
    expiration: str,
    greeks: bool = True,
    strike_count: int = 15,
) -> str:
    """Get the option chain for an underlying symbol at a specific expiration.

    Returns calls and puts near the money with: bid/ask with sizes, last price,
    day change/%, volume, open interest, and optionally greeks (IV, delta, gamma,
    theta, vega, rho).

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    greeks: include greeks and IV per contract (default True).
    strike_count: number of strikes above and below ATM to include (default 15).
      Set to 0 for the full unfiltered chain.

    Typical workflow:
    1. get_option_expirations('AAPL') → list of dates
    2. get_option_chain('AAPL', '2026-04-17') → chain with greeks

    Requires [tradier] section in ~/.tradingrc.
    """
    resp = _tradier(ctx).get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks))
    if resp.options and strike_count > 0:
        strikes = sorted({o["strike"] for o in resp.options})
        mid = (strikes[0] + strikes[-1]) / 2
        # Find the strike closest to midpoint of the tradeable range (≈ ATM)
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - mid))
        lo = max(0, atm_idx - strike_count)
        hi = min(len(strikes), atm_idx + strike_count + 1)
        keep = set(strikes[lo:hi])
        resp.options = [o for o in resp.options if o["strike"] in keep]
    return resp.to_output()


@mcp.tool()
def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.OPTION_LOOKUP, t.GetLookupRequest(underlying)).to_output()


# ── Options Analytics ──────────────────────────────────────


@mcp.tool()
def get_expected_move(ctx: Context, symbol: str, expiration: str) -> str:
    """Compute the expected move for a stock at a given option expiration.

    Shows the ATM straddle price (expected 1-sigma move), implied volatility,
    historical volatility, and IV/HV ratio. Useful for sizing positions and
    evaluating whether options are cheap or expensive.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: option expiration date (YYYY-MM-DD, from get_option_expirations).

    Requires [tradier] section in ~/.tradingrc.
    """
    from trading_clients.table_helpers import fmt_number, kv_table

    tradier = _tradier(ctx)

    # Get current stock price
    quote = tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    # Get option chain with greeks
    chain = tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks=True))
    if not chain.options:
        return f"(no option chain for {symbol} at {expiration})"

    # Expected move from ATM straddle
    em = opts.expected_move(chain.options, stock_price)

    # Historical volatility from price data
    history = tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily"))
    closes = [float(b["close"]) for b in history.days] if history.days else []
    hv20 = opts.historical_volatility(closes, 20)
    hv50 = opts.historical_volatility(closes, 50)

    # Build output
    data: dict[str, str] = {"Stock Price": fmt_number(stock_price)}
    data["Expiration"] = expiration

    if em["straddle_price"] is not None:
        straddle = em["straddle_price"]
        data["ATM Straddle"] = fmt_number(straddle)
        data["Expected Move"] = f"±${fmt_number(straddle)} ({fmt_number(em['expected_move_pct'])}%)"
        data["Expected Range"] = (
            f"${fmt_number(stock_price - straddle)} — ${fmt_number(stock_price + straddle)}"
        )
        data["ATM Strikes"] = f"Call {em['atm_call_strike']}, Put {em['atm_put_strike']}"

    if em["atm_iv"] is not None:
        data["Implied Volatility"] = f"{em['atm_iv'] * 100:.1f}%"

    if hv20 is not None:
        data["Historical Vol (20d)"] = f"{hv20 * 100:.1f}%"
    if hv50 is not None:
        data["Historical Vol (50d)"] = f"{hv50 * 100:.1f}%"

    if em["atm_iv"] is not None and hv20 is not None and hv20 > 0:
        ratio = em["atm_iv"] / hv20
        label = "rich" if ratio > 1.2 else "cheap" if ratio < 0.8 else "fair"
        data["IV/HV Ratio"] = f"{ratio:.2f} ({label})"

    return f"## {symbol} Expected Move ({expiration})\n\n{kv_table(data)}"


@mcp.tool()
def analyze_option_strategy(
    ctx: Context,
    symbol: str,
    legs: list[dict],
    shares: int | None = None,
    cost_basis: float | None = None,
) -> str:
    """Analyze an option strategy's risk/reward profile.

    Computes max profit, max loss, breakeven points, probability of profit,
    and risk/reward ratio for any single or multi-leg option strategy.

    Supports both single-expiration strategies (verticals, iron condors, etc.) and
    multi-expiration strategies (calendar spreads, diagonal spreads, PMCC, double
    diagonals). For multi-expiration, uses Black-Scholes to value the far-dated leg
    at the near-term expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    legs: list of leg dicts, each with:
      - strike: strike price (e.g. 250)
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - quantity: number of contracts (default 1)
      - expiration: option expiration date (YYYY-MM-DD)
    shares: number of shares held (e.g. 100 for covered call). Omit for option-only.
    cost_basis: per-share cost basis (e.g. 150.00). Required when shares is provided.

    Premiums and deltas are auto-fetched from the live option chain.

    Common strategies:
      CSP: [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"}]
      Bull put spread:
           [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"},
            {"strike": 240, "option_type": "put", "side": "buy",
             "expiration": "2026-06-18"}]
      Calendar spread:
           [{"strike": 100, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"},
            {"strike": 100, "option_type": "call", "side": "buy",
             "expiration": "2026-06-18"}]
      Diagonal / PMCC:
           [{"strike": 90, "option_type": "call", "side": "buy",
             "expiration": "2027-01-15"},
            {"strike": 110, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"}]

    Requires [tradier] section in ~/.tradingrc.
    """
    from trading_clients.table_helpers import fmt_number, kv_table

    tradier = _tradier(ctx)

    # Validate every leg has an expiration
    for i, leg in enumerate(legs):
        if "expiration" not in leg:
            return f"(leg {i + 1} missing required 'expiration' field)"

    # Validate equity params
    equity_position = None
    if shares is not None or cost_basis is not None:
        if shares is None or cost_basis is None:
            return "(both shares and cost_basis are required together)"
        if shares <= 0:
            return "(shares must be positive)"
        if cost_basis <= 0:
            return "(cost_basis must be positive)"
        equity_position = {"shares": shares, "cost_basis": cost_basis}

    # Get current stock price
    quote = tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    # Fetch option chain for each unique expiration
    unique_exps = sorted({leg["expiration"] for leg in legs})
    chains: dict[str, list[dict]] = {}
    for exp in unique_exps:
        chain = tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp, greeks=True))
        if not chain.options:
            return f"(no option chain for {symbol} at {exp})"
        chains[exp] = chain.options

    # Match each leg to its chain entry and fill in premium + delta
    enriched_legs = []
    for leg in legs:
        strike = float(leg["strike"])
        otype = leg["option_type"]
        leg_exp = leg["expiration"]
        chain_options = chains[leg_exp]
        matches = [
            o
            for o in chain_options
            if o.get("option_type") == otype and abs(o["strike"] - strike) < 0.01
        ]
        if not matches:
            return f"(no {otype} at strike {strike} for {leg_exp})"
        opt = matches[0]
        greeks = opt.get("greeks") or {}
        enriched_legs.append(
            {
                "strike": strike,
                "option_type": otype,
                "side": leg["side"],
                "quantity": leg.get("quantity", 1),
                "premium": opts.mid_price(opt),
                "delta": greeks.get("delta"),
                "iv": greeks.get("mid_iv"),
                "bid": opt.get("bid"),
                "ask": opt.get("ask"),
                "occ_symbol": opt.get("symbol", ""),
                "expiration": leg_exp,
            }
        )

    # Route to appropriate analyzer
    is_multi_exp = len(unique_exps) > 1
    if is_multi_exp:
        from trading_clients.options_multi_exp import analyze_multi_exp_strategy

        result = analyze_multi_exp_strategy(enriched_legs, stock_price)
    else:
        result = opts.strategy_analysis(enriched_legs, stock_price, equity_position)

    # Build leg detail table
    from trading_clients.table_helpers import list_table

    leg_rows = []
    if equity_position:
        leg_rows.append(
            {
                "Side": "LONG",
                "Type": "EQUITY",
                "Strike": "",
                "Exp": "",
                "Bid": "",
                "Ask": "",
                "Mid": fmt_number(stock_price),
                "Delta": "1.000",
                "IV": "",
                "Qty": str(equity_position["shares"]),
            }
        )
    for el in enriched_legs:
        row: dict[str, str] = {
            "Side": el["side"].upper(),
            "Type": el["option_type"].upper(),
            "Strike": fmt_number(el["strike"]),
        }
        if is_multi_exp:
            row["Exp"] = el["expiration"]
        row["Bid"] = fmt_number(el["bid"])
        row["Ask"] = fmt_number(el["ask"])
        row["Mid"] = fmt_number(el["premium"])
        row["Delta"] = fmt_number(el["delta"], 3) if el["delta"] else ""
        row["IV"] = f"{el['iv'] * 100:.1f}%" if el["iv"] else ""
        row["Qty"] = str(el["quantity"])
        leg_rows.append(row)

    # Build summary
    data: dict[str, str] = {
        "Strategy": result.get("strategy_type", ""),
        "Stock Price": fmt_number(stock_price),
    }
    if is_multi_exp:
        data["Near Expiration"] = result.get("near_exp", unique_exps[0])
        data["Far Expiration"] = result.get("far_exp", unique_exps[-1])
    else:
        data["Expiration"] = unique_exps[0]

    if equity_position:
        data["Cost Basis"] = fmt_number(equity_position["cost_basis"])
        data["Shares"] = str(equity_position["shares"])

    net = result["net_premium"]
    from math import gcd

    leg_qtys = [el.get("quantity", 1) for el in enriched_legs]
    units = gcd(*leg_qtys) if leg_qtys else 1
    per_share = net / units
    total = net * 100
    if net >= 0:
        data["Net Credit"] = f"${fmt_number(per_share)} per share (${fmt_number(total)} total)"
    else:
        data["Net Debit"] = (
            f"${fmt_number(abs(per_share))} per share (${fmt_number(abs(total))} total)"
        )

    data["Max Profit"] = f"${fmt_number(result['max_profit'])}"
    data["Max Loss"] = f"${fmt_number(result['max_loss'])}"

    if result["breakevens"]:
        data["Breakeven"] = ", ".join(f"${fmt_number(b)}" for b in result["breakevens"])

    if result["risk_reward_ratio"] is not None:
        data["Risk/Reward"] = f"{result['risk_reward_ratio']:.2f}"

    if result["probability_of_profit"] is not None:
        data["P(Profit)"] = f"{result['probability_of_profit'] * 100:.0f}%"

    if result.get("if_called_return") is not None:
        data["If-Called Return"] = f"{result['if_called_return'] * 100:.2f}%"
    if result.get("static_return") is not None:
        data["Static Return"] = f"{result['static_return'] * 100:.2f}%"

    if is_multi_exp:
        data["Note"] = "P&L evaluated at near expiration using Black-Scholes for far-dated legs"

    sections = [
        f"## {symbol} {result.get('strategy_type', 'Strategy')} Analysis",
        "",
        "### Legs",
        list_table(leg_rows),
        "",
        "### Summary",
        kv_table(data),
    ]
    return "\n".join(sections)


@mcp.tool()
def analyze_roll(
    ctx: Context,
    current_symbol: str,
    target_expiration: str,
    target_strike: float | None = None,
    quantity: int = 1,
) -> str:
    """Analyze rolling an option position to a new expiration and/or strike.

    Computes cost to close, premium for new position, net credit/debit, DTE change,
    and greek comparison. Designed for covered calls and CSPs that need regular rolling.

    current_symbol: OCC option symbol of current position
      (e.g. 'SMH260501C00410000'). Use get_account_positions to find it,
      or get_option_lookup to construct it.
    target_expiration: expiration date for the new position (YYYY-MM-DD).
      Use get_option_expirations to find available dates.
    target_strike: strike price for new position. Omit to keep same strike
      (horizontal roll). Change for diagonal rolls (roll up/down).
    quantity: number of contracts being rolled (default 1).

    Requires [tradier] section in ~/.tradingrc.
    """
    from trading_clients.table_helpers import fmt_number, kv_table

    tradier = _tradier(ctx)

    # Parse OCC symbol
    try:
        underlying, current_exp, option_type, current_strike = opts.parse_occ(current_symbol)
    except (IndexError, ValueError):
        return f"(invalid OCC symbol: {current_symbol})"

    if target_strike is None:
        target_strike = current_strike

    # Fetch: current option quote, stock price, target chain
    cur_resp = tradier.get(t.QUOTES, t.GetQuotesRequest(current_symbol, greeks=True))
    if not cur_resp.quotes:
        return f"(no quote for {current_symbol})"

    stock_resp = tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False))
    stock_price = 0.0
    if stock_resp.quotes:
        stock_price = float(
            stock_resp.quotes[0].get("last") or stock_resp.quotes[0].get("close", 0)
        )

    chain = tradier.get(t.CHAIN, t.GetChainRequest(underlying, target_expiration, greeks=True))
    if not chain.options:
        return f"(no option chain for {underlying} at {target_expiration})"

    # Find target option (exact strike, then closest)
    matches = [
        o
        for o in chain.options
        if o.get("option_type") == option_type and abs(o["strike"] - target_strike) < 0.01
    ]
    if not matches:
        typed = [o for o in chain.options if o.get("option_type") == option_type]
        if not typed:
            return f"(no {option_type} options at {target_expiration})"
        matches = [min(typed, key=lambda o: abs(o["strike"] - target_strike))]
    new_opt = matches[0]
    actual_strike = new_opt["strike"]

    # Compute roll metrics
    r = opts.roll_analysis(
        cur_resp.quotes[0],
        new_opt,
        stock_price,
        current_exp,
        target_expiration,
        current_strike,
        actual_strike,
    )

    # --- Format output ---
    type_label = option_type.upper()
    title = (
        f"## {underlying} Roll: "
        f"{current_exp} {type_label[0]}{current_strike:g} → "
        f"{target_expiration} {type_label[0]}{actual_strike:g}"
    )

    cur_data: dict[str, str] = {
        "Symbol": current_symbol,
        "Type": type_label,
        "Strike": fmt_number(current_strike),
        "Expiration": current_exp,
        "DTE": str(r["cur_dte"]),
        "Bid": fmt_number(r["cur_bid"]),
        "Ask": fmt_number(r["cur_ask"]),
    }
    new_data: dict[str, str] = {
        "Symbol": new_opt.get("symbol", ""),
        "Type": type_label,
        "Strike": fmt_number(actual_strike),
        "Expiration": target_expiration,
        "DTE": str(r["new_dte"]),
        "Bid": fmt_number(r["new_bid"]),
        "Ask": fmt_number(r["new_ask"]),
    }
    for label, data, prefix in [
        ("cur", cur_data, "cur_"),
        ("new", new_data, "new_"),
    ]:
        if r.get(f"{prefix}delta") is not None:
            data["Delta"] = fmt_number(r[f"{prefix}delta"], 4)
        if r.get(f"{prefix}theta") is not None:
            data["Theta"] = fmt_number(r[f"{prefix}theta"], 4)
        if r.get(f"{prefix}mid_iv") is not None:
            data["IV"] = f"{r[f'{prefix}mid_iv'] * 100:.1f}%"

    net = r["net"]
    net_total = net * quantity * 100
    roll_data: dict[str, str] = {
        "Stock Price": fmt_number(stock_price),
        "Roll Type": r["roll_type"],
        "Cost to Close": f"${fmt_number(r['close_cost'])} (buy at ask)",
        "New Premium": f"${fmt_number(r['open_premium'])} (sell at bid)",
    }
    if net >= 0:
        roll_data["Net Credit"] = f"${fmt_number(net)}/sh (${fmt_number(net_total)} total)"
    else:
        roll_data["Net Debit"] = f"${fmt_number(abs(net))}/sh (${fmt_number(abs(net_total))} total)"
    roll_data["DTE Change"] = (
        f"{r['cur_dte']} → {r['new_dte']} (+{r['new_dte'] - r['cur_dte']} days)"
    )

    for key, label in [("delta", "Delta"), ("theta", "Theta")]:
        if r.get(f"cur_{key}") is not None:
            diff = r[f"new_{key}"] - r[f"cur_{key}"]
            sign = "+" if diff >= 0 else ""
            roll_data[f"{label} Change"] = (
                f"{fmt_number(r[f'cur_{key}'], 4)} → "
                f"{fmt_number(r[f'new_{key}'], 4)} ({sign}{fmt_number(diff, 4)})"
            )
    if r.get("cur_mid_iv") is not None:
        iv_diff = (r["new_mid_iv"] - r["cur_mid_iv"]) * 100
        sign = "+" if iv_diff >= 0 else ""
        roll_data["IV Change"] = (
            f"{r['cur_mid_iv'] * 100:.1f}% → {r['new_mid_iv'] * 100:.1f}% ({sign}{iv_diff:.1f}%)"
        )

    sections = [
        title,
        "",
        "### Current Position",
        kv_table(cur_data),
        "",
        "### New Position",
        kv_table(new_data),
        "",
        "### Roll Summary",
        kv_table(roll_data),
    ]
    return "\n".join(sections)


@mcp.tool()
def get_tradier_history(
    ctx: Context,
    symbol: str,
    interval: str = "daily",
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> str:
    """Get historical OHLCV pricing data. Works for both stocks AND option contracts.

    For option contracts, pass the OCC symbol (e.g. 'AAPL260417C00260000') — use
    get_option_lookup to discover available symbols.

    symbol: ticker or OCC option symbol.
    interval: 'daily', 'weekly', or 'monthly'.
    start: start date (YYYY-MM-DD). Defaults to beginning of available data.
    end: end date (YYYY-MM-DD). Defaults to today.
    limit: max number of bars to return, keeping the most recent. Default: all bars.

    Requires [tradier] section in ~/.tradingrc.
    """
    resp = _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, interval, start, end))
    if limit and resp.days:
        resp.days = resp.days[-limit:]
    return resp.to_output()


@mcp.tool()
def search_symbols(ctx: Context, query: str, indexes: bool = False) -> str:
    """Search for stocks and ETFs by company name or partial symbol. Results are sorted
    by average volume (most liquid first). Useful for stock discovery.

    query: search term — company name or partial symbol (e.g. 'apple', 'semi', 'AI').
    indexes: set True to include index symbols in results.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.SEARCH, t.SearchRequest(query, indexes)).to_output()


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
    return _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbols, greeks)).to_output()


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
    return (
        _tradier(ctx)
        .get(t.TIMESALES, t.GetTimesalesRequest(symbol, interval, start, end))
        .to_output()
    )


@mcp.tool()
def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return _tradier(ctx).get(t.CLOCK, t.EmptyRequest()).to_output()


# ── Technical Analysis ─────────────────────────────────────


@mcp.tool()
def get_technical_indicators(
    ctx: Context,
    symbol: str,
    indicators: list[str] | None = None,
    period: str = "daily",
) -> str:
    """Compute technical indicators from historical price data.

    symbol: ticker symbol (e.g. 'AAPL').
    indicators: list of indicators to compute. Default: all.
      - 'sma' — Simple Moving Average (20 and 50 period)
      - 'ema' — Exponential Moving Average (12 and 26 period)
      - 'rsi' — Relative Strength Index (14 period)
      - 'macd' — MACD line, signal, histogram (12/26/9)
      - 'bbands' — Bollinger Bands (20 period, 2 std dev)
      - 'atr' — Average True Range (14 period)
    period: bar interval — 'daily', 'weekly', or 'monthly'. Default 'daily'.

    Returns the latest values for each indicator plus a recent history table.
    Requires [tradier] section in ~/.tradingrc.
    """
    if indicators is None:
        indicators = ["sma", "ema", "rsi", "macd", "bbands", "atr"]

    # Fetch enough history for warmup (60 bars covers all indicator needs)
    resp = _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, period))
    bars = resp.days
    if not bars:
        return "(no historical data)"

    closes = [float(b["close"]) for b in bars]
    latest_price = closes[-1]
    latest_date = bars[-1].get("date", "")

    sections: list[str] = [f"## {symbol} Technical Indicators ({latest_date})"]
    sections.append(f"**Price:** {latest_price:,.2f}\n")

    # Number of recent values to show in the table
    tail = 10

    if "rsi" in indicators:
        vals = ta.rsi(closes)
        latest = vals[-1]
        if latest is not None:
            level = "oversold" if latest < 30 else "overbought" if latest > 70 else "neutral"
            sections.append(f"**RSI(14):** {latest:.1f} ({level})")

    if "macd" in indicators:
        macd_line, signal_line, histogram = ta.macd(closes)
        m, s, h = macd_line[-1], signal_line[-1], histogram[-1]
        if m is not None and s is not None and h is not None:
            trend = "bullish" if h > 0 else "bearish"
            sections.append(
                f"**MACD(12,26,9):** line={m:.2f}, signal={s:.2f}, histogram={h:.2f} ({trend})"
            )

    if "sma" in indicators:
        sma20 = ta.sma(closes, 20)
        sma50 = ta.sma(closes, 50)
        parts = []
        if sma20[-1] is not None:
            rel = "above" if latest_price > sma20[-1] else "below"
            parts.append(f"SMA(20)={sma20[-1]:.2f} (price {rel})")
        if sma50[-1] is not None:
            rel = "above" if latest_price > sma50[-1] else "below"
            parts.append(f"SMA(50)={sma50[-1]:.2f} (price {rel})")
        if parts:
            sections.append(f"**SMA:** {', '.join(parts)}")

    if "ema" in indicators:
        ema12 = ta.ema(closes, 12)
        ema26 = ta.ema(closes, 26)
        parts = []
        if ema12[-1] is not None:
            parts.append(f"EMA(12)={ema12[-1]:.2f}")
        if ema26[-1] is not None:
            parts.append(f"EMA(26)={ema26[-1]:.2f}")
        if parts:
            sections.append(f"**EMA:** {', '.join(parts)}")

    if "bbands" in indicators:
        upper, middle, lower = ta.bollinger_bands(closes)
        if upper[-1] is not None and middle[-1] is not None and lower[-1] is not None:
            width = (upper[-1] - lower[-1]) / middle[-1] * 100
            if latest_price > upper[-1]:
                pos = "above upper band"
            elif latest_price < lower[-1]:
                pos = "below lower band"
            else:
                pos = "within bands"
            sections.append(
                f"**Bollinger(20,2):** upper={upper[-1]:.2f}, "
                f"mid={middle[-1]:.2f}, lower={lower[-1]:.2f} "
                f"(width={width:.1f}%, {pos})"
            )

    if "atr" in indicators:
        atr_vals = ta.atr(bars)
        if atr_vals[-1] is not None:
            atr_pct = atr_vals[-1] / latest_price * 100
            sections.append(f"**ATR(14):** {atr_vals[-1]:.2f} ({atr_pct:.1f}% of price)")

    # Recent history table
    sections.append("\n### Recent Values")
    from trading_clients.table_helpers import fmt_number, list_table

    rows = []
    start = max(0, len(bars) - tail)
    rsi_vals = ta.rsi(closes) if "rsi" in indicators else []
    sma20_vals = ta.sma(closes, 20) if "sma" in indicators else []
    atr_vals_full = ta.atr(bars) if "atr" in indicators else []

    for i in range(start, len(bars)):
        row: dict[str, str] = {
            "Date": bars[i].get("date", ""),
            "Close": fmt_number(closes[i]),
        }
        if rsi_vals:
            row["RSI"] = fmt_number(rsi_vals[i], 1) if rsi_vals[i] is not None else ""
        if sma20_vals:
            row["SMA20"] = fmt_number(sma20_vals[i]) if sma20_vals[i] is not None else ""
        if atr_vals_full:
            row["ATR"] = fmt_number(atr_vals_full[i]) if atr_vals_full[i] is not None else ""
        rows.append(row)

    sections.append(list_table(rows))
    return "\n".join(sections)


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
    return (
        _finnhub(ctx)
        .get(fh.COMPANY_NEWS, fh.CompanyNewsRequest(symbol, from_date, to_date))
        .to_output()
    )


@mcp.tool()
def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.MARKET_NEWS, fh.MarketNewsRequest(category)).to_output()


@mcp.tool()
def get_earnings_calendar(
    ctx: Context,
    from_date: str,
    to_date: str,
    symbol: str | None = None,
    limit: int = 50,
) -> str:
    """Get upcoming and recent earnings reports. Automatically filters out micro-caps.

    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    symbol: optional ticker to filter for (e.g. 'TSLA'). Returns only that symbol's
      earnings entry when set.
    limit: max number of entries to return (default 50).

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = _finnhub(ctx).get(fh.EARNINGS_CALENDAR, fh.DateRangeRequest(from_date, to_date))
    if symbol:
        resp.earnings = [e for e in resp.earnings if e.get("symbol", "").upper() == symbol.upper()]
    resp.earnings = resp.earnings[:limit]
    return resp.to_output()


@mcp.tool()
def get_basic_financials(ctx: Context, symbol: str) -> str:
    """Get key financial metrics: P/E, P/B, EPS, dividend yield, 52-week high/low,
    market cap, beta, ROE, debt/equity.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol)).to_output()


@mcp.tool()
def get_eps_estimates(ctx: Context, symbol: str) -> str:
    """Get analyst EPS estimates for upcoming quarters and years: average, high, low,
    number of analysts, year-ago EPS, and growth rate.

    Periods: current quarter (0q), next quarter (+1q), current year (0y), next year (+1y).

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_clients.table_helpers import fmt_number, list_table

    data = yfc.earnings_estimate(symbol)
    if not data:
        return f"(no EPS estimates for {symbol})"
    rows = [
        {
            "Period": d["period"],
            "# Analysts": str(int(d.get("numberOfAnalysts", 0))),
            "Avg": fmt_number(d.get("avg")),
            "Low": fmt_number(d.get("low")),
            "High": fmt_number(d.get("high")),
            "Year Ago": fmt_number(d.get("yearAgoEps")),
            "Growth": fmt_number(d.get("growth")),
        }
        for d in data
    ]
    return list_table(rows)


@mcp.tool()
def get_recommendation_trends(ctx: Context, symbol: str) -> str:
    """Get analyst recommendation trends: counts of strong buy, buy, hold, sell, and
    strong sell ratings by month.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.RECOMMENDATIONS, fh.SymbolRequest(symbol)).to_output()


@mcp.tool()
def get_price_target(ctx: Context, symbol: str) -> str:
    """Get analyst consensus price target: current price, high, low, mean, and median
    target prices.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_clients.table_helpers import fmt_number, kv_table

    data = yfc.analyst_price_targets(symbol)
    if not data:
        return f"(no price targets for {symbol})"
    return kv_table(
        {
            "Current": fmt_number(data.get("current")),
            "Target Low": fmt_number(data.get("low")),
            "Target Mean": fmt_number(data.get("mean")),
            "Target Median": fmt_number(data.get("median")),
            "Target High": fmt_number(data.get("high")),
        }
    )


@mcp.tool()
def get_insider_transactions(ctx: Context, symbol: str, limit: int = 20) -> str:
    """Get recent insider transactions: buys, sells, and grants by company officers
    and directors.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: max number of transactions to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = _finnhub(ctx).get(fh.INSIDER_TRANSACTIONS, fh.SymbolRequest(symbol))
    resp.transactions = resp.transactions[:limit]
    return resp.to_output()


@mcp.tool()
def get_company_peers(ctx: Context, symbol: str) -> str:
    """Get a list of peer/competitor symbols for a company.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return _finnhub(ctx).get(fh.PEERS, fh.SymbolRequest(symbol)).to_output()


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
    return _fmp(ctx).get(fmp.PROFILE, fmp.SymbolRequest(symbol)).to_output()


@mcp.tool()
def get_income_statement(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get income statement from SEC filings: revenue, cost of revenue, gross profit,
    operating income, net income, EPS.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = _finnhub(ctx).get(fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq))
    return result.income_markdown(limit)


@mcp.tool()
def get_balance_sheet(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get balance sheet from SEC filings: cash, current assets, total assets,
    current liabilities, long-term debt, total liabilities, total equity.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = _finnhub(ctx).get(fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq))
    return result.balance_sheet_markdown(limit)


@mcp.tool()
def get_cash_flow(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get cash flow statement from SEC filings: operating cash flow, capex,
    investing/financing cash flows, dividends, buybacks.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = _finnhub(ctx).get(fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq))
    return result.cash_flow_markdown(limit)


@mcp.tool()
def get_key_metrics(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get key financial metrics: EV/EBITDA, ROE, ROA, current ratio, debt/equity, FCF yield.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.KEY_METRICS, fmp.FinancialRequest(symbol, period, limit)).to_output()


@mcp.tool()
def get_dividend_history(ctx: Context, symbol: str) -> str:
    """Get dividend payment history: ex-date, pay date, record date, amount.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] or [tastytrade] section in ~/.tradingrc.
    """
    fmp_client = ctx.request_context.lifespan_context.get("fmp")
    if fmp_client:
        try:
            return fmp_client.get(fmp.DIVIDEND_HISTORY, fmp.SymbolRequest(symbol)).to_output()
        except ValueError:
            pass  # FMP paywall — fall through to TastyTrade
    tt_client = ctx.request_context.lifespan_context.get("tastytrade")
    if tt_client:
        return tt_client.get(tt.DIVIDEND_HISTORY, tt.DividendHistoryRequest(symbol)).to_output()
    raise RuntimeError(
        "No dividend data source available. Add [fmp] or [tastytrade] to ~/.tradingrc"
    )


@mcp.tool()
def get_fmp_earnings_calendar(ctx: Context, symbol: str, limit: int = 5) -> str:
    """Get earnings history: date, EPS estimate/actual, revenue estimate/actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5).
    Requires [fmp] section in ~/.tradingrc.
    """
    return _fmp(ctx).get(fmp.EARNINGS, fmp.EarningsRequest(symbol, limit)).to_output()


@mcp.tool()
def get_sector_performance(ctx: Context, date: str, exchange: str = "NYSE") -> str:
    """Get sector performance for a specific date: average percentage change for each
    of 11 sectors (Technology, Healthcare, Financial Services, etc.), sorted best to worst.

    Useful for understanding sector rotation and whether a stock's movement is
    stock-specific or sector-wide.

    date: trading date (YYYY-MM-DD). Use a recent trading day (not weekend/holiday).
    exchange: 'NYSE' (default) or 'NASDAQ'.

    Requires [fmp] section in ~/.tradingrc.
    """
    return (
        _fmp(ctx)
        .get(fmp.SECTOR_PERFORMANCE, fmp.SectorPerformanceRequest(date, exchange))
        .to_output()
    )


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
    return _fred(ctx).get(fred.OBSERVATIONS, req).to_output()


@mcp.tool()
def get_fred_series_info(ctx: Context, series_id: str) -> str:
    """Get metadata for a FRED series: title, frequency, units, seasonal adjustment.

    series_id: FRED series ID (e.g. 'CPIAUCSL', 'GDP', 'VIXCLS').
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.SERIES_INFO, fred.SeriesIdRequest(series_id)).to_output()


@mcp.tool()
def get_upcoming_economic_releases(ctx: Context, limit: int = 20) -> str:
    """Get upcoming FRED data release dates: when CPI, GDP, jobs report will be published.

    limit: number of upcoming releases to return (default 20).
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.RELEASES, fred.GetReleasesRequest(limit)).to_output()


@mcp.tool()
def search_fred_series(ctx: Context, query: str, limit: int = 10) -> str:
    """Search for FRED economic data series by keyword.

    query: search terms (e.g. 'inflation', 'housing starts', 'consumer credit').
    limit: max results to return (default 10).

    Use the returned series_id with get_economic_data to fetch actual values.
    Requires [fred] section in ~/.tradingrc.
    """
    return _fred(ctx).get(fred.SEARCH, fred.SearchRequest(query, limit)).to_output()


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
    return (
        _alphavantage(ctx)
        .get(av.SENTIMENT, av.SentimentRequest(tickers, topics, limit=limit))
        .to_output()
    )


@mcp.tool()
def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks.

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return _alphavantage(ctx).get(av.MOVERS, av.MoversRequest()).to_output()


# ═══════════════════════════════════════════════════════════════
# TASTYTRADE — IV Rank, IV Percentile, Market Metrics
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_iv_metrics(ctx: Context, symbols: str) -> str:
    """Get implied volatility metrics: IV rank, IV percentile, IV index, 30-day IV,
    5-day IV change, next earnings date, and liquidity rating.

    IV Rank shows where current IV sits relative to its 52-week high/low (0-100).
    IV Percentile shows what % of days in the past year had lower IV (0-100%).
    Use these to time premium-selling strategies: high IV Rank = rich premiums.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,QCOM,ADBE').

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return _tastytrade(ctx).get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbols)).to_output()


@mcp.tool()
def get_public_watchlists(ctx: Context) -> str:
    """List all TastyTrade curated watchlists with symbol counts.

    Includes sector lists, high IV rank names, liquid options, dividend aristocrats,
    earnings calendars, and more. Use get_public_watchlist to get the symbols in
    a specific list.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return _tastytrade(ctx).get(tt.PUBLIC_WATCHLISTS, tt.EmptyRequest()).to_output()


@mcp.tool()
def get_public_watchlist(ctx: Context, name: str) -> str:
    """Get all symbols in a TastyTrade curated watchlist.

    name: watchlist name (e.g. 'tasty IVR', 'High Options Volume',
      '52 Week Near Low', 'A.I. Stocks', 'Dividend Aristocrats').
      Use get_public_watchlists to see available names.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return _tastytrade(ctx).get(tt.PUBLIC_WATCHLIST, tt.WatchlistRequest(name)).to_output()


@mcp.tool()
def backtest_strategy(
    ctx: Context,
    symbol: str,
    start_date: str,
    end_date: str,
    legs: list[dict],
    entry_conditions: dict | None = None,
    exit_conditions: dict | None = None,
) -> str:
    """Backtest an option strategy against historical data.

    Runs the strategy repeatedly over the date range and returns win rate,
    P&L, and individual trial results.

    symbol: underlying ticker (e.g. 'ADBE'). ~147 symbols available.
    start_date: backtest start (YYYY-MM-DD). Most symbols available from 2013.
    end_date: backtest end (YYYY-MM-DD).
    legs: list of leg dicts, each with:
      - type: 'equity-option' or 'equity'
      - direction: 'long' or 'short'
      - side: 'call' or 'put' (for options)
      - quantity: 1-10 for options, 1-100 for equity
      - strikeSelection: how to pick the strike:
          'delta' (use delta field, 1-100 where 20 = 0.20 delta)
          'percentageOTM' (use percentageOTM field, e.g. 0.10 for 10% OTM)
      - delta: strike delta (e.g. 20 for 0.20 delta)
      - percentageOTM: pct OTM (e.g. 0.10 for 10%)
      - daysUntilExpiration: target DTE (e.g. 45)
    entry_conditions: dict with:
      - frequency: 'every day', 'on specific days of the week',
          'on exact days to expiration match'
      - maximumActiveTrials: max concurrent positions (e.g. 1)
      - maximumActiveTrialsBehavior: 'don't enter' or 'close oldest'
      - minimumVIX / maximumVIX: VIX range filter
    exit_conditions: dict with:
      - takeProfitPercentage: close at X% profit (e.g. 50)
      - stopLossPercentage: close at X% loss
      - atDaysToExpiration: close at N DTE (e.g. 7)
      - afterDaysInTrade: close after N days

    Example CSP backtest:
      symbol='ADBE', start_date='2024-01-01', end_date='2026-04-01',
      legs=[{'type': 'equity-option', 'direction': 'short', 'side': 'put',
             'quantity': 1, 'strikeSelection': 'delta', 'delta': 20,
             'daysUntilExpiration': 45}],
      entry_conditions={'frequency': 'every day', 'maximumActiveTrials': 1,
                        'maximumActiveTrialsBehavior': "don't enter"},
      exit_conditions={'takeProfitPercentage': 50, 'atDaysToExpiration': 7}

    Note: backtests run asynchronously and may take 1-3 minutes.
    Requires [tastytrade] section in ~/.tradingrc.
    """
    import time

    client = _tastytrade(ctx)

    # Create the backtest
    result = client.post(
        tt.BACKTEST_CREATE,
        tt.BacktestRequest(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            legs=legs,
            entry_conditions=entry_conditions or {},
            exit_conditions=exit_conditions or {},
        ),
    )
    bt_id = result.data.get("id")
    if not bt_id:
        return result.to_output()

    # Poll until complete (up to 5 minutes)
    for _ in range(100):
        result = client.get(tt.BACKTEST_GET, tt.BacktestIdRequest(bt_id))
        if result.data.get("status") == "completed":
            return result.to_output()
        time.sleep(3)

    return f"Backtest {bt_id} still running. Check back later."


# ═══════════════════════════════════════════════════════════════
# YAHOO FINANCE
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def screen_stocks(
    ctx: Context,
    criteria: list[dict],
    sort_field: str = "intradaymarketcap",
    sort_dir: str = "DESC",
    limit: int = 25,
) -> str:
    """Screen for US stocks matching specific criteria.

    criteria: list of filter dicts, each with:
      - field: the data field to filter on
      - op: comparison operator ('gt', 'lt', 'gte', 'lte', 'eq', 'btwn', 'is-in')
      - value: comparison value (number for numeric, string for categorical).
        For 'btwn', use [min, max]. For 'is-in', use a list of values.

    Available fields:
      Market: intradaymarketcap, intradayprice, avgdailyvol3m, beta, percentchange
      Valuation: peratio.lasttwelvemonths, pricebookratio.quarterly, pegratio_5y
      Dividends: forward_dividend_yield, forward_dividend_per_share
      Growth: epsgrowth.lasttwelvemonths, quarterlyrevenuegrowth.quarterly
      Profitability: returnonequity.lasttwelvemonths, returnonassets.lasttwelvemonths,
        currentratio.lasttwelvemonths
      Categorical: sector, exchange (use 'eq' or 'is-in')
      Short Interest: days_to_cover_short.value, short_percentage_of_float.value

    Sectors: 'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical',
      'Communication Services', 'Industrials', 'Consumer Defensive', 'Energy',
      'Basic Materials', 'Real Estate', 'Utilities'

    sort_field: field to sort by (default 'intradaymarketcap').
    sort_dir: 'DESC' or 'ASC'.
    limit: max results to return (default 25, max 250).

    Example: large-cap tech with low P/E:
      criteria=[
        {"field": "intradaymarketcap", "op": "gt", "value": 50000000000},
        {"field": "sector", "op": "eq", "value": "Technology"},
        {"field": "peratio.lasttwelvemonths", "op": "lt", "value": 25}
      ]

    Uses Yahoo Finance via yfinance (no API key required). Data is 15-minute delayed.
    """
    result = yfc.custom_screen(criteria, sort_field, sort_dir == "ASC", limit)
    return ScreenerResponse.from_response(result).to_output()


@mcp.tool()
def get_predefined_screen(ctx: Context, screen_id: str, count: int = 25) -> str:
    """Get a predefined stock screen from Yahoo Finance.

    screen_id: one of:
      - 'most_actives' — highest volume today
      - 'day_gainers' — biggest percentage gainers today
      - 'day_losers' — biggest percentage losers today
      - 'aggressive_small_caps' — high-growth small caps
      - 'growth_technology_stocks' — growing tech stocks
      - 'most_shorted_stocks' — highest short interest
      - 'undervalued_large_caps' — large caps trading below intrinsic value
      - 'undervalued_growth_stocks' — growth stocks at low valuations
      - 'small_cap_gainers' — small cap stocks gaining today
    count: number of results to return (default 25).

    Uses Yahoo Finance via yfinance (no API key required). Data is 15-minute delayed.
    """
    return ScreenerResponse.from_response(yfc.predefined_screen(screen_id, count)).to_output()


@mcp.tool()
def get_institutional_ownership(ctx: Context, symbol: str) -> str:
    """Get top institutional holders of a stock: holder name, shares held, percentage
    held, position value, and recent change.

    Shows who the biggest institutional investors are (Vanguard, BlackRock, etc.)
    and whether they're accumulating or reducing positions.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_clients.table_helpers import fmt_large, fmt_number, list_table

    holders = yfc.institutional_holders(symbol)
    if not holders:
        return f"(no institutional ownership data for {symbol})"
    rows = [
        {
            "Holder": h.get("Holder", ""),
            "Shares": fmt_large(h.get("Shares")),
            "% Held": fmt_number(h.get("pctHeld", 0) * 100),
            "Value": fmt_large(h.get("Value")),
            "Change": fmt_number(h.get("pctChange", 0) * 100),
            "Date": str(h.get("Date Reported", ""))[:10],
        }
        for h in holders
    ]
    return list_table(rows)


@mcp.tool()
def get_short_interest(ctx: Context, symbol: str) -> str:
    """Get short interest data for a stock: shares short, short ratio (days to cover),
    short % of float, and month-over-month change.

    Useful for gauging squeeze risk on CSP positions and identifying heavily shorted names.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """
    from trading_clients.table_helpers import fmt_large, fmt_number, kv_table

    data = yfc.short_interest(symbol)
    if not any(data.values()):
        return f"(no short interest data for {symbol})"
    result: dict[str, str] = {}
    if data["sharesShort"] is not None:
        result["Shares Short"] = fmt_large(data["sharesShort"])
    if data["sharesShortPriorMonth"] is not None:
        result["Shares Short (Prior Month)"] = fmt_large(data["sharesShortPriorMonth"])
    if data["shortRatio"] is not None:
        result["Short Ratio (Days to Cover)"] = fmt_number(data["shortRatio"])
    if data["shortPercentOfFloat"] is not None:
        result["Short % of Float"] = fmt_number(data["shortPercentOfFloat"] * 100) + "%"
    return kv_table(result)


# ═══════════════════════════════════════════════════════════════
# YouTube
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def get_youtube_transcript(ctx: Context, url: str) -> str:
    """Get the transcript of a YouTube video.

    Extracts auto-generated or manual captions and returns the full text.
    Useful for analyzing financial commentary, earnings calls, or market analysis videos.

    url: YouTube video URL or video ID (e.g. 'https://www.youtube.com/watch?v=abc123'
      or just 'abc123').
    """
    import re

    from youtube_transcript_api import YouTubeTranscriptApi

    # Extract video ID from URL or use as-is
    video_id = url
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        video_id = m.group(1)

    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    full_text = " ".join(s.text for s in transcript.snippets)
    kind = "auto-generated" if transcript.is_generated else "manual"
    return f"**Video ID:** {video_id}\n**Language:** {transcript.language} ({kind})\n\n{full_text}"


# ═══════════════════════════════════════════════════════════════


def main():
    mcp.run()


if __name__ == "__main__":
    main()
