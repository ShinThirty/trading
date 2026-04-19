import asyncio
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from math import gcd
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from trading_clients import btc_regime as btc
from trading_clients import indicators as ta
from trading_clients import options as opts
from trading_clients import regime
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.config import load_config
from trading_clients.endpoint import CONTRACT_MULTIPLIER, ApiError
from trading_clients.endpoints import alphavantage as av
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import fmp, fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    CANCEL_ORDER,
    CRYPTO_BARS,
    CRYPTO_SNAPSHOT,
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
    CryptoBarsRequest,
    CryptoSnapshotRequest,
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
from trading_clients.portfolio import (
    AccountSummary,
    PortfolioSummary,
    compact_portfolio_summary,
    format_greeks_compact,
    format_greeks_detail,
    format_portfolio_summary,
    parse_fidelity_folder,
)
from trading_clients.table_helpers import (
    fmt_large,
    fmt_number,
    kv_table,
    list_table,
    to_float,
    to_float_zero,
)
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
            await client.aclose()


mcp = FastMCP("trading-mcp", lifespan=lifespan)

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _year_ago(d: date) -> date:
    """Return a date ~1 year before *d*, handling leap years."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


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


async def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    """Validate market state before placing an order."""
    tradier = ctx.request_context.lifespan_context.get("tradier")
    if tradier is None:
        return  # skip check if Tradier not configured
    clock = await tradier.get(t.CLOCK, t.EmptyRequest())
    state = clock.data.get("state", "closed")
    if order_type == "MARKET" and state != "open" and not extended_hours:
        raise RuntimeError(
            f"MARKET orders require regular hours (state: {state}). "
            "Use a LIMIT order, or wait for market open."
        )


async def _webull_get_with_retry(client: Any, endpoint: Any, request: Any, retries: int = 2) -> Any:
    """Call client.get with retry on 429 rate limit errors."""
    for attempt in range(retries + 1):
        try:
            return await client.get(endpoint, request)
        except ApiError as e:
            if e.status_code == 429 and attempt < retries:
                await asyncio.sleep(2)
                continue
            raise


async def _write_temp_file(content: str, suffix: str, prefix: str) -> str:

    def _sync_write() -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, prefix=prefix, delete=False)
        f.write(content)
        f.close()
        return f.name

    return await asyncio.to_thread(_sync_write)


# ── Portfolio helpers ────────────────────────────────────────


async def _fetch_accounts(
    webull: Any,
    fidelity_folder: str | None = None,
) -> tuple[list, dict[str, str]]:
    """Fetch balance + positions for all Webull accounts, optionally including Fidelity.

    Returns (list[AccountSummary], errors dict). Cash equivalents (SGOV, etc.)
    are reclassified from market_value to cash in each AccountSummary.
    """
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    if not account_list.accounts:
        errors["Webull"] = "No accounts found"

    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", acct.get("account_type", aid))
        atype = acct.get("account_type", "")

        try:
            bal = await _webull_get_with_retry(webull, BALANCE, AccountRequest(aid))
        except Exception as e:
            errors[label] = str(e)
            continue

        nlv = to_float_zero(bal.net_liquidation)
        cash = to_float_zero(bal.cash_balance)
        mv = to_float_zero(bal.market_value)

        try:
            pos_resp = await _webull_get_with_retry(webull, POSITIONS, AccountRequest(aid))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        cash_equiv_value = sum(p["value"] for p in positions if p.get("is_cash"))
        cash += cash_equiv_value
        mv -= cash_equiv_value

        summaries.append(
            AccountSummary(
                account_id=aid,
                label=label,
                broker="Webull",
                account_type=atype,
                nlv=nlv,
                cash=cash,
                market_value=mv,
                day_pnl=to_float_zero(bal.day_pnl),
                unrealized_pnl=to_float_zero(bal.unrealized_pnl),
                positions=positions,
            )
        )

    if fidelity_folder:
        try:
            summaries.extend(await parse_fidelity_folder(fidelity_folder))
        except Exception as e:
            errors["Fidelity"] = str(e)

    return summaries, errors


async def _fetch_all_positions(
    webull: Any,
    fidelity_folder: str | None = None,
) -> tuple[list[dict], list[str]]:
    """Fetch a flat list of normalized positions across all accounts.

    Returns (positions, errors). Lighter than _fetch_accounts — skips
    balance calls. Used by tools that only need positions (greeks, hedge).
    """
    all_positions: list[dict] = []
    errors: list[str] = []

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", aid)
        try:
            pos_resp = await _webull_get_with_retry(webull, POSITIONS, AccountRequest(aid))
            all_positions.extend(pos_resp.to_normalized())
        except Exception as e:
            errors.append(f"{label}: {e}")

    if fidelity_folder:
        for acct in await parse_fidelity_folder(fidelity_folder):
            all_positions.extend(acct.positions)

    return all_positions, errors


def _compute_csp_collateral(positions: list[dict]) -> float:
    """Sum collateral for all short puts in a position list."""
    total = 0.0
    for p in positions:
        if not p.get("is_option") or p.get("option_type") != "put":
            continue
        qty = p.get("quantity", 0)
        if qty >= 0:
            continue
        total += p.get("strike", 0) * CONTRACT_MULTIPLIER * abs(qty)
    return total


async def _fetch_total_nlv(webull: Any) -> float:
    """Sum NLV across all Webull accounts."""
    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    total = 0.0
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        try:
            bal = await _webull_get_with_retry(webull, BALANCE, AccountRequest(aid))
            total += to_float_zero(bal.net_liquidation)
        except Exception:
            continue
    return total


async def _conviction_data(finnhub_client, tradier_client, symbol: str) -> dict[str, Any]:
    """Shared conviction computation used by get_conviction_metrics and get_entry_signals."""
    basics_r, fin_r, quote_r = await asyncio.gather(
        finnhub_client.get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol)),
        finnhub_client.get(
            fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, "quarterly")
        ),
        tradier_client.get(t.QUOTES, t.GetQuotesRequest(symbol)),
        return_exceptions=True,
    )

    basics = None if isinstance(basics_r, BaseException) else basics_r
    fin = None if isinstance(fin_r, BaseException) else fin_r
    quote_resp = None if isinstance(quote_r, BaseException) else quote_r

    metric = basics.data.get("metric", {}) if basics else {}
    pe = to_float(metric.get("peNormalizedAnnual"))
    roe = to_float(metric.get("roeTTM"))
    de = to_float(metric.get("totalDebt/totalEquityAnnual"))

    q = quote_resp.quotes[0] if quote_resp and quote_resp.quotes else {}
    price = to_float(q.get("last"))
    high_52w = to_float(q.get("week_52_high"))

    quarters = fin.income_numeric(8) if fin else []

    drawdown_pct = None
    if price and high_52w and high_52w > 0:
        drawdown_pct = (price - high_52w) / high_52w * 100

    rev_growth = None
    current_q = None
    prior_q = None
    if len(quarters) >= 2:
        current_q = quarters[0]
        current_rev = current_q.get("Revenue")
        cur_fy = current_q.get("fiscal_year")
        cur_fq = current_q.get("fiscal_quarter")
        if current_rev and cur_fy and cur_fq:
            for q_row in quarters[1:]:
                if q_row.get("fiscal_quarter") == cur_fq and q_row.get("fiscal_year") == cur_fy - 1:
                    prior_rev = q_row.get("Revenue")
                    if prior_rev and prior_rev > 0:
                        prior_q = q_row
                        rev_growth = (current_rev - prior_rev) / prior_rev * 100
                    break

    margins: list[tuple[str, float]] = []
    for q_row in quarters[:4]:
        rev = q_row.get("Revenue")
        op_inc = q_row.get("Operating Income")
        period = q_row.get("period", "")
        if rev and op_inc and rev > 0:
            margins.append((period, op_inc / rev * 100))

    margin_trend = None
    if len(margins) >= 2:
        if margins[0][1] > margins[1][1] + 0.5:
            margin_trend = "Expanding"
        elif margins[0][1] < margins[1][1] - 0.5:
            margin_trend = "Compressing"
        else:
            margin_trend = "Stable"

    peg = None
    peg_valid = True
    peg_note = ""
    if pe is not None and rev_growth is not None:
        if pe < 0:
            peg_valid = False
            peg_note = "Negative P/E (unprofitable) — PEG not meaningful, use raw P/E"
        elif rev_growth <= 0:
            peg_valid = False
            peg_note = "Negative/zero growth — PEG not meaningful, use raw P/E"
        elif margin_trend == "Compressing":
            peg_valid = False
            peg_note = "Margins compressing — PEG unreliable, use raw P/E"
        else:
            peg = pe / rev_growth

    if peg is not None and peg_valid:
        if peg < 1.5:
            size = "Full — PEG < 1.5"
        elif peg <= 3.0:
            size = "Standard — PEG 1.5-3.0"
        else:
            size = "Reduced — PEG > 3.0"
        if pe and pe > 80:
            size = "Reduced — PEG > 3.0 | P/E >80 hard cap: never full-size"
    elif pe is not None and pe > 0:
        if pe < 15:
            size = "Full — P/E < 15"
        elif pe <= 25:
            size = "Standard — P/E 15-25"
        else:
            size = "Reduced — P/E > 25"
    elif pe is not None and pe < 0:
        size = "Reduced — negative P/E (unprofitable)"
    else:
        size = "Unable to determine — missing P/E data"

    return {
        "pe": pe,
        "roe": roe,
        "de": de,
        "price": price,
        "high_52w": high_52w,
        "drawdown_pct": drawdown_pct,
        "rev_growth": rev_growth,
        "current_q": current_q,
        "prior_q": prior_q,
        "margins": margins,
        "margin_trend": margin_trend,
        "peg": peg,
        "peg_valid": peg_valid,
        "peg_note": peg_note,
        "size": size,
    }


# ═══════════════════════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════════════════════

# ── Webull — Brokerage (Account, Orders, Market Data) ────────

# ── Account ──────────────────────────────────────────────────


@mcp.tool()
async def get_account_balance(ctx: Context, account_id: str) -> str:
    """Get account balance: net liquidation, cash, buying power, market value, day P&L,
    unrealized P&L, margin info.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    resp = await client.get(BALANCE, AccountRequest(client.ensure_account_id(account_id)))
    return resp.to_output()


