"""Response processing for API endpoints.

Every API response passes through `process()` which applies two stages:

1. **Field filtering** — drop unneeded top-level keys to reduce token usage.
   Configure via FIELD_FILTERS (set of keys to keep, or None for passthrough).

2. **Transformation** — convert the response to a markdown table string so the
   model gets clean, structured, unambiguous output. This drastically reduces
   hallucinations compared to raw JSON. Configure via TRANSFORMERS.

Both stages are optional per endpoint. If neither is configured, the raw
response passes through unchanged.

Keys use the API path for Webull endpoints (e.g. "/account/profile") and a
namespaced logical key for external providers (e.g. "tradier:chain").
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# ── Markdown table helpers ───────────────────────────────────


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a markdown table from headers and rows."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        # Pad row to match header count
        while len(cells) < len(headers):
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _kv_table(data: dict, key_header: str = "Field", val_header: str = "Value") -> str:
    """Build a two-column key/value markdown table from a dict."""
    headers = [key_header, val_header]
    rows = [[str(k), str(v)] for k, v in data.items() if v is not None]
    return _md_table(headers, rows)


def _list_table(items: list[dict], columns: list[str] | None = None) -> str:
    """Build a markdown table from a list of dicts.

    If columns is provided, only those keys are included (in that order).
    Otherwise all keys from the first item are used.
    """
    if not items:
        return "(no data)"
    if columns is None:
        seen: dict[str, None] = {}
        for item in items:
            seen.update(dict.fromkeys(item.keys()))
        columns = list(seen)
    rows = [[str(item.get(c, "")) for c in columns] for item in items]
    return _md_table(columns, rows)


def _fmt_number(val: Any, decimals: int = 2) -> str:
    """Format a number with commas and fixed decimals, or return '' if None."""
    if val is None:
        return ""
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _fmt_large(val: Any) -> str:
    """Format large numbers as B/M/K for readability."""
    if val is None:
        return ""
    try:
        n = float(val)
    except (ValueError, TypeError):
        return str(val)
    if abs(n) >= 1e12:
        return f"{n / 1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"{n / 1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"{n / 1e3:.1f}K"
    return f"{n:.2f}"


def _unix_to_date(ts: Any) -> str:
    """Convert unix timestamp to YYYY-MM-DD HH:MM."""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)


# ── Per-endpoint top-level field keep-sets ────────────────────
# Set to None (or omit) to pass through all fields.

FIELD_FILTERS: dict[str, set[str] | None] = {
    # ── Webull ──
    # Account
    "/account/profile": None,
    "/account/balance": None,
    "/account/positions": None,
    # Orders (read)
    "/trade/orders/list-open": None,
    "/trade/orders/list-today": None,
    "/trade/order/detail": None,
    # Order management
    "/openapi/account/orders/preview": None,
    "/trade/order/place": None,
    "/trade/order/replace": None,
    "/trade/order/cancel": None,
    "/openapi/account/orders/option/preview": None,
    "/openapi/account/orders/option/place": None,
    "/openapi/account/orders/option/replace": None,
    "/openapi/account/orders/option/cancel": None,
    # Trade info
    "/trade/calendar": None,
    "/trade/instrument": None,
    "/app/subscriptions/list": None,
    # Market data
    "/instrument/list": None,
    "/market-data/bars": None,
}


# ── Transformers ─────────────────────────────────────────────


# ── Webull ──


def _transform_account_profile(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_account_balance(data: dict) -> str:
    if not data:
        return "(no data)"
    # Flatten the nested account_currency_assets into top-level
    assets = data.get("account_currency_assets", [])
    usd = assets[0] if assets else {}
    selected = {
        "Net Liquidation": _fmt_number(usd.get("net_liquidation_value")),
        "Market Value": _fmt_number(data.get("total_market_value")),
        "Cash Balance": _fmt_number(data.get("total_cash_balance")),
        "Cash Power": _fmt_number(usd.get("cash_power")),
        "Margin Power": _fmt_number(usd.get("margin_power")),
        "Margin Utilization": data.get("margin_utilization_rate"),
        "Available Withdrawal": _fmt_number(usd.get("available_withdrawal")),
        "Pending Incoming": _fmt_number(usd.get("pending_incoming")),
    }
    return _kv_table({k: v for k, v in selected.items() if v and v != "0.00"})


def _transform_account_positions(data: list[dict]) -> str:
    if not data:
        return "(no positions)"
    rows = [
        {
            "Symbol": p.get("symbol", ""),
            "Instrument ID": p.get("instrument_id", ""),
            "Qty": p.get("qty", ""),
            "Cost": _fmt_number(p.get("unit_cost")),
            "Last": _fmt_number(p.get("last_price")),
            "Mkt Value": _fmt_number(p.get("market_value")),
            "P&L": _fmt_number(p.get("unrealized_profit_loss")),
            "P&L %": _fmt_number(float(p.get("unrealized_profit_loss_rate", 0)) * 100),
        }
        for p in data
    ]
    return _list_table(rows)


def _transform_instruments(data: list[dict]) -> str:
    if not data:
        return "(no instruments)"
    rows = [
        {
            "Symbol": i.get("symbol", ""),
            "Name": i.get("name", ""),
            "Instrument ID": i.get("instrument_id", ""),
            "Exchange": i.get("exchange_code", ""),
            "Currency": i.get("currency", ""),
        }
        for i in data
    ]
    return _list_table(rows)


def _transform_bars(data: list[dict]) -> str:
    if not data:
        return "(no bars)"
    rows = [
        {
            "Date": (b.get("time") or "")[:10],
            "Open": _fmt_number(b.get("open")),
            "High": _fmt_number(b.get("high")),
            "Low": _fmt_number(b.get("low")),
            "Close": _fmt_number(b.get("close")),
            "Volume": _fmt_large(b.get("volume")),
        }
        for b in data
    ]
    return _list_table(rows)


def _transform_trade_instrument(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_trade_calendar(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": d.get("trade_day", ""),
            "Type": d.get("trade_date_type", ""),
        }
        for d in data
    ]
    return _list_table(rows)


def _transform_subscriptions(data: list[dict]) -> str:
    if not data:
        return "(no subscriptions)"
    rows = [
        {
            "Account Number": s.get("account_number", ""),
            "Account ID": s.get("account_id", ""),
        }
        for s in data
    ]
    return _list_table(rows)


def _transform_open_orders(data: dict) -> str:
    orders = data.get("orders", []) if isinstance(data, dict) else []
    if not orders:
        return "(no open orders)"
    return _transform_order_list(orders)


def _transform_today_orders(data: dict) -> str:
    orders = data.get("orders", []) if isinstance(data, dict) else []
    if not orders:
        return "(no orders today)"
    return _transform_order_list(orders)


def _transform_order_list(orders: list[dict]) -> str:
    rows = []
    for o in orders:
        items = o.get("items", [])
        for item in items:
            rows.append(
                {
                    "Symbol": item.get("symbol", ""),
                    "Side": item.get("side", ""),
                    "Type": item.get("order_type", ""),
                    "Qty": item.get("qty", ""),
                    "Filled": item.get("filled_qty", ""),
                    "Price": _fmt_number(item.get("limit_price")),
                    "Status": item.get("order_status", ""),
                    "Time": (item.get("place_time") or "")[:19],
                }
            )
    return _list_table(rows) if rows else "(no orders)"


def _transform_order_detail(data: dict) -> str:
    if not data:
        return "(no data)"
    items = data.get("items", [])
    header = {
        "Order ID": data.get("client_order_id"),
        "TIF": data.get("tif"),
        "Extended Hours": str(data.get("extended_hours_trading", "")),
    }
    result = _kv_table({k: v for k, v in header.items() if v})
    if items:
        result += "\n\n"
        rows = [
            {
                "Symbol": item.get("symbol", ""),
                "Side": item.get("side", ""),
                "Type": item.get("order_type", ""),
                "Qty": item.get("qty", ""),
                "Filled": item.get("filled_qty", ""),
                "Price": _fmt_number(item.get("limit_price")),
                "Status": item.get("order_status", ""),
                "Time": (item.get("place_time") or "")[:19],
                "Commission": _fmt_number(item.get("commission")),
            }
            for item in items
        ]
        result += _list_table(rows)
    return result


def _transform_order_result(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


# ── Tradier ──


def _transform_option_expirations(data: list[str]) -> str:
    if not data:
        return "(no expirations)"
    rows = [[d] for d in data]
    return _md_table(["Expiration"], rows)


def _transform_option_strikes(data: list) -> str:
    if not data:
        return "(no strikes)"
    rows = [[_fmt_number(s)] for s in data]
    return _md_table(["Strike"], rows)


def _transform_option_lookup(data: list) -> str:
    if not data:
        return "(no options)"
    rows = [[str(o)] for o in data]
    return _md_table(["Option Symbol"], rows)


def _transform_tradier_history(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": d.get("date", ""),
            "Open": _fmt_number(d.get("open")),
            "High": _fmt_number(d.get("high")),
            "Low": _fmt_number(d.get("low")),
            "Close": _fmt_number(d.get("close")),
            "Volume": _fmt_large(d.get("volume")),
        }
        for d in data
    ]
    return _list_table(rows)


def _transform_tradier_search(data: list[dict]) -> str:
    if not data:
        return "(no results)"
    rows = [
        {
            "Symbol": s.get("symbol", ""),
            "Exchange": s.get("exchange", ""),
            "Type": s.get("type", ""),
            "Description": s.get("description", ""),
        }
        for s in data
    ]
    return _list_table(rows)


def _transform_tradier_quotes(data: list[dict]) -> str:
    if not data:
        return "(no quotes)"
    rows = []
    for q in data:
        is_option = q.get("option_type") is not None
        row: dict[str, str] = {"Symbol": q.get("symbol", "")}
        if is_option:
            row["Type"] = q.get("option_type", "")
            row["Strike"] = _fmt_number(q.get("strike"))
            row["Exp"] = q.get("expiration_date", "")
        row |= {
            "Last": _fmt_number(q.get("last")),
            "Bid": _fmt_number(q.get("bid")),
            "Bid Sz": _fmt_large(q.get("bidsize")),
            "Ask": _fmt_number(q.get("ask")),
            "Ask Sz": _fmt_large(q.get("asksize")),
            "Volume": _fmt_large(q.get("volume")),
            "Change": _fmt_number(q.get("change")),
            "Change %": _fmt_number(q.get("change_percentage")),
        }
        if is_option:
            row["OI"] = _fmt_large(q.get("open_interest"))
        else:
            row |= {
                "Prev Close": _fmt_number(q.get("prevclose")),
                "Open": _fmt_number(q.get("open")),
                "High": _fmt_number(q.get("high")),
                "Low": _fmt_number(q.get("low")),
                "Avg Vol": _fmt_large(q.get("average_volume")),
                "52W High": _fmt_number(q.get("week_52_high")),
                "52W Low": _fmt_number(q.get("week_52_low")),
            }
        greeks = q.get("greeks")
        if greeks:
            row |= {
                "IV": _fmt_number(greeks.get("mid_iv"), 4),
                "Delta": _fmt_number(greeks.get("delta"), 4),
                "Gamma": _fmt_number(greeks.get("gamma"), 4),
                "Theta": _fmt_number(greeks.get("theta"), 4),
                "Vega": _fmt_number(greeks.get("vega"), 4),
                "Rho": _fmt_number(greeks.get("rho"), 4),
            }
        rows.append(row)
    has_stocks = any(q.get("option_type") is None for q in data)
    has_options = any(q.get("option_type") is not None for q in data)
    has_greeks = any("IV" in r for r in rows)
    cols = ["Symbol"]
    if has_options:
        cols += ["Type", "Strike", "Exp"]
    cols += ["Last", "Bid", "Bid Sz", "Ask", "Ask Sz", "Volume", "Change", "Change %"]
    if has_options:
        cols += ["OI"]
    if has_stocks:
        cols += ["Prev Close", "Open", "High", "Low", "Avg Vol", "52W High", "52W Low"]
    if has_greeks:
        cols += ["IV", "Delta", "Gamma", "Theta", "Vega", "Rho"]
    return _list_table(rows, cols)


def _transform_tradier_timesales(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Time": t.get("time", "")[:19],
            "Price": _fmt_number(t.get("price")),
            "Open": _fmt_number(t.get("open")),
            "High": _fmt_number(t.get("high")),
            "Low": _fmt_number(t.get("low")),
            "Close": _fmt_number(t.get("close")),
            "Volume": _fmt_large(t.get("volume")),
        }
        for t in data
    ]
    return _list_table(rows)


def _transform_tradier_clock(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "State": data.get("state"),
            "Description": data.get("description"),
            "Date": data.get("date"),
            "Timestamp": data.get("timestamp"),
            "Next State": data.get("next_state"),
            "Next Change": data.get("next_change"),
        }
    )


def _transform_tradier_profile(data: list[dict]) -> str:
    if not data:
        return "(no accounts)"
    rows = [
        {
            "Account": a.get("account_number", ""),
            "Type": a.get("type", ""),
            "Classification": a.get("classification", ""),
            "Option Level": str(a.get("option_level", "")),
            "Day Trader": str(a.get("day_trader", "")),
            "Status": a.get("status", ""),
        }
        for a in data
    ]
    return _list_table(rows)


def _transform_tradier_balances(data: dict) -> str:
    if not data:
        return "(no data)"
    selected = {
        "Account": data.get("account_number"),
        "Account Type": data.get("account_type"),
        "Total Equity": _fmt_number(data.get("total_equity")),
        "Total Cash": _fmt_number(data.get("total_cash")),
        "Market Value": _fmt_number(data.get("market_value")),
        "Option Value": _fmt_number(data.get("option_long_value")),
        "Stock Buying Power": _fmt_number(data.get("stock_buying_power")),
        "Option Buying Power": _fmt_number(data.get("option_buying_power")),
        "Pending Cash": _fmt_number(data.get("pending_cash")),
        "Uncleared Funds": _fmt_number(data.get("uncleared_funds")),
    }
    return _kv_table({k: v for k, v in selected.items() if v})


def _transform_tradier_positions(data: list[dict]) -> str:
    if not data:
        return "(no positions)"
    rows = [
        {
            "Symbol": p.get("symbol", ""),
            "Qty": _fmt_number(p.get("quantity"), 0),
            "Cost Basis": _fmt_number(p.get("cost_basis")),
            "Date Acquired": p.get("date_acquired", ""),
        }
        for p in data
    ]
    return _list_table(rows)


def _transform_tradier_orders(data: list[dict]) -> str:
    if not data:
        return "(no orders)"
    rows = [
        {
            "ID": str(o.get("id", "")),
            "Class": o.get("class", ""),
            "Symbol": o.get("symbol", ""),
            "Side": o.get("side", ""),
            "Qty": _fmt_number(o.get("quantity"), 0),
            "Type": o.get("type", ""),
            "Price": _fmt_number(o.get("price")),
            "Stop": _fmt_number(o.get("stop_price")),
            "Status": o.get("status", ""),
            "Duration": o.get("duration", ""),
            "Created": (o.get("create_date") or "")[:10],
        }
        for o in data
    ]
    return _list_table(rows)


def _transform_tradier_order_detail(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_tradier_gainloss(data: list[dict]) -> str:
    if not data:
        return "(no closed positions)"
    rows = [
        {
            "Symbol": g.get("symbol", ""),
            "Qty": _fmt_number(g.get("quantity"), 0),
            "Open Date": (g.get("open_date") or "")[:10],
            "Close Date": (g.get("close_date") or "")[:10],
            "Term": g.get("term", ""),
            "Cost": _fmt_number(g.get("cost")),
            "Proceeds": _fmt_number(g.get("proceeds")),
            "Gain/Loss": _fmt_number(g.get("gain_loss")),
            "G/L %": _fmt_number(g.get("gain_loss_percent")),
        }
        for g in data
    ]
    return _list_table(rows)


def _transform_tradier_account_history(data: list[dict]) -> str:
    if not data:
        return "(no activity)"
    rows = [
        {
            "Date": (e.get("date") or "")[:10],
            "Type": e.get("type", ""),
            "Amount": _fmt_number(e.get("amount")),
            "Description": e.get("description", ""),
        }
        for e in data
    ]
    return _list_table(rows)


def _transform_tradier_place_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_tradier_modify_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_tradier_cancel_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(data)


def _transform_option_chain(data: list[dict]) -> str:
    if not data:
        return "(no options)"
    rows = []
    for o in data:
        greeks = o.get("greeks", {}) or {}
        rows.append(
            {
                "Symbol": o.get("symbol", ""),
                "Type": o.get("option_type", ""),
                "Strike": _fmt_number(o.get("strike")),
                "Bid": _fmt_number(o.get("bid")),
                "Bid Sz": _fmt_large(o.get("bidsize")),
                "Ask": _fmt_number(o.get("ask")),
                "Ask Sz": _fmt_large(o.get("asksize")),
                "Last": _fmt_number(o.get("last")),
                "Change": _fmt_number(o.get("change")),
                "Change %": _fmt_number(o.get("change_percentage")),
                "Vol": _fmt_large(o.get("volume")),
                "OI": _fmt_large(o.get("open_interest")),
                "IV": _fmt_number(greeks.get("mid_iv"), 4),
                "Delta": _fmt_number(greeks.get("delta"), 4),
                "Gamma": _fmt_number(greeks.get("gamma"), 4),
                "Theta": _fmt_number(greeks.get("theta"), 4),
                "Vega": _fmt_number(greeks.get("vega"), 4),
                "Rho": _fmt_number(greeks.get("rho"), 4),
            }
        )
    return _list_table(rows)


# ── Finnhub ──


def _transform_company_news(data: list[dict]) -> str:
    if not data:
        return "(no news)"
    rows = [
        {
            "Date": _unix_to_date(a.get("datetime")),
            "Headline": a.get("headline", ""),
            "Source": a.get("source", ""),
        }
        for a in data
    ]
    return _list_table(rows)


def _transform_market_news(data: list[dict]) -> str:
    return _transform_company_news(data)


def _transform_economic_calendar(data: list[dict]) -> str:
    if not data:
        return "(no events)"
    rows = [
        {
            "Date": e.get("time", ""),
            "Event": e.get("event", ""),
            "Country": e.get("country", ""),
            "Actual": str(e.get("actual", "")),
            "Estimate": str(e.get("estimate", "")),
            "Previous": str(e.get("prev", "")),
            "Impact": e.get("impact", ""),
        }
        for e in data
    ]
    return _list_table(rows)


def _transform_earnings_calendar(data: list[dict]) -> str:
    if not data:
        return "(no earnings)"
    rows = [
        {
            "Date": e.get("date", ""),
            "Symbol": e.get("symbol", ""),
            "Hour": e.get("hour", ""),
            "EPS Est": _fmt_number(e.get("epsEstimate")),
            "EPS Act": _fmt_number(e.get("epsActual")),
            "Rev Est": _fmt_large(e.get("revenueEstimate")),
            "Rev Act": _fmt_large(e.get("revenueActual")),
        }
        for e in data
    ]
    return _list_table(rows)


def _transform_basic_financials(data: dict) -> str:
    if not data:
        return "(no data)"
    metric = data.get("metric", {})
    if not metric:
        return "(no metrics)"
    selected = {
        "P/E (TTM)": _fmt_number(metric.get("peNormalizedAnnual")),
        "P/B": _fmt_number(metric.get("pbAnnual")),
        "EPS (TTM)": _fmt_number(metric.get("epsNormalizedAnnual")),
        "Dividend Yield %": _fmt_number(metric.get("dividendYieldIndicatedAnnual")),
        "Beta": _fmt_number(metric.get("beta")),
        "52W High": _fmt_number(metric.get("52WeekHigh")),
        "52W Low": _fmt_number(metric.get("52WeekLow")),
        # Finnhub reports market cap in millions
        "Market Cap": _fmt_large(mc * 1e6) if (mc := metric.get("marketCapitalization")) else "",
        "ROE (TTM)": _fmt_number(metric.get("roeTTM")),
        "Debt/Equity": _fmt_number(metric.get("totalDebt/totalEquityAnnual")),
        "Current Ratio": _fmt_number(metric.get("currentRatioAnnual")),
        "Revenue/Share (TTM)": _fmt_number(metric.get("revenuePerShareTTM")),
    }
    return _kv_table({k: v for k, v in selected.items() if v})


def _transform_eps_estimates(data: list[dict]) -> str:
    if not data:
        return "(no estimates)"
    rows = [
        {
            "Period": e.get("period", ""),
            "Avg": _fmt_number(e.get("epsAvg")),
            "High": _fmt_number(e.get("epsHigh")),
            "Low": _fmt_number(e.get("epsLow")),
            "# Analysts": str(e.get("numberAnalysts", "")),
        }
        for e in data
    ]
    return _list_table(rows)


def _transform_recommendations(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Period": r.get("period", ""),
            "Strong Buy": str(r.get("strongBuy", "")),
            "Buy": str(r.get("buy", "")),
            "Hold": str(r.get("hold", "")),
            "Sell": str(r.get("sell", "")),
            "Strong Sell": str(r.get("strongSell", "")),
        }
        for r in data
    ]
    return _list_table(rows)


def _transform_price_target(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "Symbol": data.get("symbol"),
            "Target High": _fmt_number(data.get("targetHigh")),
            "Target Low": _fmt_number(data.get("targetLow")),
            "Target Mean": _fmt_number(data.get("targetMean")),
            "Target Median": _fmt_number(data.get("targetMedian")),
            "Last Updated": data.get("lastUpdated", ""),
        }
    )


def _transform_insider_transactions(data: list[dict]) -> str:
    if not data:
        return "(no transactions)"
    rows = [
        {
            "Date": t.get("transactionDate", ""),
            "Name": t.get("name", ""),
            "Share": _fmt_number(t.get("share"), 0),
            "Change": _fmt_number(t.get("change"), 0),
            "Price": _fmt_number(t.get("transactionPrice")),
            "Type": t.get("transactionCode", ""),
        }
        for t in data
    ]
    return _list_table(rows)


def _transform_peers(data: list[str]) -> str:
    if not data:
        return "(no peers)"
    rows = [[s] for s in data]
    return _md_table(["Symbol"], rows)


def _transform_finnhub_dividends(data: list[dict]) -> str:
    if not data:
        return "(no dividends)"
    rows = [
        {
            "Ex-Date": d.get("date", ""),
            "Pay Date": d.get("payDate", ""),
            "Record Date": d.get("recordDate", ""),
            "Amount": _fmt_number(d.get("amount"), 4),
            "Currency": d.get("currency", ""),
        }
        for d in data
    ]
    return _list_table(rows)


# ── FMP ──


def _transform_fmp_profile(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "Name": data.get("companyName"),
            "Symbol": data.get("symbol"),
            "Price": _fmt_number(data.get("price")),
            "Market Cap": _fmt_large(data.get("marketCap")),
            "Beta": _fmt_number(data.get("beta")),
            "Vol Avg": _fmt_large(data.get("averageVolume")),
            "Last Dividend": _fmt_number(data.get("lastDividend")),
            "52W Range": data.get("range", ""),
            "Sector": data.get("sector"),
            "Industry": data.get("industry"),
            "Exchange": data.get("exchange"),
            "CEO": data.get("ceo"),
        }
    )


def _transform_income_statement(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": s.get("date", ""),
            "Revenue": _fmt_large(s.get("revenue")),
            "Gross Profit": _fmt_large(s.get("grossProfit")),
            "Op Income": _fmt_large(s.get("operatingIncome")),
            "Net Income": _fmt_large(s.get("netIncome")),
            "EPS": _fmt_number(s.get("eps")),
            "EBITDA": _fmt_large(s.get("ebitda")),
        }
        for s in data
    ]
    return _list_table(rows)


def _transform_balance_sheet(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": s.get("date", ""),
            "Total Assets": _fmt_large(s.get("totalAssets")),
            "Total Liab": _fmt_large(s.get("totalLiabilities")),
            "Total Equity": _fmt_large(s.get("totalStockholdersEquity")),
            "Cash": _fmt_large(s.get("cashAndCashEquivalents")),
            "Total Debt": _fmt_large(s.get("totalDebt")),
        }
        for s in data
    ]
    return _list_table(rows)


def _transform_cash_flow(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": s.get("date", ""),
            "Operating CF": _fmt_large(s.get("operatingCashFlow")),
            "Capex": _fmt_large(s.get("capitalExpenditure")),
            "Free CF": _fmt_large(s.get("freeCashFlow")),
            "Dividends": _fmt_large(s.get("commonDividendsPaid")),
            "Buybacks": _fmt_large(s.get("commonStockRepurchased")),
        }
        for s in data
    ]
    return _list_table(rows)


def _transform_key_metrics(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": m.get("date", ""),
            "EV/EBITDA": _fmt_number(m.get("evToEBITDA")),
            "EV/Sales": _fmt_number(m.get("evToSales")),
            "ROE": _fmt_number(m.get("returnOnEquity")),
            "ROA": _fmt_number(m.get("returnOnAssets")),
            "Curr Ratio": _fmt_number(m.get("currentRatio")),
            "Net Debt/EBITDA": _fmt_number(m.get("netDebtToEBITDA")),
            "FCF Yield": _fmt_number(m.get("freeCashFlowYield"), 4),
        }
        for m in data
    ]
    return _list_table(rows)


def _transform_fmp_dividend_history(data: list[dict]) -> str:
    if not data:
        return "(no dividends)"
    rows = [
        {
            "Ex-Date": d.get("date", ""),
            "Pay Date": d.get("paymentDate", ""),
            "Record Date": d.get("recordDate", ""),
            "Declaration": d.get("declarationDate", ""),
            "Dividend": _fmt_number(d.get("dividend"), 4),
            "Adj Dividend": _fmt_number(d.get("adjDividend"), 4),
        }
        for d in data
    ]
    return _list_table(rows)


def _transform_fmp_earnings(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": e.get("date", ""),
            "Symbol": e.get("symbol", ""),
            "EPS Est": _fmt_number(e.get("epsEstimated")),
            "EPS Act": _fmt_number(e.get("epsActual")),
            "Rev Est": _fmt_large(e.get("revenueEstimated")),
            "Rev Act": _fmt_large(e.get("revenueActual")),
        }
        for e in data
    ]
    return _list_table(rows)


# ── FRED ──


def _transform_observations(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [{"Date": o.get("date", ""), "Value": o.get("value", "")} for o in data]
    return _list_table(rows)


def _transform_series_info(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "ID": data.get("id"),
            "Title": data.get("title"),
            "Frequency": data.get("frequency"),
            "Units": data.get("units"),
            "Seasonal Adj": data.get("seasonal_adjustment"),
            "Last Updated": data.get("last_updated"),
        }
    )


def _transform_releases(data: list[dict]) -> str:
    if not data:
        return "(no releases)"
    rows = [
        {
            "Release ID": str(r.get("release_id", "")),
            "Release": r.get("release_name", ""),
            "Date": r.get("date", ""),
        }
        for r in data
    ]
    return _list_table(rows)


def _transform_fred_search(data: list[dict]) -> str:
    if not data:
        return "(no results)"
    rows = [
        {
            "ID": s.get("id", ""),
            "Title": s.get("title", ""),
            "Frequency": s.get("frequency", ""),
            "Units": s.get("units", ""),
        }
        for s in data
    ]
    return _list_table(rows)


# ── Alpha Vantage ──


def _transform_sentiment(data: list[dict]) -> str:
    if not data:
        return "(no articles)"
    rows = [
        {
            "Date": a.get("time_published", "")[:16],
            "Title": (a.get("title", "") or "")[:80],
            "Source": a.get("source", ""),
            "Sentiment": _fmt_number(a.get("overall_sentiment_score"), 3),
            "Label": a.get("overall_sentiment_label", ""),
        }
        for a in data
    ]
    return _list_table(rows)


def _transform_movers(data: dict) -> str:
    if not data:
        return "(no data)"
    sections = []
    for key, title in [
        ("top_gainers", "Top Gainers"),
        ("top_losers", "Top Losers"),
        ("most_actively_traded", "Most Active"),
    ]:
        items = data.get(key, [])
        if items:
            rows = [
                {
                    "Ticker": m.get("ticker", ""),
                    "Price": m.get("price", ""),
                    "Change": m.get("change_amount", ""),
                    "Change %": m.get("change_percentage", ""),
                    "Volume": _fmt_large(m.get("volume")),
                }
                for m in items[:10]
            ]
            sections.append(f"### {title}\n\n{_list_table(rows)}")
    return "\n\n".join(sections) if sections else "(no data)"


# ── Transformer registry ────────────────────────────────────

TRANSFORMERS: dict[str, Callable[[Any], Any]] = {
    # Webull
    "/account/profile": _transform_account_profile,
    "/account/balance": _transform_account_balance,
    "/account/positions": _transform_account_positions,
    "/instrument/list": _transform_instruments,
    "/market-data/bars": _transform_bars,
    "/trade/instrument": _transform_trade_instrument,
    "/trade/calendar": _transform_trade_calendar,
    "/app/subscriptions/list": _transform_subscriptions,
    "/trade/orders/list-open": _transform_open_orders,
    "/trade/orders/list-today": _transform_today_orders,
    "/trade/order/detail": _transform_order_detail,
    "/trade/order/place": _transform_order_result,
    "/trade/order/replace": _transform_order_result,
    "/trade/order/cancel": _transform_order_result,
    # Tradier
    "tradier:expirations": _transform_option_expirations,
    "tradier:strikes": _transform_option_strikes,
    "tradier:chain": _transform_option_chain,
    "tradier:option-lookup": _transform_option_lookup,
    "tradier:history": _transform_tradier_history,
    "tradier:search": _transform_tradier_search,
    "tradier:quotes": _transform_tradier_quotes,
    "tradier:timesales": _transform_tradier_timesales,
    "tradier:clock": _transform_tradier_clock,
    "tradier:profile": _transform_tradier_profile,
    "tradier:balances": _transform_tradier_balances,
    "tradier:positions": _transform_tradier_positions,
    "tradier:orders": _transform_tradier_orders,
    "tradier:order-detail": _transform_tradier_order_detail,
    "tradier:gainloss": _transform_tradier_gainloss,
    "tradier:account-history": _transform_tradier_account_history,
    "tradier:place-order": _transform_tradier_place_order,
    "tradier:modify-order": _transform_tradier_modify_order,
    "tradier:cancel-order": _transform_tradier_cancel_order,
    # Finnhub
    "finnhub:company-news": _transform_company_news,
    "finnhub:market-news": _transform_market_news,
    "finnhub:economic-calendar": _transform_economic_calendar,
    "finnhub:earnings-calendar": _transform_earnings_calendar,
    "finnhub:basic-financials": _transform_basic_financials,
    "finnhub:eps-estimates": _transform_eps_estimates,
    "finnhub:recommendations": _transform_recommendations,
    "finnhub:price-target": _transform_price_target,
    "finnhub:insider-transactions": _transform_insider_transactions,
    "finnhub:peers": _transform_peers,
    "finnhub:dividends": _transform_finnhub_dividends,
    # FMP
    "fmp:profile": _transform_fmp_profile,
    "fmp:income-statement": _transform_income_statement,
    "fmp:balance-sheet": _transform_balance_sheet,
    "fmp:cash-flow": _transform_cash_flow,
    "fmp:key-metrics": _transform_key_metrics,
    "fmp:earnings-calendar": _transform_fmp_earnings,
    "fmp:dividend-history": _transform_fmp_dividend_history,
    # FRED
    "fred:observations": _transform_observations,
    "fred:series-info": _transform_series_info,
    "fred:releases": _transform_releases,
    "fred:search": _transform_fred_search,
    # Alpha Vantage
    "alphavantage:sentiment": _transform_sentiment,
    "alphavantage:movers": _transform_movers,
}


def _apply_field_filter(data: Any, fields: set[str]) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields}
    if isinstance(data, list):
        return [
            {k: v for k, v in item.items() if k in fields}
            for item in data
            if isinstance(item, dict)
        ]
    return data


def process(path: str, data: Any) -> Any:
    """Filter and transform an API response based on its endpoint path or logical key."""
    # Stage 1: field filtering
    fields = FIELD_FILTERS.get(path)
    if fields is not None:
        data = _apply_field_filter(data, fields)

    # Stage 2: transform to markdown table
    transformer = TRANSFORMERS.get(path)
    if transformer is not None:
        data = transformer(data)

    return data
