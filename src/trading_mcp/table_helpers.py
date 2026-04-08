"""Markdown table helper functions for API response rendering.

These helpers convert structured data into markdown tables for clean,
unambiguous LLM output. Used by response models in endpoints/*.py.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# ── Markdown table helpers ───────────────────────────────────


def md_table(headers: list[str], rows: list[list[str]]) -> str:
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


def kv_table(data: dict, key_header: str = "Field", val_header: str = "Value") -> str:
    """Build a two-column key/value markdown table from a dict."""
    headers = [key_header, val_header]
    rows = [[str(k), str(v)] for k, v in data.items() if v is not None]
    return md_table(headers, rows)


def list_table(items: list[dict], columns: list[str] | None = None) -> str:
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
    return md_table(columns, rows)


def fmt_number(val: Any, decimals: int = 2) -> str:
    """Format a number with commas and fixed decimals, or return '' if None."""
    if val is None:
        return ""
    try:
        return f"{float(val):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def fmt_large(val: Any) -> str:
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


def unix_to_date(ts: Any) -> str:
    """Convert unix timestamp to YYYY-MM-DD HH:MM."""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)



# ── Transformers ─────────────────────────────────────────────


# ── Webull ──


def _transform_account_list(data: list[dict]) -> str:
    if not data:
        return "(no accounts)"
    rows = [
        {
            "Account ID": a.get("account_id", ""),
            "Account Number": a.get("account_number", ""),
            "Type": a.get("account_type", ""),
            "Label": a.get("account_label", ""),
        }
        for a in data
    ]
    return list_table(rows)


def _transform_account_balance(data: dict) -> str:
    if not data:
        return "(no data)"
    assets = data.get("account_currency_assets", [])
    usd = assets[0] if assets else {}
    selected = {
        "Net Liquidation": fmt_number(data.get("total_net_liquidation_value")),
        "Market Value": fmt_number(data.get("total_market_value")),
        "Cash Balance": fmt_number(data.get("total_cash_balance")),
        "Day P&L": fmt_number(data.get("total_day_profit_loss")),
        "Unrealized P&L": fmt_number(data.get("total_unrealized_profit_loss")),
        "Day Trades Left": data.get("day_trades_left"),
        "Cash Power": fmt_number(usd.get("cash_power")),
        "Margin Power": fmt_number(usd.get("margin_power")),
        "Margin Ratio": data.get("margin_ratio"),
        "Available Withdrawal": fmt_number(usd.get("available_withdrawal")),
    }
    return kv_table({k: v for k, v in selected.items() if v and v != "0.00"})


def _transform_account_positions(data: list[dict]) -> str:
    if not data:
        return "(no positions)"
    has_options = any(p.get("legs") for p in data)
    rows = []
    for p in data:
        pnl_rate = p.get("unrealized_profit_loss_rate")
        pnl_pct = fmt_number(float(pnl_rate) * 100) if pnl_rate else ""
        row: dict[str, str] = {
            "Symbol": p.get("symbol", ""),
            "Qty": p.get("quantity", ""),
            "Cost": fmt_number(p.get("cost_price")),
            "Last": fmt_number(p.get("last_price")),
            "Mkt Val": fmt_number(p.get("market_value")),
            "P&L": fmt_number(p.get("unrealized_profit_loss")),
            "P&L %": pnl_pct,
        }
        if has_options:
            # Find the OPTION leg (covered stocks have both EQUITY + OPTION legs)
            option_leg = None
            for leg in p.get("legs", []):
                if leg.get("instrument_type") == "OPTION":
                    option_leg = leg
                    break
            if option_leg:
                row["Option"] = option_leg.get("option_type", "")
                row["Strike"] = fmt_number(option_leg.get("option_exercise_price"))
                row["Exp"] = option_leg.get("option_expire_date", "")
            else:
                row["Option"] = ""
                row["Strike"] = ""
                row["Exp"] = ""
            row["Strategy"] = p.get("option_strategy", "")
        rows.append(row)
    cols = ["Symbol", "Qty", "Cost", "Last", "Mkt Val", "P&L", "P&L %"]
    if has_options:
        cols += ["Option", "Strike", "Exp", "Strategy"]
    return list_table(rows, cols)


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
            "Shortable": str(i.get("shortable", "")),
            "Fractionable": str(i.get("fractionable", "")),
        }
        for i in data
    ]
    return list_table(rows)


def _transform_order_list(data: list[dict]) -> str:
    if not data:
        return "(no orders)"
    rows = []
    for combo in data:
        orders = combo.get("orders", [])
        for o in orders:
            row: dict[str, str] = {
                "Order ID": o.get("client_order_id", ""),
                "Symbol": o.get("symbol", ""),
                "Side": o.get("side", ""),
                "Type": o.get("order_type", ""),
                "Instrument": o.get("instrument_type", ""),
                "Qty": o.get("total_quantity", ""),
                "Filled": o.get("filled_quantity", ""),
                "Price": fmt_number(o.get("limit_price")),
                "Status": o.get("status", ""),
                "Time": (o.get("place_time_at") or "")[:19],
            }
            legs = o.get("legs", [])
            if legs:
                leg = legs[0]
                row["Strike"] = fmt_number(leg.get("strike_price"))
                row["Exp"] = leg.get("option_expire_date", "")
                row["Option"] = leg.get("option_type", "")
            rows.append(row)
    return list_table(rows) if rows else "(no orders)"


def _transform_order_detail(data: dict) -> str:
    if not data:
        return "(no data)"
    orders = data.get("orders", [])
    if not orders:
        return "(no data)"
    sections = []
    for o in orders:
        details: dict[str, str | None] = {
            "Order ID": o.get("client_order_id"),
            "Symbol": o.get("symbol"),
            "Side": o.get("side"),
            "Type": o.get("order_type"),
            "Instrument": o.get("instrument_type"),
            "Qty": o.get("total_quantity"),
            "Filled": o.get("filled_quantity"),
            "Fill Price": fmt_number(o.get("filled_price")),
            "Limit": fmt_number(o.get("limit_price")),
            "Stop": fmt_number(o.get("stop_price")),
            "Status": o.get("status"),
            "TIF": o.get("time_in_force"),
            "Session": o.get("support_trading_session"),
            "Placed": (o.get("place_time_at") or "")[:19] or None,
            "Filled At": (o.get("filled_time_at") or "")[:19] or None,
        }
        legs = o.get("legs", [])
        if legs:
            leg = legs[0]
            details["Option"] = leg.get("option_type")
            details["Strike"] = fmt_number(leg.get("strike_price"))
            details["Exp"] = leg.get("option_expire_date")
        sections.append(kv_table({k: v for k, v in details.items() if v}))
    return "\n\n".join(sections)


def _transform_order_result(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(data)


# ── Tradier ──


def _transform_option_expirations(data: list[str]) -> str:
    if not data:
        return "(no expirations)"
    rows = [[d] for d in data]
    return md_table(["Expiration"], rows)


def _transform_option_strikes(data: list) -> str:
    if not data:
        return "(no strikes)"
    rows = [[fmt_number(s)] for s in data]
    return md_table(["Strike"], rows)


def _transform_option_lookup(data: list) -> str:
    if not data:
        return "(no options)"
    rows = [[str(o)] for o in data]
    return md_table(["Option Symbol"], rows)


def _transform_tradier_history(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": d.get("date", ""),
            "Open": fmt_number(d.get("open")),
            "High": fmt_number(d.get("high")),
            "Low": fmt_number(d.get("low")),
            "Close": fmt_number(d.get("close")),
            "Volume": fmt_large(d.get("volume")),
        }
        for d in data
    ]
    return list_table(rows)


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
    return list_table(rows)


def _transform_tradier_quotes(data: list[dict]) -> str:
    if not data:
        return "(no quotes)"
    rows = []
    for q in data:
        is_option = q.get("option_type") is not None
        row: dict[str, str] = {"Symbol": q.get("symbol", "")}
        if is_option:
            row["Type"] = q.get("option_type", "")
            row["Strike"] = fmt_number(q.get("strike"))
            row["Exp"] = q.get("expiration_date", "")
        row |= {
            "Last": fmt_number(q.get("last")),
            "Bid": fmt_number(q.get("bid")),
            "Bid Sz": fmt_large(q.get("bidsize")),
            "Ask": fmt_number(q.get("ask")),
            "Ask Sz": fmt_large(q.get("asksize")),
            "Volume": fmt_large(q.get("volume")),
            "Change": fmt_number(q.get("change")),
            "Change %": fmt_number(q.get("change_percentage")),
        }
        if is_option:
            row["OI"] = fmt_large(q.get("open_interest"))
        else:
            row |= {
                "Prev Close": fmt_number(q.get("prevclose")),
                "Open": fmt_number(q.get("open")),
                "High": fmt_number(q.get("high")),
                "Low": fmt_number(q.get("low")),
                "Avg Vol": fmt_large(q.get("average_volume")),
                "52W High": fmt_number(q.get("week_52_high")),
                "52W Low": fmt_number(q.get("week_52_low")),
            }
        greeks = q.get("greeks")
        if greeks:
            row |= {
                "IV": fmt_number(greeks.get("mid_iv"), 4),
                "Delta": fmt_number(greeks.get("delta"), 4),
                "Gamma": fmt_number(greeks.get("gamma"), 4),
                "Theta": fmt_number(greeks.get("theta"), 4),
                "Vega": fmt_number(greeks.get("vega"), 4),
                "Rho": fmt_number(greeks.get("rho"), 4),
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
    return list_table(rows, cols)


def _transform_tradier_timesales(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Time": t.get("time", "")[:19],
            "Price": fmt_number(t.get("price")),
            "Open": fmt_number(t.get("open")),
            "High": fmt_number(t.get("high")),
            "Low": fmt_number(t.get("low")),
            "Close": fmt_number(t.get("close")),
            "Volume": fmt_large(t.get("volume")),
        }
        for t in data
    ]
    return list_table(rows)


def _transform_tradier_clock(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(
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
    return list_table(rows)


def _transform_tradier_balances(data: dict) -> str:
    if not data:
        return "(no data)"
    selected = {
        "Account": data.get("account_number"),
        "Account Type": data.get("account_type"),
        "Total Equity": fmt_number(data.get("total_equity")),
        "Total Cash": fmt_number(data.get("total_cash")),
        "Market Value": fmt_number(data.get("market_value")),
        "Option Value": fmt_number(data.get("option_long_value")),
        "Stock Buying Power": fmt_number(data.get("stock_buying_power")),
        "Option Buying Power": fmt_number(data.get("option_buying_power")),
        "Pending Cash": fmt_number(data.get("pending_cash")),
        "Uncleared Funds": fmt_number(data.get("uncleared_funds")),
    }
    return kv_table({k: v for k, v in selected.items() if v})


def _transform_tradier_positions(data: list[dict]) -> str:
    if not data:
        return "(no positions)"
    rows = [
        {
            "Symbol": p.get("symbol", ""),
            "Qty": fmt_number(p.get("quantity"), 0),
            "Cost Basis": fmt_number(p.get("cost_basis")),
            "Date Acquired": p.get("date_acquired", ""),
        }
        for p in data
    ]
    return list_table(rows)


def _transform_tradier_orders(data: list[dict]) -> str:
    if not data:
        return "(no orders)"
    rows = [
        {
            "ID": str(o.get("id", "")),
            "Class": o.get("class", ""),
            "Symbol": o.get("symbol", ""),
            "Side": o.get("side", ""),
            "Qty": fmt_number(o.get("quantity"), 0),
            "Type": o.get("type", ""),
            "Price": fmt_number(o.get("price")),
            "Stop": fmt_number(o.get("stop_price")),
            "Status": o.get("status", ""),
            "Duration": o.get("duration", ""),
            "Created": (o.get("create_date") or "")[:10],
        }
        for o in data
    ]
    return list_table(rows)


def _transform_tradier_order_detail(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(data)


def _transform_tradier_gainloss(data: list[dict]) -> str:
    if not data:
        return "(no closed positions)"
    rows = [
        {
            "Symbol": g.get("symbol", ""),
            "Qty": fmt_number(g.get("quantity"), 0),
            "Open Date": (g.get("open_date") or "")[:10],
            "Close Date": (g.get("close_date") or "")[:10],
            "Term": g.get("term", ""),
            "Cost": fmt_number(g.get("cost")),
            "Proceeds": fmt_number(g.get("proceeds")),
            "Gain/Loss": fmt_number(g.get("gain_loss")),
            "G/L %": fmt_number(g.get("gain_loss_percent")),
        }
        for g in data
    ]
    return list_table(rows)


def _transform_tradier_account_history(data: list[dict]) -> str:
    if not data:
        return "(no activity)"
    rows = [
        {
            "Date": (e.get("date") or "")[:10],
            "Type": e.get("type", ""),
            "Amount": fmt_number(e.get("amount")),
            "Description": e.get("description", ""),
        }
        for e in data
    ]
    return list_table(rows)


def _transform_tradier_place_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(data)


def _transform_tradier_modify_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(data)


def _transform_tradier_cancel_order(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(data)


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
                "Strike": fmt_number(o.get("strike")),
                "Bid": fmt_number(o.get("bid")),
                "Bid Sz": fmt_large(o.get("bidsize")),
                "Ask": fmt_number(o.get("ask")),
                "Ask Sz": fmt_large(o.get("asksize")),
                "Last": fmt_number(o.get("last")),
                "Change": fmt_number(o.get("change")),
                "Change %": fmt_number(o.get("change_percentage")),
                "Vol": fmt_large(o.get("volume")),
                "OI": fmt_large(o.get("open_interest")),
                "IV": fmt_number(greeks.get("mid_iv"), 4),
                "Delta": fmt_number(greeks.get("delta"), 4),
                "Gamma": fmt_number(greeks.get("gamma"), 4),
                "Theta": fmt_number(greeks.get("theta"), 4),
                "Vega": fmt_number(greeks.get("vega"), 4),
                "Rho": fmt_number(greeks.get("rho"), 4),
            }
        )
    return list_table(rows)


# ── Finnhub ──


def _transform_company_news(data: list[dict]) -> str:
    if not data:
        return "(no news)"
    rows = [
        {
            "Date": unix_to_date(a.get("datetime")),
            "Headline": a.get("headline", ""),
            "Source": a.get("source", ""),
        }
        for a in data
    ]
    return list_table(rows)


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
    return list_table(rows)


def _transform_earnings_calendar(data: list[dict]) -> str:
    if not data:
        return "(no earnings)"
    rows = [
        {
            "Date": e.get("date", ""),
            "Symbol": e.get("symbol", ""),
            "Hour": e.get("hour", ""),
            "EPS Est": fmt_number(e.get("epsEstimate")),
            "EPS Act": fmt_number(e.get("epsActual")),
            "Rev Est": fmt_large(e.get("revenueEstimate")),
            "Rev Act": fmt_large(e.get("revenueActual")),
        }
        for e in data
    ]
    return list_table(rows)


def _transform_basic_financials(data: dict) -> str:
    if not data:
        return "(no data)"
    metric = data.get("metric", {})
    if not metric:
        return "(no metrics)"
    selected = {
        "P/E (TTM)": fmt_number(metric.get("peNormalizedAnnual")),
        "P/B": fmt_number(metric.get("pbAnnual")),
        "EPS (TTM)": fmt_number(metric.get("epsNormalizedAnnual")),
        "Dividend Yield %": fmt_number(metric.get("dividendYieldIndicatedAnnual")),
        "Beta": fmt_number(metric.get("beta")),
        "52W High": fmt_number(metric.get("52WeekHigh")),
        "52W Low": fmt_number(metric.get("52WeekLow")),
        # Finnhub reports market cap in millions
        "Market Cap": fmt_large(mc * 1e6) if (mc := metric.get("marketCapitalization")) else "",
        "ROE (TTM)": fmt_number(metric.get("roeTTM")),
        "Debt/Equity": fmt_number(metric.get("totalDebt/totalEquityAnnual")),
        "Current Ratio": fmt_number(metric.get("currentRatioAnnual")),
        "Revenue/Share (TTM)": fmt_number(metric.get("revenuePerShareTTM")),
    }
    return kv_table({k: v for k, v in selected.items() if v})


def _transform_eps_estimates(data: list[dict]) -> str:
    if not data:
        return "(no estimates)"
    rows = [
        {
            "Period": e.get("period", ""),
            "Avg": fmt_number(e.get("epsAvg")),
            "High": fmt_number(e.get("epsHigh")),
            "Low": fmt_number(e.get("epsLow")),
            "# Analysts": str(e.get("numberAnalysts", "")),
        }
        for e in data
    ]
    return list_table(rows)


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
    return list_table(rows)


def _transform_price_target(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(
        {
            "Symbol": data.get("symbol"),
            "Target High": fmt_number(data.get("targetHigh")),
            "Target Low": fmt_number(data.get("targetLow")),
            "Target Mean": fmt_number(data.get("targetMean")),
            "Target Median": fmt_number(data.get("targetMedian")),
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
            "Share": fmt_number(t.get("share"), 0),
            "Change": fmt_number(t.get("change"), 0),
            "Price": fmt_number(t.get("transactionPrice")),
            "Type": t.get("transactionCode", ""),
        }
        for t in data
    ]
    return list_table(rows)


def _transform_peers(data: list[str]) -> str:
    if not data:
        return "(no peers)"
    rows = [[s] for s in data]
    return md_table(["Symbol"], rows)


def _transform_finnhub_dividends(data: list[dict]) -> str:
    if not data:
        return "(no dividends)"
    rows = [
        {
            "Ex-Date": d.get("date", ""),
            "Pay Date": d.get("payDate", ""),
            "Record Date": d.get("recordDate", ""),
            "Amount": fmt_number(d.get("amount"), 4),
            "Currency": d.get("currency", ""),
        }
        for d in data
    ]
    return list_table(rows)


# ── FMP ──


def _transform_fmp_profile(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(
        {
            "Name": data.get("companyName"),
            "Symbol": data.get("symbol"),
            "Price": fmt_number(data.get("price")),
            "Market Cap": fmt_large(data.get("marketCap")),
            "Beta": fmt_number(data.get("beta")),
            "Vol Avg": fmt_large(data.get("averageVolume")),
            "Last Dividend": fmt_number(data.get("lastDividend")),
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
            "Revenue": fmt_large(s.get("revenue")),
            "Gross Profit": fmt_large(s.get("grossProfit")),
            "Op Income": fmt_large(s.get("operatingIncome")),
            "Net Income": fmt_large(s.get("netIncome")),
            "EPS": fmt_number(s.get("eps")),
            "EBITDA": fmt_large(s.get("ebitda")),
        }
        for s in data
    ]
    return list_table(rows)


def _transform_balance_sheet(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": s.get("date", ""),
            "Total Assets": fmt_large(s.get("totalAssets")),
            "Total Liab": fmt_large(s.get("totalLiabilities")),
            "Total Equity": fmt_large(s.get("totalStockholdersEquity")),
            "Cash": fmt_large(s.get("cashAndCashEquivalents")),
            "Total Debt": fmt_large(s.get("totalDebt")),
        }
        for s in data
    ]
    return list_table(rows)


def _transform_cash_flow(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": s.get("date", ""),
            "Operating CF": fmt_large(s.get("operatingCashFlow")),
            "Capex": fmt_large(s.get("capitalExpenditure")),
            "Free CF": fmt_large(s.get("freeCashFlow")),
            "Dividends": fmt_large(s.get("commonDividendsPaid")),
            "Buybacks": fmt_large(s.get("commonStockRepurchased")),
        }
        for s in data
    ]
    return list_table(rows)


def _transform_key_metrics(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": m.get("date", ""),
            "EV/EBITDA": fmt_number(m.get("evToEBITDA")),
            "EV/Sales": fmt_number(m.get("evToSales")),
            "ROE": fmt_number(m.get("returnOnEquity")),
            "ROA": fmt_number(m.get("returnOnAssets")),
            "Curr Ratio": fmt_number(m.get("currentRatio")),
            "Net Debt/EBITDA": fmt_number(m.get("netDebtToEBITDA")),
            "FCF Yield": fmt_number(m.get("freeCashFlowYield"), 4),
        }
        for m in data
    ]
    return list_table(rows)


def _transform_fmp_dividend_history(data: list[dict]) -> str:
    if not data:
        return "(no dividends)"
    rows = [
        {
            "Ex-Date": d.get("date", ""),
            "Pay Date": d.get("paymentDate", ""),
            "Record Date": d.get("recordDate", ""),
            "Declaration": d.get("declarationDate", ""),
            "Dividend": fmt_number(d.get("dividend"), 4),
            "Adj Dividend": fmt_number(d.get("adjDividend"), 4),
        }
        for d in data
    ]
    return list_table(rows)


def _transform_fmp_earnings(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [
        {
            "Date": e.get("date", ""),
            "Symbol": e.get("symbol", ""),
            "EPS Est": fmt_number(e.get("epsEstimated")),
            "EPS Act": fmt_number(e.get("epsActual")),
            "Rev Est": fmt_large(e.get("revenueEstimated")),
            "Rev Act": fmt_large(e.get("revenueActual")),
        }
        for e in data
    ]
    return list_table(rows)


# ── FRED ──


def _transform_observations(data: list[dict]) -> str:
    if not data:
        return "(no data)"
    rows = [{"Date": o.get("date", ""), "Value": o.get("value", "")} for o in data]
    return list_table(rows)


def _transform_series_info(data: dict) -> str:
    if not data:
        return "(no data)"
    return kv_table(
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
    return list_table(rows)


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
    return list_table(rows)


# ── Alpha Vantage ──


def _transform_sentiment(data: list[dict]) -> str:
    if not data:
        return "(no articles)"
    rows = [
        {
            "Date": a.get("time_published", "")[:16],
            "Title": (a.get("title", "") or "")[:80],
            "Source": a.get("source", ""),
            "Sentiment": fmt_number(a.get("overall_sentiment_score"), 3),
            "Label": a.get("overall_sentiment_label", ""),
        }
        for a in data
    ]
    return list_table(rows)


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
                    "Volume": fmt_large(m.get("volume")),
                }
                for m in items[:10]
            ]
            sections.append(f"### {title}\n\n{list_table(rows)}")
    return "\n\n".join(sections) if sections else "(no data)"


# ── Transformer registry ────────────────────────────────────

TRANSFORMERS: dict[str, Callable[[Any], str]] = {
    # Webull
    "/openapi/account/list": _transform_account_list,
    "/openapi/assets/balance": _transform_account_balance,
    "/openapi/assets/positions": _transform_account_positions,
    "/openapi/instrument/stock/list": _transform_instruments,
    "/openapi/trade/order/open": _transform_order_list,
    "/openapi/trade/order/history": _transform_order_list,
    "/openapi/trade/order/detail": _transform_order_detail,
    "/openapi/trade/order/preview": _transform_order_result,
    "/openapi/trade/order/place": _transform_order_result,
    "/openapi/trade/order/replace": _transform_order_result,
    "/openapi/trade/order/cancel": _transform_order_result,
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


def process(path: str, data: Any) -> str:
    """Transform an API response based on its endpoint path or logical key."""
    transformer = TRANSFORMERS.get(path)
    if transformer is not None:
        return transformer(data)

    return json.dumps(data, indent=2, default=str)