@mcp.tool()
async def get_account_positions(ctx: Context, account_id: str) -> str:
    """Get all current portfolio holdings including option positions with full leg details
    (strike, expiration, option type, strategy). Returns each position's symbol, type,
    quantity, cost, last price, and unrealized P&L.

    account_id: Webull account ID (use get_app_subscriptions to find it).
    """
    client = _webull(ctx)
    resp = await client.get(POSITIONS, AccountRequest(client.ensure_account_id(account_id)))
    return resp.to_output()


# ── Orders ───────────────────────────────────────────────────


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


# ── Order Management (unified for stocks + options) ─────────


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
    # Preview uses the same request structure as place_order but via preview endpoint
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


@mcp.tool()
async def refresh_webull_token(ctx: Context) -> str:
    """Create a new Webull API access token and save it to ~/.tradingrc.

    Use this when Webull tools fail with 401 errors (token expired after 15 days
    of inactivity). After running this tool, the new token must be verified in the
    Webull App: Menu > Messages > OpenAPI Notifications.

    The token status will be PENDING until verified. Webull tools will fail until
    verification is complete.
    """
    client = _webull(ctx)
    token = await client._create_token()
    return (
        f"New token created: {token[:8]}...\n\n"
        "**Action required:** Verify this token in the Webull App:\n"
        "Menu > Messages > OpenAPI Notifications\n\n"
        "Token is PENDING until verified. Webull tools will fail until then."
    )


@mcp.tool()
async def get_app_subscriptions(ctx: Context) -> str:
    """Get all Webull accounts linked to this API key.

    Returns Account ID, Account Number, Type, and Label for each account.
    IMPORTANT: Use the 'Account ID' column (not 'Account Number') as the account_id
    parameter for all other Webull tools.
    """
    return (await _webull(ctx).get(ACCOUNT_LIST, EmptyRequest())).to_output()


@mcp.tool()
async def get_portfolio_summary(
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
    summaries, errors = await _fetch_accounts(_webull(ctx), fidelity_folder)
    portfolio = PortfolioSummary(summaries, errors)
    full_output = format_portfolio_summary(portfolio)

    # Save full details to temp file, return compact summary
    path = await _write_temp_file(full_output, ".md", "portfolio_")

    return compact_portfolio_summary(portfolio, path)


@mcp.tool()
async def get_csp_utilization(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Calculate CSP collateral utilization across all accounts.

    Shows total cash-secured put collateral vs available cash (including SGOV),
    utilization %, remaining capacity, and per-position detail. Use before
    writing new CSPs to check the 60% cash utilization limit.

    fidelity_folder: path to folder containing Fidelity Positions_*.csv files
      (e.g. '~/Downloads/fidelity'). Omit to show Webull only.
    """

    summaries, _ = await _fetch_accounts(_webull(ctx), fidelity_folder)

    csp_rows: list[dict[str, str]] = []
    total_collateral = 0.0
    total_cash = 0.0

    for acct in summaries:
        total_cash += acct.cash
        for p in acct.positions:
            if not p.get("is_option") or p.get("option_type") != "put":
                continue
            qty = p.get("quantity", 0)
            if qty >= 0:
                continue
            strike = p.get("strike", 0)
            contracts = abs(qty)
            collateral = strike * CONTRACT_MULTIPLIER * contracts
            total_collateral += collateral
            csp_rows.append(
                {
                    "Account": acct.label,
                    "Underlying": p.get("underlying", p.get("symbol", "")),
                    "Strike": fmt_number(strike),
                    "Exp": p.get("expiration", ""),
                    "Qty": fmt_number(contracts, 0),
                    "Collateral": fmt_number(collateral),
                }
            )

    # 4. Build output
    utilization = (total_collateral / total_cash * 100) if total_cash > 0 else 0
    remaining = total_cash - total_collateral
    status = "OVER LIMIT" if utilization > 60 else "OK"

    summary = kv_table(
        {
            "Total Cash (incl. SGOV)": f"${fmt_number(total_cash)}",
            "Total CSP Collateral": f"${fmt_number(total_collateral)}",
            "Utilization": f"{utilization:.1f}% ({status} — limit 60%)",
            "Remaining Capacity": f"${fmt_number(remaining)}",
        }
    )

    sections = [f"## CSP Collateral Utilization\n\n{summary}"]
    if csp_rows:
        sections.append(f"\n### Open CSPs ({len(csp_rows)} positions)\n")
        sections.append(list_table(csp_rows))
    else:
        sections.append("\nNo open CSP positions found.")

    return "\n".join(sections)


@mcp.tool()
async def get_free_capital(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> str:
    """Calculate free (deployable) capital across all brokerage accounts.

    For each account shows total cash/money market, CSP collateral tied up,
    liquid holdings (SGOV), and resulting free capital.

    Free Capital = Cash/MM + Liquid Holdings - CSP Collateral

    Rules:
    - Short puts tie up collateral = strike x 100 per contract
    - Covered calls do NOT tie up additional collateral
    - Long options don't tie up collateral
    - SGOV (0-3 month treasury) is treated as liquid/deployable

    fidelity_folder: path to folder containing Fidelity Portfolio_Positions_*.csv
      files (e.g. '~/Downloads/fidelity'). Omit to show Webull only.
    """

    summaries, errors = await _fetch_accounts(_webull(ctx), fidelity_folder)

    rows: list[dict[str, str]] = []
    grand_cash = 0.0
    grand_collateral = 0.0
    grand_liquid = 0.0
    grand_free = 0.0

    for acct in summaries:
        acct_liquid = sum(
            p.get("value", 0.0)
            for p in acct.positions
            if p.get("is_cash") and p.get("symbol", "").upper() == "SGOV"
        )
        acct_cash_mm = acct.cash - acct_liquid
        acct_collateral = _compute_csp_collateral(acct.positions)
        acct_free = acct.cash - acct_collateral

        rows.append(
            {
                "Account": acct.label,
                "Broker": acct.broker,
                "Cash/MM": f"${fmt_number(acct_cash_mm)}",
                "SGOV": f"${fmt_number(acct_liquid)}",
                "CSP Collateral": f"${fmt_number(acct_collateral)}",
                "Free Capital": f"${fmt_number(acct_free)}",
            }
        )

        grand_cash += acct_cash_mm
        grand_collateral += acct_collateral
        grand_liquid += acct_liquid
        grand_free += acct_free

    # Total row
    rows.append(
        {
            "Account": "**Total**",
            "Broker": "",
            "Cash/MM": f"**${fmt_number(grand_cash)}**",
            "SGOV": f"**${fmt_number(grand_liquid)}**",
            "CSP Collateral": f"**${fmt_number(grand_collateral)}**",
            "Free Capital": f"**${fmt_number(grand_free)}**",
        }
    )

    # 4. Build output
    total_available = grand_cash + grand_liquid
    utilization = (grand_collateral / total_available * 100) if total_available > 0 else 0

    summary = kv_table(
        {
            "Total Available (Cash + SGOV)": f"${fmt_number(total_available)}",
            "Total CSP Collateral": f"${fmt_number(grand_collateral)}",
            "Total Free Capital": f"${fmt_number(grand_free)}",
            "Collateral Utilization": f"{utilization:.1f}%",
        }
    )

    sections = [f"## Free Capital\n\n{summary}"]
    sections.append(f"\n### Per Account\n\n{list_table(rows)}")

    if errors:
        sections.append("\n### Errors")
        for label, err in errors.items():
            sections.append(f"- {label}: {err}")

    return "\n".join(sections)


@mcp.tool()
async def get_cc_coverage(
    ctx: Context,
    account_id: str,
) -> str:
    """Calculate covered call coverage ratio per underlying in a Webull account.

    For each stock position with short calls, shows total shares, covered shares,
    uncovered shares, and coverage %. Use before writing new CCs to decide how
    many contracts to sell.

    Coverage guidance from the decision framework:
    - 0-25%: High conviction hold (minimal income, max upside)
    - 50-75%: Growth with income (balanced)
    - 75-100%: Exit/neutral (max income, capped upside)

    account_id: Webull account ID.
    """

    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    pos_resp = await _webull_get_with_retry(client, POSITIONS, AccountRequest(aid))
    positions = pos_resp.to_normalized()

    # Collect shares and short calls per underlying
    shares_by_sym: dict[str, float] = {}
    calls_by_sym: dict[str, list[dict]] = {}

    for p in positions:
        if p.get("is_cash"):
            continue
        if p.get("is_option"):
            # Short calls: negative quantity, option_type == "call"
            if p.get("option_type") == "call" and p.get("quantity", 0) < 0:
                sym = p.get("underlying", "")
                calls_by_sym.setdefault(sym, []).append(p)
        else:
            sym = p.get("symbol", "")
            qty = p.get("quantity", 0)
            if qty > 0:
                shares_by_sym[sym] = shares_by_sym.get(sym, 0) + qty

    # Build coverage table for symbols that have either shares or short calls
    all_syms = sorted(set(shares_by_sym) | set(calls_by_sym))
    if not all_syms:
        return "(no stock or short call positions found)"

    rows: list[dict[str, str]] = []
    for sym in all_syms:
        total_shares = shares_by_sym.get(sym, 0)
        calls = calls_by_sym.get(sym, [])
        covered_contracts = sum(abs(c.get("quantity", 0)) for c in calls)
        covered_shares = covered_contracts * CONTRACT_MULTIPLIER
        uncovered = max(0, total_shares - covered_shares)
        coverage_pct = (covered_shares / total_shares * 100) if total_shares > 0 else 0

        # Determine coverage label
        if coverage_pct == 0:
            label = "None"
        elif coverage_pct <= 25:
            label = "High conviction"
        elif coverage_pct <= 50:
            label = "Moderate"
        elif coverage_pct <= 75:
            label = "Growth + income"
        else:
            label = "Exit/neutral"

        row: dict[str, str] = {
            "Symbol": sym,
            "Shares": fmt_number(total_shares, 0),
            "Covered": fmt_number(covered_shares, 0),
            "Uncovered": fmt_number(uncovered, 0),
            "Coverage": f"{coverage_pct:.0f}%",
            "Label": label,
        }

        # Show call details inline if any
        if calls:
            call_details = ", ".join(
                f"${fmt_number(c.get('strike'))} {c.get('expiration', '')}" for c in calls
            )
            row["Calls"] = call_details

        rows.append(row)

    return f"## CC Coverage Ratio\n\n{list_table(rows)}"


@mcp.tool()
async def get_cc_chain_pnl(
    ctx: Context,
    account_id: str,
    symbol: str,
    option_type: str = "call",
    start_date: str | None = None,
) -> str:
    """Calculate the running P&L of a covered call or CSP roll chain.

    Traces all filled option orders for a symbol, sums credits (SELL) and
    debits (BUY), and shows the chain P&L. Useful before rolling to see
    whether the chain is profitable or underwater.

    account_id: Webull account ID.
    symbol: underlying ticker (e.g. 'AMZN').
    option_type: 'call' for covered calls, 'put' for CSPs (default 'call').
    start_date: earliest date to search (YYYY-MM-DD). Defaults to 90 days ago.
    """

    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    if not start_date:
        start_date = (date.today().replace(day=1) - timedelta(days=90)).isoformat()

    response = await client.get(
        ORDER_HISTORY,
        GetOrderHistoryRequest(
            aid, page_size=100, start_date=start_date, end_date=date.today().isoformat()
        ),
    )

    # Filter for filled option orders matching symbol and option_type
    opt_type = option_type.lower()
    chain_orders: list[dict] = []
    for combo in response.combos:
        for o in combo.get("orders", []):
            if o.get("status") != "FILLED":
                continue
            if o.get("instrument_type") != "OPTION":
                continue
            if (o.get("symbol") or "").upper() != symbol.upper():
                continue
            legs = o.get("legs", [])
            if not legs:
                continue
            leg = legs[0]
            if (leg.get("option_type") or "").lower() != opt_type:
                continue
            chain_orders.append(o)

    if not chain_orders:
        return f"(no filled {opt_type} orders for {symbol} since {start_date})"

    # Sort by fill time
    chain_orders.sort(key=lambda o: o.get("filled_time_at") or o.get("place_time_at") or "")

    # Build chain detail and compute P&L
    rows: list[dict[str, str]] = []
    total_credit = 0.0
    total_debit = 0.0

    for o in chain_orders:
        side = o.get("side", "")
        qty = to_float_zero(o.get("filled_quantity"))
        price = to_float_zero(o.get("filled_price"))
        amount = price * qty * CONTRACT_MULTIPLIER
        leg = o.get("legs", [{}])[0]

        if side == "SELL":
            total_credit += amount
        else:
            total_debit += amount

        rows.append(
            {
                "Date": (o.get("filled_time_at") or o.get("place_time_at") or "")[:10],
                "Side": side,
                "Strike": fmt_number(leg.get("strike_price")),
                "Exp": leg.get("option_expire_date", ""),
                "Qty": fmt_number(qty, 0),
                "Fill": fmt_number(price),
                "Amount": f"{'+' if side == 'SELL' else '-'}${fmt_number(amount)}",
            }
        )

    chain_pnl = total_credit - total_debit
    pnl_sign = "+" if chain_pnl >= 0 else ""

    type_label = "Covered Call" if opt_type == "call" else "CSP"
    summary = kv_table(
        {
            "Symbol": symbol.upper(),
            "Chain Type": type_label,
            "Total Credits (SELL)": f"+${fmt_number(total_credit)}",
            "Total Debits (BUY)": f"-${fmt_number(total_debit)}",
            "Chain P&L": f"{pnl_sign}${fmt_number(chain_pnl)}",
            "Orders": str(len(chain_orders)),
        }
    )

    sections = [f"## {symbol.upper()} {type_label} Chain P&L\n\n{summary}"]
    sections.append(f"\n### Order History\n\n{list_table(rows)}")

    return "\n".join(sections)


@mcp.tool()
async def get_portfolio_greeks(
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
    webull = _webull(ctx)
    tradier = _tradier(ctx)

    all_positions, errors = await _fetch_all_positions(webull, fidelity_folder)

    # Build OCC symbols for all option positions
    option_positions = [p for p in all_positions if p.get("is_option")]
    if not option_positions:
        return "(no option positions found)"

    occ_set: set[str] = set()
    for p in option_positions:
        occ_set.add(opts.build_occ(p["underlying"], p["expiration"], p["option_type"], p["strike"]))

    # 3. Batch quote Greeks from Tradier
    greeks_by_symbol: dict[str, dict] = {}
    quote_resp = await tradier.get(t.QUOTES, t.GetQuotesRequest(",".join(occ_set), greeks=True))
    for q in quote_resp.quotes:
        greeks = q.get("greeks") or {}
        if greeks:
            greeks_by_symbol[q.get("symbol", "")] = greeks

    # 4. Aggregate and format
    result = opts.aggregate_greeks(all_positions, greeks_by_symbol)

    detail = format_greeks_detail(result["totals"], result["by_underlying"])
    path = await _write_temp_file(detail, ".md", "greeks_")

    output = format_greeks_compact(result["totals"], len(option_positions), path)
    if errors:
        output += "\nErrors: " + "; ".join(errors)
    return output


# ── Webull Market Data ──────────────────────────────────────


@mcp.tool()
async def get_instruments(ctx: Context, symbols: str, category: str = "US_STOCK") -> str:
    """Look up instrument details for symbols: instrument_id, exchange, currency,
    and trading attributes (shortable, fractionable, marginable).

    symbols: comma-separated ticker symbols (e.g. 'AAPL,TSLA'). Max 100.
    category: 'US_STOCK' (default) or 'US_ETF'.
    """
    resp = await _webull(ctx).get(INSTRUMENTS, GetInstrumentsRequest(symbols, category))
    return resp.to_output()


# ═══════════════════════════════════════════════════════════════
# TRADIER — Option Chains, Greeks, IV
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_option_expirations(ctx: Context, symbol: str) -> str:
    """Get all available option expiration dates for an underlying symbol.
    Use this first to discover which expirations are available before fetching
    the full chain.

    symbol: underlying ticker symbol (e.g. 'AAPL', 'SPY', 'TSLA').
    Returns a list of expiration dates as strings (YYYY-MM-DD).

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))).to_output()


@mcp.tool()
async def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.STRIKES, t.GetStrikesRequest(symbol, expiration))).to_output()


@mcp.tool()
async def get_option_chain(
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
    tradier = _tradier(ctx)
    quote_resp, resp = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks)),
    )
    last_price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if resp.options and strike_count > 0 and last_price:
        strikes = sorted({o["strike"] for o in resp.options})
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - last_price))
        lo = max(0, atm_idx - strike_count)
        hi = min(len(strikes), atm_idx + strike_count + 1)
        keep = set(strikes[lo:hi])
        resp.options = [o for o in resp.options if o["strike"] in keep]
    return resp.to_output()


@mcp.tool()
async def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.OPTION_LOOKUP, t.GetLookupRequest(underlying))).to_output()


# ── Options Analytics ──────────────────────────────────────


@mcp.tool()
async def get_expected_move(ctx: Context, symbol: str, expiration: str) -> str:
    """Compute the expected move for a stock at a given option expiration.

    Shows the ATM straddle price (expected 1-sigma move), implied volatility,
    historical volatility, and IV/HV ratio. Useful for sizing positions and
    evaluating whether options are cheap or expensive.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: option expiration date (YYYY-MM-DD, from get_option_expirations).

    Requires [tradier] section in ~/.tradingrc.
    """

    tradier = _tradier(ctx)

    # Fetch quote, chain, and history concurrently
    quote, chain, history = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks=True)),
        tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily")),
    )

    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    if not chain.options:
        return f"(no option chain for {symbol} at {expiration})"

    # Expected move from ATM straddle
    em = opts.expected_move(chain.options, stock_price)

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
async def analyze_option_strategy(
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
    quote = await tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    # Fetch option chain for each unique expiration
    unique_exps = sorted({leg["expiration"] for leg in legs})
    chains: dict[str, list[dict]] = {}
    for exp in unique_exps:
        chain = await tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp, greeks=True))
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
                "spread_pct": opts.bid_ask_spread_pct(opt),
                "occ_symbol": opt.get("symbol", ""),
                "expiration": leg_exp,
            }
        )

    # Route to appropriate analyzer
    is_multi_exp = len(unique_exps) > 1
    if is_multi_exp:
        from trading_clients.options_multi_exp import analyze_multi_exp_strategy

        risk_free_rate = 0.0
        try:
            fred_client = _fred(ctx)
            obs = await fred_client.get(
                fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 1)
            )
            if obs.observations:
                val = obs.observations[0].get("value")
                if val:
                    risk_free_rate = float(val) / 100.0
        except Exception:
            pass
        result = analyze_multi_exp_strategy(enriched_legs, stock_price, risk_free_rate)
    else:
        result = opts.strategy_analysis(enriched_legs, stock_price, equity_position)

    # Build leg detail table

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
        sp = el.get("spread_pct")
        row["Spread"] = f"{sp:.0f}%" if sp is not None else ""
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
    leg_qtys = [el.get("quantity", 1) for el in enriched_legs]
    units = gcd(*leg_qtys) if leg_qtys else 1
    per_share = net / units
    total = net * CONTRACT_MULTIPLIER
    if net >= 0:
        data["Net Credit"] = f"${fmt_number(per_share)} per share (${fmt_number(total)} total)"
    else:
        data["Net Debit"] = (
            f"${fmt_number(abs(per_share))} per share (${fmt_number(abs(total))} total)"
        )

    data["Max Profit"] = f"${fmt_number(result['max_profit'])}"
    data["Max Loss"] = f"${fmt_number(result['max_loss'])}"

    # Credit-to-width ratio for credit spreads
    _CREDIT_SPREAD_TYPES = {
        "Bull Put Spread",
        "Bear Call Spread",
        "Iron Condor",
        "Iron Butterfly",
    }
    strategy_type = result.get("strategy_type", "")
    if strategy_type in _CREDIT_SPREAD_TYPES and net > 0:
        strikes = sorted({el["strike"] for el in enriched_legs})
        if len(strikes) >= 2:
            if strategy_type in ("Iron Condor", "Iron Butterfly"):
                # Use the wider side (put spread or call spread width)
                width = (strikes[-1] - strikes[-2] + strikes[1] - strikes[0]) / 2
            else:
                width = strikes[-1] - strikes[0]
            if width > 0:
                ratio = per_share / width * 100
                warning = " \u26a0 Below 30% minimum" if ratio < 30 else ""
                data["Credit/Width"] = f"{ratio:.0f}%{warning}"

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
        rfr_pct = f"{risk_free_rate * 100:.2f}%"
        data["Note"] = (
            f"P&L evaluated at near expiration using Black-Scholes (r={rfr_pct}) for far-dated legs"
        )

    wide_spread_legs = [el for el in enriched_legs if (el.get("spread_pct") or 0) > 10]

    sections = [
        f"## {symbol} {result.get('strategy_type', 'Strategy')} Analysis",
        "",
        "### Legs",
        list_table(leg_rows),
        "",
        "### Summary",
        kv_table(data),
    ]
    if wide_spread_legs:
        warnings = []
        for el in wide_spread_legs:
            warnings.append(
                f"- {el['option_type'].upper()} {fmt_number(el['strike'])} {el['expiration']}"
                f": {el['spread_pct']:.0f}% spread (bid {fmt_number(el['bid'])}"
                f" / ask {fmt_number(el['ask'])})"
            )
        sections.extend(
            [
                "",
                "### Liquidity Warning",
                "Wide bid-ask spread (>10% of ask) — mid price may be unreliable:",
                *warnings,
            ]
        )
    return "\n".join(sections)


@mcp.tool()
async def analyze_roll(
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

    tradier = _tradier(ctx)

    # Parse OCC symbol
    try:
        underlying, current_exp, option_type, current_strike = opts.parse_occ(current_symbol)
    except (IndexError, ValueError):
        return f"(invalid OCC symbol: {current_symbol})"

    if target_strike is None:
        target_strike = current_strike

    # Fetch current option quote, stock price, and target chain concurrently
    cur_resp, stock_resp, chain = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(current_symbol, greeks=True)),
        tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(underlying, target_expiration, greeks=True)),
    )

    if not cur_resp.quotes:
        return f"(no quote for {current_symbol})"

    stock_price = 0.0
    if stock_resp.quotes:
        stock_price = float(
            stock_resp.quotes[0].get("last") or stock_resp.quotes[0].get("close", 0)
        )

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
    net_total = net * quantity * CONTRACT_MULTIPLIER
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
async def get_tradier_history(
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
    resp = await _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, interval, start, end))
    if limit and resp.days:
        resp.days = resp.days[-limit:]
    return resp.to_output()


@mcp.tool()
async def search_symbols(ctx: Context, query: str, indexes: bool = False) -> str:
    """Search for stocks and ETFs by company name or partial symbol. Results are sorted
    by average volume (most liquid first). Useful for stock discovery.

    query: search term — company name or partial symbol (e.g. 'apple', 'semi', 'AI').
    indexes: set True to include index symbols in results.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.SEARCH, t.SearchRequest(query, indexes))).to_output()


@mcp.tool()
async def get_quote(ctx: Context, symbols: str, greeks: bool = False) -> str:
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
    return (await _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbols, greeks))).to_output()


@mcp.tool()
async def get_timesales(
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
        await _tradier(ctx).get(t.TIMESALES, t.GetTimesalesRequest(symbol, interval, start, end))
    ).to_output()


@mcp.tool()
async def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.CLOCK, t.EmptyRequest())).to_output()


# ── Technical Analysis ─────────────────────────────────────


@mcp.tool()
async def get_technical_indicators(
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
    resp = await _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, period))
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
async def get_company_news(
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
        await _finnhub(ctx).get(fh.COMPANY_NEWS, fh.CompanyNewsRequest(symbol, from_date, to_date))
    ).to_output()


@mcp.tool()
async def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.MARKET_NEWS, fh.MarketNewsRequest(category))).to_output()


@mcp.tool()
async def get_earnings_calendar(
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
    resp = await _finnhub(ctx).get(fh.EARNINGS_CALENDAR, fh.DateRangeRequest(from_date, to_date))
    if symbol:
        resp.earnings = [e for e in resp.earnings if e.get("symbol", "").upper() == symbol.upper()]
    resp.earnings = resp.earnings[:limit]
    return resp.to_output()


@mcp.tool()
async def get_basic_financials(ctx: Context, symbol: str) -> str:
    """Get key financial metrics: P/E, P/B, EPS, dividend yield, 52-week high/low,
    market cap, beta, ROE, debt/equity.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = await _finnhub(ctx).get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol))
    return resp.to_output()


@mcp.tool()
async def get_eps_estimates(ctx: Context, symbol: str) -> str:
    """Get analyst EPS estimates for upcoming quarters and years: average, high, low,
    number of analysts, year-ago EPS, and growth rate.

    Periods: current quarter (0q), next quarter (+1q), current year (0y), next year (+1y).

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """

    data = await yfc.earnings_estimate(symbol)
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
async def get_recommendation_trends(ctx: Context, symbol: str) -> str:
    """Get analyst recommendation trends: counts of strong buy, buy, hold, sell, and
    strong sell ratings by month.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.RECOMMENDATIONS, fh.SymbolRequest(symbol))).to_output()


@mcp.tool()
async def get_price_target(ctx: Context, symbol: str) -> str:
    """Get analyst consensus price target: current price, high, low, mean, and median
    target prices.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """

    data = await yfc.analyst_price_targets(symbol)
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
async def get_insider_transactions(ctx: Context, symbol: str, limit: int = 20) -> str:
    """Get recent insider transactions: buys, sells, and grants by company officers
    and directors.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: max number of transactions to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    resp = await _finnhub(ctx).get(fh.INSIDER_TRANSACTIONS, fh.SymbolRequest(symbol))
    resp.transactions = resp.transactions[:limit]
    return resp.to_output()


@mcp.tool()
async def get_company_peers(ctx: Context, symbol: str) -> str:
    """Get a list of peer/competitor symbols for a company.

    symbol: ticker symbol (e.g. 'AAPL').

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.PEERS, fh.SymbolRequest(symbol))).to_output()


# ═══════════════════════════════════════════════════════════════
# FMP — Fundamental Financial Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_company_profile(ctx: Context, symbol: str) -> str:
    """Get company profile: name, price, market cap, beta, avg volume, last dividend,
    52-week range, sector, industry, exchange, and CEO.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] section in ~/.tradingrc.
    """
    return (await _fmp(ctx).get(fmp.PROFILE, fmp.SymbolRequest(symbol))).to_output()


@mcp.tool()
async def get_income_statement(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get income statement from SEC filings: revenue, cost of revenue, gross profit,
    operating income, net income, EPS.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc. Falls back to Yahoo Finance
    if Finnhub has no data for the symbol.
    """

    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    output = result.income_markdown(limit)
    if output != "(no data)":
        return output

    # Fallback to Yahoo Finance
    data = await yfc.income_statement(symbol, freq, limit)
    if not data:
        return f"(no income statement data for {symbol})"

    def _fmt(v: float | None) -> str:
        if v is None:
            return ""
        if abs(v) >= 1e9:
            return f"{v / 1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"{v / 1e6:.1f}M"
        return fmt_number(v)

    rows = [
        {
            "Period": d["period"],
            "Revenue": _fmt(d["revenue"]),
            "Gross Profit": _fmt(d["gross_profit"]),
            "Operating Income": _fmt(d["operating_income"]),
            "Net Income": _fmt(d["net_income"]),
            "EPS": fmt_number(d["eps"]),
        }
        for d in data
    ]
    return f"(via Yahoo Finance)\n{list_table(rows)}"


@mcp.tool()
async def get_balance_sheet(
    ctx: Context, symbol: str, period: str = "annual", limit: int = 4
) -> str:
    """Get balance sheet from SEC filings: cash, current assets, total assets,
    current liabilities, long-term debt, total liabilities, total equity.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    return result.balance_sheet_markdown(limit)


@mcp.tool()
async def get_cash_flow(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get cash flow statement from SEC filings: operating cash flow, capex,
    investing/financing cash flows, dividends, buybacks.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarterly'.
    limit: number of periods to return (default 4).
    Requires [finnhub] section in ~/.tradingrc.
    """
    freq = "quarterly" if period in ("quarter", "quarterly") else "annual"
    result = await _finnhub(ctx).get(
        fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, freq)
    )
    return result.cash_flow_markdown(limit)


@mcp.tool()
async def get_key_metrics(ctx: Context, symbol: str, period: str = "annual", limit: int = 4) -> str:
    """Get key financial metrics: EV/EBITDA, ROE, ROA, current ratio, debt/equity, FCF yield.

    symbol: ticker symbol (e.g. 'AAPL').
    period: 'annual' or 'quarter'.
    limit: number of periods to return (default 4).
    Requires [fmp] section in ~/.tradingrc.
    """
    resp = await _fmp(ctx).get(fmp.KEY_METRICS, fmp.FinancialRequest(symbol, period, limit))
    return resp.to_output()


@mcp.tool()
async def get_dividend_history(ctx: Context, symbol: str) -> str:
    """Get dividend payment history: ex-date, pay date, record date, amount.

    symbol: ticker symbol (e.g. 'AAPL').
    Requires [fmp] or [tastytrade] section in ~/.tradingrc.
    """
    fmp_client = ctx.request_context.lifespan_context.get("fmp")
    if fmp_client:
        try:
            resp = await fmp_client.get(fmp.DIVIDEND_HISTORY, fmp.SymbolRequest(symbol))
            return resp.to_output()
        except ValueError:
            pass  # FMP paywall — fall through to TastyTrade
    tt_client = ctx.request_context.lifespan_context.get("tastytrade")
    if tt_client:
        resp = await tt_client.get(tt.DIVIDEND_HISTORY, tt.DividendHistoryRequest(symbol))
        return resp.to_output()
    raise RuntimeError(
        "No dividend data source available. Add [fmp] or [tastytrade] to ~/.tradingrc"
    )


@mcp.tool()
async def get_fmp_earnings_calendar(ctx: Context, symbol: str, limit: int = 5) -> str:
    """Get earnings history: date, EPS estimate/actual, revenue estimate/actual.

    symbol: ticker symbol (e.g. 'AAPL').
    limit: number of recent earnings to return (default 5).
    Requires [fmp] section in ~/.tradingrc.
    """
    return (await _fmp(ctx).get(fmp.EARNINGS, fmp.EarningsRequest(symbol, limit))).to_output()


@mcp.tool()
async def get_sector_performance(ctx: Context, date: str, exchange: str = "NYSE") -> str:
    """Get sector performance for a specific date: average percentage change for each
    of 11 sectors (Technology, Healthcare, Financial Services, etc.), sorted best to worst.

    Useful for understanding sector rotation and whether a stock's movement is
    stock-specific or sector-wide.

    date: trading date (YYYY-MM-DD). Use a recent trading day (not weekend/holiday).
    exchange: 'NYSE' (default) or 'NASDAQ'.

    Requires [fmp] section in ~/.tradingrc.
    """
    return (
        await _fmp(ctx).get(fmp.SECTOR_PERFORMANCE, fmp.SectorPerformanceRequest(date, exchange))
    ).to_output()


# ═══════════════════════════════════════════════════════════════
# FRED — Macroeconomic Data
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_economic_data(
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
    return (await _fred(ctx).get(fred.OBSERVATIONS, req)).to_output()


@mcp.tool()
async def get_fred_series_info(ctx: Context, series_id: str) -> str:
    """Get metadata for a FRED series: title, frequency, units, seasonal adjustment.

    series_id: FRED series ID (e.g. 'CPIAUCSL', 'GDP', 'VIXCLS').
    Requires [fred] section in ~/.tradingrc.
    """
    return (await _fred(ctx).get(fred.SERIES_INFO, fred.SeriesIdRequest(series_id))).to_output()


@mcp.tool()
async def get_upcoming_economic_releases(ctx: Context, limit: int = 20) -> str:
    """Get upcoming FRED data release dates: when CPI, GDP, jobs report will be published.

    limit: number of upcoming releases to return (default 20).
    Requires [fred] section in ~/.tradingrc.
    """
    return (await _fred(ctx).get(fred.RELEASES, fred.GetReleasesRequest(limit))).to_output()


@mcp.tool()
async def search_fred_series(ctx: Context, query: str, limit: int = 10) -> str:
    """Search for FRED economic data series by keyword.

    query: search terms (e.g. 'inflation', 'housing starts', 'consumer credit').
    limit: max results to return (default 10).

    Use the returned series_id with get_economic_data to fetch actual values.
    Requires [fred] section in ~/.tradingrc.
    """
    return (await _fred(ctx).get(fred.SEARCH, fred.SearchRequest(query, limit))).to_output()


# ═══════════════════════════════════════════════════════════════
# MARKET REGIME — Cross-Provider Aggregation
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_market_regime(ctx: Context) -> str:
    """Get current market regime classification across volatility, trend,
    macro, and sector dimensions.

    Aggregates FRED (VIX, yield curve, fed funds), Tradier (SPY technicals),
    FMP (sector performance), and TastyTrade (IV enrichment) into simple
    regime labels.

    Returns regime labels with supporting data:
    - Volatility: Low / Normal / Elevated / Crisis (VIX + term structure)
    - Trend: Uptrend / Sideways / Downtrend (SPY RSI + SMA 50/200)
    - Macro: Steep / Flat / Inverted yield curve (10Y-2Y + Fed funds)
    - Sectors: Risk-On / Rotation / Risk-Off (high-beta vs defensive)

    Requires [fred] and [tradier] sections in ~/.tradingrc.
    FMP and TastyTrade are optional enrichments.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    fmp_client = ctx.request_context.lifespan_context.get("fmp")
    tt_client = ctx.request_context.lifespan_context.get("tastytrade")

    # Fetch all required data concurrently
    tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("VIXCLS", 1)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("VXVCLS", 1)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("T10Y2Y", 130)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        tradier.get(
            t.HISTORY,
            t.GetHistoryRequest("SPY", "daily", start=_year_ago(date.today()).isoformat()),
        ),
        tradier.get(
            t.HISTORY,
            t.GetHistoryRequest("SMH", "daily", start=_year_ago(date.today()).isoformat()),
        ),
    ]

    # Optional providers
    if fmp_client:
        tasks.append(
            fmp_client.get(
                fmp.SECTOR_PERFORMANCE,
                fmp.SectorPerformanceRequest(date.today().isoformat()),
            )
        )
    if tt_client:
        tasks.append(tt_client.get(tt.MARKET_METRICS, tt.MarketMetricsRequest("SPY")))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Unpack required results
    vix_resp = results[0] if not isinstance(results[0], BaseException) else None
    vix3m_resp = results[1] if not isinstance(results[1], BaseException) else None
    spread_resp = results[2] if not isinstance(results[2], BaseException) else None
    ff_resp = results[3] if not isinstance(results[3], BaseException) else None
    spy_resp = results[4] if not isinstance(results[4], BaseException) else None
    smh_resp = results[5] if not isinstance(results[5], BaseException) else None

    # Unpack optional results
    idx = 6
    sector_resp = None
    if fmp_client:
        sector_resp = results[idx] if not isinstance(results[idx], BaseException) else None
        idx += 1
    tt_resp = None
    if tt_client:
        tt_resp = results[idx] if not isinstance(results[idx], BaseException) else None

    data: dict[str, str | None] = {}

    # Volatility regime
    vix_val, vix_date = regime.parse_fred_value(vix_resp.observations if vix_resp else [])
    vix3m_val, _ = regime.parse_fred_value(vix3m_resp.observations if vix3m_resp else [])
    if vix_val is not None:
        label, detail = regime.classify_volatility(vix_val, vix3m_val)
        date_suffix = f", {vix_date[5:]}" if vix_date else ""
        data["Volatility"] = f"{label} ({detail}{date_suffix})"

    # Trend regime
    if spy_resp and spy_resp.days:
        closes = [float(b["close"]) for b in spy_resp.days]
        price = closes[-1]
        rsi_vals = ta.rsi(closes)
        sma50_vals = ta.sma(closes, 50)
        sma200_vals = ta.sma(closes, 200)
        label, detail = regime.classify_trend(price, rsi_vals[-1], sma50_vals[-1], sma200_vals[-1])
        data["Trend"] = f"{label} ({detail})"

    # Macro regime
    spread_observations = spread_resp.observations if spread_resp else []
    spread_val, _ = regime.parse_fred_value(spread_observations)
    ff_observations = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_observations)
    prev_ff_obs = ff_observations[1:] if len(ff_observations) > 1 else []
    prev_ff_val, _ = regime.parse_fred_value(prev_ff_obs)
    label, detail = regime.classify_macro(spread_val, ff_val, prev_ff_val)
    data["Macro"] = f"{label} ({detail})"

    # Un-inversion trap detection (needs ~6 months of T10Y2Y history)
    spread_history = []
    for obs in spread_observations:
        v = obs.get("value", ".")
        if v != ".":
            try:
                spread_history.append(float(v))
            except (ValueError, TypeError):
                pass
    trap_warning = regime.detect_uninversion_trap(spread_history, spread_val, ff_val, prev_ff_val)
    if trap_warning:
        data["\u26a0 Macro"] = trap_warning

    # Sector regime (optional)
    if sector_resp and sector_resp.sectors:
        label, detail = regime.classify_sectors(sector_resp.sectors)
        data["Sectors"] = f"{label} ({detail})"

    # Semi divergence detection (SMH vs SPY relative performance)
    if smh_resp and smh_resp.days and spy_resp and spy_resp.days:
        smh_closes = [float(b["close"]) for b in smh_resp.days]
        spy_closes_all = [float(b["close"]) for b in spy_resp.days]
        semi_warning = regime.detect_semi_divergence(smh_closes, spy_closes_all)
        if semi_warning:
            data["\u26a0 Sectors"] = semi_warning

    # IV enrichment (optional)
    if tt_resp and tt_resp.items:
        item = tt_resp.items[0]
        iv_rank = item.get("tw-implied-volatility-index-rank")
        iv_pctl = item.get("implied-volatility-percentile")
        parts = []
        if iv_rank is not None:
            parts.append(f"IV Rank {float(iv_rank) * 100:.0f}%")
        if iv_pctl is not None:
            parts.append(f"IV Pctl {float(iv_pctl) * 100:.0f}%")
        if parts:
            data["IV Context"] = f"SPY {', '.join(parts)}"

    return f"## Market Regime\n\n{kv_table(data)}"


# ═══════════════════════════════════════════════════════════════
# BTC MACRO SIGNALS — Bitcoin Entry Signal Aggregation
# ═══════════════════════════════════════════════════════════════

_FNG_URL = "https://api.alternative.me/fng/"


async def _fetch_fear_greed() -> int | None:
    """Fetch current Crypto Fear & Greed Index from Alternative.me."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_FNG_URL, params={"limit": "1", "format": "json"})
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                return int(data[0]["value"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    return None


@mcp.tool()
async def get_crypto_quote(ctx: Context, symbols: str = "BTCUSD") -> str:
    """Get real-time crypto price snapshot from Webull.

    symbols: comma-separated crypto symbols (e.g. 'BTCUSD', 'BTCUSD,ETHUSD').
      Default: BTCUSD.

    Returns current price, change, bid/ask, and day range.
    Requires [webull] section in ~/.tradingrc.
    """
    client = _webull(ctx)
    resp = await client.get(CRYPTO_SNAPSHOT, CryptoSnapshotRequest(symbols))
    return resp.to_output()


@mcp.tool()
async def get_crypto_history(
    ctx: Context,
    symbol: str = "BTCUSD",
    interval: str = "D",
    count: int = 200,
) -> str:
    """Get historical OHLCV bars for a cryptocurrency from Webull.

    symbol: crypto symbol (e.g. 'BTCUSD', 'ETHUSD'). Default: BTCUSD.
    interval: bar interval — 'D' (daily), 'W' (weekly), 'M' (monthly),
      '1' (1min), '5' (5min), '30' (30min), '60' (60min). Default: D.
    count: number of bars to return (max 250). Default: 200.

    Returns OHLCV table sorted oldest to newest.
    Requires [webull] section in ~/.tradingrc.
    """
    client = _webull(ctx)
    resp = await client.get(CRYPTO_BARS, CryptoBarsRequest(symbol, timespan=interval, count=count))
    return resp.to_output()


@mcp.tool()
async def get_btc_entry_signals(ctx: Context) -> str:
    """Get Bitcoin entry signals combining macro indicators and BTC price
    technicals into a single scorecard.

    Macro signals (from FRED):
    - Halving Cycle: position in Bitcoin's ~4-year supply cycle
    - Monetary Policy: Fed funds rate direction (easing/tightening/holding)
    - Liquidity: M2 money supply YoY growth + 3mo acceleration
    - Dollar: DXY 20d/60d trend (weak dollar = bullish BTC)
    - Real Rates: 10Y yield minus CPI (negative = bullish BTC)
    - Risk Appetite: VIX level
    - Sentiment: Crypto Fear & Greed Index (contrarian indicator)

    Price technicals (from Webull crypto bars):
    - BTC price, drawdown from ATH
    - RSI(14), SMA(50), SMA(200)

    Correlation regime (from Webull + Tradier):
    - BTC vs QQQ (risk-on) and BTC vs GLD (store-of-value) 30-day correlation
    - Composite: overall macro favorability score

    Requires [fred], [webull], and [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    webull = _webull(ctx)
    tradier = _tradier(ctx)
    start_date = _year_ago(date.today()).isoformat()

    tasks: list[Any] = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("WM2NS", 60)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DTWEXBGS", 80)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS10", 1)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("CPIAUCSL", 13)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("VIXCLS", 1)),
        webull.get(CRYPTO_BARS, CryptoBarsRequest("BTCUSD", timespan="D", count=250)),
        webull.get(CRYPTO_SNAPSHOT, CryptoSnapshotRequest("BTCUSD")),
        _fetch_fear_greed(),
        tradier.get(t.HISTORY, t.GetHistoryRequest("QQQ", "daily", start=start_date)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("GLD", "daily", start=start_date)),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    ff_resp = results[0] if not isinstance(results[0], BaseException) else None
    m2_resp = results[1] if not isinstance(results[1], BaseException) else None
    dxy_resp = results[2] if not isinstance(results[2], BaseException) else None
    dgs10_resp = results[3] if not isinstance(results[3], BaseException) else None
    cpi_resp = results[4] if not isinstance(results[4], BaseException) else None
    vix_resp = results[5] if not isinstance(results[5], BaseException) else None
    bars_resp = results[6] if not isinstance(results[6], BaseException) else None
    snap_resp = results[7] if not isinstance(results[7], BaseException) else None
    fng_val = results[8] if not isinstance(results[8], BaseException) else None
    qqq_resp = results[9] if not isinstance(results[9], BaseException) else None
    gld_resp = results[10] if not isinstance(results[10], BaseException) else None

    data: dict[str, str | None] = {}
    labels: dict[str, str] = {}

    # ── BTC Price & Technicals ──
    btc_price = None
    if snap_resp and snap_resp.snapshots:
        s = snap_resp.snapshots[0]
        btc_price = to_float(s.get("price"))
        change_ratio = to_float(s.get("change_ratio"))
        if btc_price:
            price_str = f"${btc_price:,.0f}"
            if change_ratio is not None:
                price_str += f" ({change_ratio * 100:+.2f}%)"
            data["BTC Price"] = price_str

    bars = bars_resp.bars if bars_resp else []
    closes = [float(b["close"]) for b in bars if b.get("close")] if bars else []
    ath: float | None = None

    if closes:
        ath = max(closes)
        current = closes[-1]
        if btc_price:
            current = btc_price
            ath = max(ath, btc_price)
        drawdown = (current - ath) / ath * 100 if ath > 0 else 0
        data["ATH Drawdown"] = f"{drawdown:+.1f}% (ATH ${ath:,.0f})"

        rsi_vals = ta.rsi(closes)
        rsi_val = rsi_vals[-1] if rsi_vals else None
        if rsi_val is not None:
            level = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"
            data["RSI(14)"] = f"{rsi_val:.1f} ({level})"

        sma50_vals = ta.sma(closes, 50)
        sma50 = sma50_vals[-1]
        if sma50 is not None and current:
            rel = "above" if current > sma50 else "below"
            data["SMA(50)"] = f"${sma50:,.0f} (price {rel})"

        sma200_vals = ta.sma(closes, 200)
        sma200 = sma200_vals[-1]
        if sma200 is not None and current:
            rel = "above" if current > sma200 else "below"
            data["SMA(200)"] = f"${sma200:,.0f} (price {rel})"

    # ── Correlation Regime ──
    btc_by_date: dict[str, float] = {}
    for b in bars:
        t_str = b.get("time", "")
        close = to_float(b.get("close"))
        if t_str and close:
            btc_by_date[t_str[:10]] = close

    qqq_by_date: dict[str, float] = {}
    if qqq_resp and qqq_resp.days:
        for d in qqq_resp.days:
            qqq_by_date[d.get("date", "")] = float(d["close"])

    gld_by_date: dict[str, float] = {}
    if gld_resp and gld_resp.days:
        for d in gld_resp.days:
            gld_by_date[d.get("date", "")] = float(d["close"])

    if btc_by_date and qqq_by_date and gld_by_date:
        corr_label, corr_detail = btc.classify_correlation(btc_by_date, qqq_by_date, gld_by_date)
        data["Correlation"] = f"{corr_label} — {corr_detail}"

    # ── Macro Signals ──

    # Halving cycle (static calculation, no data needed)
    label, detail = btc.classify_halving_cycle()
    data["Halving Cycle"] = f"{label} — {detail}"
    labels["Halving Cycle"] = label

    # Monetary policy
    ff_obs = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_obs)
    prev_ff_val, _ = regime.parse_fred_value(ff_obs[1:] if len(ff_obs) > 1 else [])
    label, detail = btc.classify_monetary_policy(ff_val, prev_ff_val)
    data["Monetary Policy"] = f"{label} — {detail}"
    labels["Monetary Policy"] = label

    # Liquidity (M2 money supply)
    m2_obs = m2_resp.observations if m2_resp else []
    m2_values: list[tuple[str, float]] = []
    for obs in m2_obs:
        v = obs.get("value", ".")
        if v != ".":
            try:
                m2_values.append((obs.get("date", ""), float(v)))
            except (ValueError, TypeError):
                pass
    label, detail = btc.classify_liquidity(m2_values)
    data["Liquidity"] = f"{label} — {detail}"
    labels["Liquidity"] = label

    # Dollar strength
    dxy_obs = dxy_resp.observations if dxy_resp else []
    dxy_values: list[tuple[str, float]] = []
    for obs in dxy_obs:
        v = obs.get("value", ".")
        if v != ".":
            try:
                dxy_values.append((obs.get("date", ""), float(v)))
            except (ValueError, TypeError):
                pass
    label, detail = btc.classify_dollar(dxy_values)
    data["Dollar"] = f"{label} — {detail}"
    labels["Dollar"] = label

    # Real rates (10Y yield minus CPI YoY)
    dgs10_val, _ = regime.parse_fred_value(dgs10_resp.observations if dgs10_resp else [])
    cpi_obs = cpi_resp.observations if cpi_resp else []
    cpi_yoy = None
    if len(cpi_obs) >= 13:
        try:
            current_cpi = float(cpi_obs[0].get("value", "."))
            year_ago_cpi = float(cpi_obs[12].get("value", "."))
            if year_ago_cpi > 0:
                cpi_yoy = (current_cpi - year_ago_cpi) / year_ago_cpi * 100
        except (ValueError, TypeError):
            pass
    label, detail = btc.classify_real_rates(dgs10_val, cpi_yoy)
    data["Real Rates"] = f"{label} — {detail}"
    labels["Real Rates"] = label

    # Risk appetite
    vix_val, _ = regime.parse_fred_value(vix_resp.observations if vix_resp else [])
    label, detail = btc.classify_risk_appetite(vix_val)
    data["Risk Appetite"] = f"{label} — {detail}"
    labels["Risk Appetite"] = label

    # Sentiment (Crypto Fear & Greed Index — contrarian)
    label, detail = btc.classify_fear_greed(fng_val)
    data["Sentiment"] = f"{label} — {detail}"
    labels["Sentiment"] = label

    # Composite scorecard
    data["Composite"] = btc.macro_scorecard(labels)

    # DCA sizing (drawdown-based)
    if btc_price and ath:
        data["DCA Sizing"] = btc.dca_sizing(btc_price, ath)

    return f"## BTC Entry Signals\n\n{kv_table(data)}"


@mcp.tool()
async def get_conviction_metrics(ctx: Context, symbol: str) -> str:
    """Compute position sizing metrics from the decision framework: PEG ratio,
    drawdown %, operating margin trend, and recommended position size tier.

    Pulls P/E + ROE from Finnhub basic financials, quarterly revenue and operating
    income from SEC filings, and current price / 52W high from Tradier quotes.
    Returns all computed values in one call — replaces manual math across
    get_basic_financials + get_income_statement + get_quote.

    symbol: ticker symbol (e.g. 'ADBE').

    Requires [finnhub] and [tradier] sections in ~/.tradingrc.
    """

    d = await _conviction_data(_finnhub(ctx), _tradier(ctx), symbol)

    data: dict[str, str] = {"Symbol": symbol}

    if d["price"]:
        data["Price"] = f"${d['price']:,.2f}"
    if d["high_52w"]:
        data["52W High"] = f"${d['high_52w']:,.2f}"
    if d["drawdown_pct"] is not None:
        data["Drawdown"] = f"{d['drawdown_pct']:+.1f}%"

    if d["pe"] is not None:
        data["P/E (TTM)"] = f"{d['pe']:.1f}"
    if d["roe"] is not None:
        data["ROE (TTM)"] = f"{d['roe']:.1f}%"
    if d["de"] is not None:
        data["Debt/Equity"] = f"{d['de']:.2f}"

    if d["current_q"] and d["prior_q"]:
        cr = d["current_q"].get("Revenue")
        pr = d["prior_q"].get("Revenue")
        data["Revenue (Current Q)"] = (
            f"${cr / 1e9:.2f}B" if cr and cr >= 1e9 else (f"${cr / 1e6:.0f}M" if cr else "N/A")
        )
        data["Revenue (Prior YoY Q)"] = (
            f"${pr / 1e9:.2f}B" if pr and pr >= 1e9 else (f"${pr / 1e6:.0f}M" if pr else "N/A")
        )
    if d["rev_growth"] is not None:
        data["Revenue Growth (YoY)"] = f"{d['rev_growth']:.1f}%"

    if d["margins"]:
        data["Operating Margin"] = " → ".join(f"{p[:7]} {m:.1f}%" for p, m in d["margins"])
    if d["margin_trend"]:
        data["Margin Trend"] = d["margin_trend"]

    if d["peg"] is not None and d["peg_valid"]:
        data["PEG"] = f"{d['peg']:.2f}"
    elif d["peg_note"]:
        data["PEG"] = d["peg_note"]

    data["Position Size"] = d["size"]

    return kv_table(data)


@mcp.tool()
async def calculate_position_size(
    ctx: Context, symbol: str, total_assets: float, tier: str = "full"
) -> str:
    """Calculate share count for a position based on sizing tier and total portfolio
    assets. Uses the 10% / 5% / 2% concentration limit from the decision framework.

    Call this after get_conviction_metrics has determined the sizing tier and you are
    ready to deploy capital.

    The output share count is NOT rounded to 100-share lots. If CSP is the recommended
    strategy, tell the user to round up to the nearest 100 shares since each CSP
    contract covers 100 shares.

    symbol: ticker symbol (e.g. 'ADBE').
    total_assets: total portfolio value in the target account (e.g. 500000).
    tier: sizing tier from get_conviction_metrics — 'full', 'standard', or 'reduced'.
    """

    fracs = {"full": 0.10, "standard": 0.05, "reduced": 0.02}
    frac = fracs.get(tier.lower())
    if frac is None:
        return f"Invalid tier '{tier}' — use full, standard, or reduced"

    quote_resp = await _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if not price or price <= 0:
        return f"Could not get price for {symbol}"

    dollars = total_assets * frac
    shares = int(dollars / price)

    return kv_table(
        {
            "Symbol": symbol,
            "Price": f"${price:,.2f}",
            "Total Assets": f"${total_assets:,.0f}",
            "Tier": f"{tier.capitalize()} ({frac:.0%})",
            "Allocation": f"${dollars:,.0f}",
            "Shares": str(shares),
        }
    )


@mcp.tool()
async def calculate_hedge(
    ctx: Context,
    hedge_index: str = "SPY",
    expiration: str | None = None,
    strike: float | None = None,
    hedge_ratio: float = 1.0,
    delta_adjusted: bool = False,
) -> str:
    """Calculate put contracts needed to hedge the portfolio.

    Computes portfolio beta vs the hedge index from trailing 90-day returns,
    then sizes the hedge and prices it from the current option chain.

    hedge_index: 'SPY' or 'QQQ' (default 'SPY').
    expiration: option expiration (YYYY-MM-DD). Defaults to nearest monthly >=30 DTE.
    strike: put strike. Defaults to ~5% OTM.
    hedge_ratio: fraction to hedge, 0.0-1.0 (default 1.0 = 100%).
    delta_adjusted: if True, divide by put delta for continuous 1:1 hedging.
      Default False = tail-risk mode (sized for full payout when puts go ITM).

    Requires [webull] and [tradier] sections in ~/.tradingrc.
    """

    if hedge_index.upper() not in ("SPY", "QQQ"):
        return "hedge_index must be 'SPY' or 'QQQ'"
    hedge_index = hedge_index.upper()

    webull = _webull(ctx)
    tradier = _tradier(ctx)

    # Phase 1: Fetch positions + index quote + expirations + NLV in parallel
    positions_task = _fetch_all_positions(webull)
    quote_task = tradier.get(t.QUOTES, t.GetQuotesRequest(hedge_index, greeks=False))
    exp_task = tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(hedge_index))
    bal_task = _fetch_total_nlv(webull)

    (positions, _pos_errors), quote_resp, exp_resp, total_nlv = await asyncio.gather(
        positions_task, quote_task, exp_task, bal_task
    )

    index_price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if not index_price:
        return f"Could not get quote for {hedge_index}"

    # Filter to equity-only positions with value
    equities = [
        p
        for p in positions
        if not p.get("is_option") and not p.get("is_cash") and p.get("value", 0) > 0
    ]
    if not equities:
        return "No equity positions found"

    total_equity = sum(p["value"] for p in equities)
    symbols = list({p["symbol"] for p in equities})

    # Resolve expiration
    if not expiration:
        target = date.today() + timedelta(days=30)
        for d in exp_resp.dates:
            if d >= target.isoformat():
                expiration = d
                break
        if not expiration:
            return "No suitable expiration found >=30 DTE"

    # Phase 2: Fetch historical data for all symbols + index + strikes
    lookback_start = (date.today() - timedelta(days=120)).isoformat()
    history_tasks = {
        sym: tradier.get(t.HISTORY, t.GetHistoryRequest(sym, "daily", start=lookback_start))
        for sym in symbols + [hedge_index]
    }
    strikes_task = tradier.get(t.STRIKES, t.GetStrikesRequest(hedge_index, expiration))

    results = await asyncio.gather(*history_tasks.values(), strikes_task, return_exceptions=True)

    history_keys = list(history_tasks.keys())
    history_data: dict[str, list[dict]] = {}
    for i, key in enumerate(history_keys):
        r = results[i]
        if not isinstance(r, Exception) and hasattr(r, "days"):
            history_data[key] = r.days

    strikes_resp = results[-1]
    available_strikes = strikes_resp.strikes if not isinstance(strikes_resp, Exception) else []

    # Resolve strike (~5% OTM if not specified)
    if not strike:
        target_strike = index_price * 0.95
        if available_strikes:
            strike = min(available_strikes, key=lambda s: abs(float(s) - target_strike))
            strike = float(strike)
        else:
            strike = round(target_strike)

    # Compute per-symbol betas (date-aligned)
    benchmark_bars = history_data.get(hedge_index, [])
    weighted_beta = 0.0
    beta_count = 0
    fallback_count = 0

    for p in equities:
        sym = p["symbol"]
        weight = p["value"] / total_equity
        sym_bars = history_data.get(sym, [])
        b = ta.beta(sym_bars, benchmark_bars)
        if b is not None:
            weighted_beta += weight * b
            beta_count += 1
        else:
            weighted_beta += weight * 1.0
            fallback_count += 1

    # Adjust for cash: portfolio beta = (equity / total) * equity_beta
    portfolio_beta = (total_equity / total_nlv) * weighted_beta if total_nlv > 0 else weighted_beta

    # Phase 3: Fetch put quote (needed before contract calc in delta-adjusted mode)
    occ = opts.build_occ(hedge_index, expiration, "put", strike)
    try:
        put_resp = await tradier.get(t.QUOTES, t.GetQuotesRequest(occ, greeks=True))
        put_q = put_resp.quotes[0] if put_resp.quotes else {}
    except Exception:
        put_q = {}

    put_ask = put_q.get("ask", 0) or 0
    put_bid = put_q.get("bid", 0) or 0
    put_delta = put_q.get("greeks", {}).get("delta", "")
    put_iv = put_q.get("greeks", {}).get("mid_iv", "")

    # Calculate contracts
    notional = (total_nlv * portfolio_beta * hedge_ratio) / (index_price * CONTRACT_MULTIPLIER)
    if delta_adjusted and put_delta:
        contracts = round(notional / abs(float(put_delta)))
    else:
        contracts = round(notional)
    if contracts < 1:
        contracts = 1

    total_cost = put_ask * CONTRACT_MULTIPLIER * contracts
    cost_pct = (total_cost / total_nlv * 100) if total_nlv > 0 else 0
    drawdown_trigger = (1 - strike / index_price) * 100

    sizing_mode = "delta-adjusted (continuous)" if delta_adjusted else "notional (tail-risk)"

    data = {
        "Portfolio Value": f"${total_nlv:,.0f}",
        "Equity Value": f"${total_equity:,.0f}",
        "Equity Symbols": f"{len(symbols)} ({beta_count} with beta, {fallback_count} fallback)",
        "Portfolio Beta": f"{portfolio_beta:.2f}",
        "Hedge Ratio": f"{hedge_ratio:.0%}",
        "Sizing Mode": sizing_mode,
        "---": "---",
        "Hedge Index": f"{hedge_index} @ ${index_price:,.2f}",
        "Put Strike": f"${strike:,.2f} ({drawdown_trigger:.1f}% OTM)",
        "Expiration": expiration,
        "Contracts": str(contracts),
        "Put Bid / Ask": f"${put_bid:.2f} / ${put_ask:.2f}",
        "Total Cost": f"${total_cost:,.0f} ({cost_pct:.2f}% of portfolio)",
        "Put Delta": f"{put_delta}" if put_delta else "N/A",
        "Put IV": f"{float(put_iv) * 100:.1f}%" if put_iv else "N/A",
    }

    return kv_table(data)


@mcp.tool()
async def get_entry_signals(ctx: Context, symbol: str) -> str:
    """Aggregate conviction, IV, and momentum signals for a stock and detect
    circuit breakers from the decision framework (Steps 1-2).

    Combines get_conviction_metrics + get_iv_metrics + get_technical_indicators
    into one call. Automatically flags triggered circuit breakers:
    - Value Trap: RSI <30 but margins compressing
    - Justified Rally: RSI >70 but margins expanding (mirror of Value Trap)
    - Price Dislocation: downtrend but revenue accelerating + ROE >25%
    - Deteriorating Rally: uptrend but revenue declining (mirror of Price Dislocation)
    - FOMO Trap: near ATH + RSI >70 + PEG >3.0
    - Capitulation Bargain: near 52W low + RSI <30 + PEG <1 + margins ok (mirror of FOMO Trap)
    - Front-Run Catalyst: stock rallied >8% in prior 2 weeks (intent-aware)
    - Pre-Priced Selloff: stock dropped >8% in prior 2 weeks (intent-aware)

    symbol: ticker symbol (e.g. 'ULTA').

    Requires [finnhub], [tradier], and [tastytrade] sections in ~/.tradingrc.
    """

    finnhub = _finnhub(ctx)
    tradier = _tradier(ctx)
    tastytrade = _tastytrade(ctx)

    conv_task = _conviction_data(finnhub, tradier, symbol)
    iv_task = tastytrade.get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbol))
    hist_task = tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily"))

    conv_r, iv_r, hist_r = await asyncio.gather(
        conv_task, iv_task, hist_task, return_exceptions=True
    )

    d = conv_r if not isinstance(conv_r, BaseException) else {}
    iv_resp = None if isinstance(iv_r, BaseException) else iv_r
    hist_resp = None if isinstance(hist_r, BaseException) else hist_r

    price = d.get("price")
    drawdown_pct = d.get("drawdown_pct")
    pe = d.get("pe")
    roe = d.get("roe")
    de = d.get("de")
    rev_growth = d.get("rev_growth")
    margins = d.get("margins", [])
    margin_trend = d.get("margin_trend")
    peg = d.get("peg")
    peg_valid = d.get("peg_valid", False)
    size = d.get("size", "Unknown")

    # ── IV metrics ──
    iv_item = iv_resp.items[0] if iv_resp and iv_resp.items else {}
    iv_rank_raw = to_float(iv_item.get("tw-implied-volatility-index-rank"))
    iv_rank = iv_rank_raw * 100 if iv_rank_raw is not None else None
    iv_30d = to_float(iv_item.get("implied-volatility-30-day"))
    hv_30d = to_float(iv_item.get("historical-volatility-30-day"))
    iv_hv = to_float(iv_item.get("iv-hv-30-day-difference"))
    earnings = iv_item.get("earnings", {})
    earnings_date = earnings.get("expected-report-date") if isinstance(earnings, dict) else None
    liq = iv_item.get("liquidity-rating")

    # ── Technical indicators ──
    bars = hist_resp.days if hist_resp else []
    closes = [float(b["close"]) for b in bars] if bars else []

    rsi_val = None
    sma50_val = None
    sma200_val = None
    above_sma50 = None
    above_sma200 = None
    rally_2w_pct = None

    if closes:
        rsi_vals = ta.rsi(closes)
        rsi_val = rsi_vals[-1] if rsi_vals else None

        sma50_vals = ta.sma(closes, 50)
        sma50_val = sma50_vals[-1]
        if sma50_val is not None and price:
            above_sma50 = price > sma50_val

        sma200_vals = ta.sma(closes, 200)
        sma200_val = sma200_vals[-1]
        if sma200_val is not None and price:
            above_sma200 = price > sma200_val

        if len(closes) >= 10:
            price_2w_ago = closes[-10]
            if price_2w_ago > 0:
                rally_2w_pct = (closes[-1] - price_2w_ago) / price_2w_ago * 100

    # ── Circuit breakers ──
    breakers: list[str] = []

    if rsi_val is not None and rsi_val < 30 and margin_trend == "Compressing":
        breakers.append("Value Trap — RSI <30 but margins compressing. Hard stop.")

    if rsi_val is not None and rsi_val > 70 and margin_trend == "Expanding":
        breakers.append(
            "Justified Rally — RSI >70 but margins expanding. "
            "Overbought is justified by improving fundamentals. Don't short this."
        )

    in_downtrend = above_sma50 is False and above_sma200 is False
    if in_downtrend and rev_growth is not None and rev_growth > 0 and roe is not None and roe > 25:
        breakers.append(
            "Price Dislocation — downtrend but revenue accelerating + ROE >25%. "
            "Proceed with Hybrid (CSP-heavy) entry."
        )

    in_uptrend = above_sma50 is True and above_sma200 is True
    if in_uptrend and rev_growth is not None and rev_growth < 0:
        breakers.append(
            "Deteriorating Rally — uptrend but revenue declining. "
            "Technicals mask weakening fundamentals. Bearish setup."
        )

    near_ath = drawdown_pct is not None and drawdown_pct > -5
    if near_ath and rsi_val is not None and rsi_val > 70 and peg is not None and peg > 3.0:
        breakers.append("FOMO Trap — near ATH + RSI >70 + PEG >3. Reduced tier only.")

    near_52w_low = drawdown_pct is not None and drawdown_pct < -40
    if (
        near_52w_low
        and rsi_val is not None
        and rsi_val < 30
        and peg is not None
        and peg > 0
        and peg < 1.0
        and margin_trend != "Compressing"
    ):
        breakers.append(
            "Capitulation Bargain — near 52W low + RSI <30 + PEG <1 + margins not compressing. "
            "Genuine bargain, not a value trap. High-conviction accumulate."
        )

    if rally_2w_pct is not None and rally_2w_pct > 8 and earnings_date:
        breakers.append(
            f"Front-Run Catalyst — rallied {rally_2w_pct:.1f}% in 2 weeks into "
            f"{earnings_date} earnings. Bullish: wait for post-catalyst reaction. "
            f"Bearish: rally provides higher entry for puts/bear spreads."
        )

    if rally_2w_pct is not None and rally_2w_pct < -8 and earnings_date:
        breakers.append(
            f"Pre-Priced Selloff — dropped {rally_2w_pct:.1f}% in 2 weeks into "
            f"{earnings_date} earnings. Bearish: wait for post-catalyst reaction "
            f"(downside may be priced in). "
            f"Bullish: selloff provides cheaper entry for shares/CSPs."
        )

    # ── Build output ──
    data: dict[str, str] = {"Symbol": symbol}

    if price:
        data["Price"] = f"${price:,.2f}"
    if drawdown_pct is not None:
        data["Drawdown"] = f"{drawdown_pct:+.1f}%"

    if roe is not None:
        roe_str = f"{roe:.1f}%"
        if de is not None and de > 3:
            roe_str += f" (D/E {de:.1f} — leverage-inflated)"
        data["ROE"] = roe_str
    if pe is not None:
        data["P/E"] = f"{pe:.1f}"
    if rev_growth is not None:
        data["Revenue Growth (YoY)"] = f"{rev_growth:.1f}%"
    if margins:
        data["Op Margin"] = " → ".join(f"{p[:7]} {m:.1f}%" for p, m in margins)
    if margin_trend:
        data["Margin Trend"] = margin_trend
    if peg is not None and peg_valid:
        data["PEG"] = f"{peg:.2f}"
    data["Size Tier"] = size

    if iv_rank is not None:
        data["IV Rank"] = f"{iv_rank:.0f}%"
    if iv_hv is not None:
        data["IV-HV"] = f"{iv_hv:+.1f}%"
    if iv_30d is not None:
        data["IV 30d"] = f"{iv_30d:.1f}%"
    if hv_30d is not None:
        data["HV 30d"] = f"{hv_30d:.1f}%"
    if earnings_date:
        data["Earnings"] = earnings_date
    if liq is not None:
        data["Liquidity"] = str(liq)

    if rsi_val is not None:
        level = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"
        data["RSI(14)"] = f"{rsi_val:.1f} ({level})"
    if sma50_val is not None:
        rel = "above" if above_sma50 else "below"
        data["SMA(50)"] = f"{sma50_val:.2f} (price {rel})"
    if sma200_val is not None:
        rel = "above" if above_sma200 else "below"
        data["SMA(200)"] = f"{sma200_val:.2f} (price {rel})"
    if rally_2w_pct is not None:
        data["2W Rally"] = f"{rally_2w_pct:+.1f}%"

    if breakers:
        data["Circuit Breakers"] = " | ".join(breakers)
    else:
        data["Circuit Breakers"] = "None"

    return kv_table(data)


# ═══════════════════════════════════════════════════════════════
# ALPHA VANTAGE — News Sentiment, Market Movers
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_news_sentiment(
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
        await _alphavantage(ctx).get(
            av.SENTIMENT, av.SentimentRequest(tickers, topics, limit=limit)
        )
    ).to_output()


@mcp.tool()
async def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks.

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return (await _alphavantage(ctx).get(av.MOVERS, av.MoversRequest())).to_output()


# ═══════════════════════════════════════════════════════════════
# TASTYTRADE — IV Rank, IV Percentile, Market Metrics
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def get_iv_metrics(ctx: Context, symbols: str) -> str:
    """Get implied volatility metrics: IV rank, IV percentile, IV index, 30-day IV,
    5-day IV change, next earnings date, and liquidity rating.

    IV Rank shows where current IV sits relative to its 52-week high/low (0-100).
    IV Percentile shows what % of days in the past year had lower IV (0-100%).
    Use these to time premium-selling strategies: high IV Rank = rich premiums.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,QCOM,ADBE').

    Requires [tastytrade] section in ~/.tradingrc.
    """
    resp = await _tastytrade(ctx).get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbols))
    return resp.to_output()


@mcp.tool()
async def get_public_watchlists(ctx: Context) -> str:
    """List all TastyTrade curated watchlists with symbol counts.

    Includes sector lists, high IV rank names, liquid options, dividend aristocrats,
    earnings calendars, and more. Use get_public_watchlist to get the symbols in
    a specific list.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return (await _tastytrade(ctx).get(tt.PUBLIC_WATCHLISTS, tt.EmptyRequest())).to_output()


@mcp.tool()
async def get_public_watchlist(ctx: Context, name: str) -> str:
    """Get all symbols in a TastyTrade curated watchlist.

    name: watchlist name (e.g. 'tasty IVR', 'High Options Volume',
      '52 Week Near Low', 'A.I. Stocks', 'Dividend Aristocrats').
      Use get_public_watchlists to see available names.

    Requires [tastytrade] section in ~/.tradingrc.
    """
    return (await _tastytrade(ctx).get(tt.PUBLIC_WATCHLIST, tt.WatchlistRequest(name))).to_output()


@mcp.tool()
async def backtest_strategy(
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
    client = _tastytrade(ctx)

    # Create the backtest
    result = await client.post(
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
        result = await client.get(tt.BACKTEST_GET, tt.BacktestIdRequest(bt_id))
        if result.data.get("status") == "completed":
            return result.to_output()
        await asyncio.sleep(3)

    return f"Backtest {bt_id} still running. Check back later."


# ═══════════════════════════════════════════════════════════════
# YAHOO FINANCE
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def screen_stocks(
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
    ascending = sort_dir == "ASC"
    result = await yfc.custom_screen(criteria, sort_field, ascending, limit)
    return ScreenerResponse.from_response(result).to_output()


@mcp.tool()
async def get_predefined_screen(ctx: Context, screen_id: str, count: int = 25) -> str:
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
    result = await yfc.predefined_screen(screen_id, count)
    return ScreenerResponse.from_response(result).to_output()


@mcp.tool()
async def get_institutional_ownership(ctx: Context, symbol: str) -> str:
    """Get top institutional holders of a stock: holder name, shares held, percentage
    held, position value, and recent change.

    Shows who the biggest institutional investors are (Vanguard, BlackRock, etc.)
    and whether they're accumulating or reducing positions.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """

    holders = await yfc.institutional_holders(symbol)
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
async def get_short_interest(ctx: Context, symbol: str) -> str:
    """Get short interest data for a stock: shares short, short ratio (days to cover),
    short % of float, and month-over-month change.

    Useful for gauging squeeze risk on CSP positions and identifying heavily shorted names.

    symbol: ticker symbol (e.g. 'AAPL').

    Uses Yahoo Finance via yfinance (no API key required).
    """

    data = await yfc.short_interest(symbol)
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
async def get_youtube_transcript(ctx: Context, url: str) -> str:
    """Get the transcript of a YouTube video.

    Extracts auto-generated or manual captions and returns the full text.
    Useful for analyzing financial commentary, earnings calls, or market analysis videos.

    url: YouTube video URL or video ID (e.g. 'https://www.youtube.com/watch?v=abc123'
      or just 'abc123').
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = url
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        video_id = m.group(1)

    api = YouTubeTranscriptApi()
    transcript = await asyncio.to_thread(api.fetch, video_id)
    full_text = " ".join(s.text for s in transcript.snippets)
    kind = "auto-generated" if transcript.is_generated else "manual"
    return f"**Video ID:** {video_id}\n**Language:** {transcript.language} ({kind})\n\n{full_text}"


# ═══════════════════════════════════════════════════════════════


def main():
    mcp.run()


if __name__ == "__main__":
    main()
