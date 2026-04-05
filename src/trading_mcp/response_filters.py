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
        columns = list(items[0].keys())
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
    "/account/position/details": None,
    # Orders (read)
    "/trade/orders/list-open": None,
    "/trade/orders/list-today": None,
    "/trade/order/detail": None,
    # Order management
    "/openapi/account/orders/history": None,
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
    "/trade/security": None,
    "/trade/instrument/tradable/list": None,
    "/app/subscriptions/list": None,
    # Market data
    "/market-data/snapshot": None,
    "/instrument/list": None,
    "/market-data/bars": None,
    "/market-data/batch-bars": None,
    "/market-data/eod-bars": None,
    "/instrument/corp-action": None,
}


# ── Transformers ─────────────────────────────────────────────


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
                "Ask": _fmt_number(o.get("ask")),
                "Last": _fmt_number(o.get("last")),
                "Vol": str(o.get("volume", "")),
                "OI": str(o.get("open_interest", "")),
                "IV": _fmt_number(greeks.get("mid_iv"), 4),
                "Delta": _fmt_number(greeks.get("delta"), 4),
                "Gamma": _fmt_number(greeks.get("gamma"), 4),
                "Theta": _fmt_number(greeks.get("theta"), 4),
                "Vega": _fmt_number(greeks.get("vega"), 4),
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
            "URL": a.get("url", ""),
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


def _transform_company_profile(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "Name": data.get("name"),
            "Ticker": data.get("ticker"),
            "Exchange": data.get("exchange"),
            "Industry": data.get("finnhubIndustry"),
            "Market Cap": _fmt_large(data.get("marketCapitalization")),
            "IPO Date": data.get("ipo"),
            "Website": data.get("weburl"),
        }
    )


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
        "Market Cap": _fmt_large(metric.get("marketCapitalization")),
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


# ── FMP ──


def _transform_fmp_profile(data: dict) -> str:
    if not data:
        return "(no data)"
    return _kv_table(
        {
            "Name": data.get("companyName"),
            "Symbol": data.get("symbol"),
            "Price": _fmt_number(data.get("price")),
            "Market Cap": _fmt_large(data.get("mktCap")),
            "P/E": _fmt_number(data.get("pe") if data.get("pe") else None),
            "Beta": _fmt_number(data.get("beta")),
            "Vol Avg": _fmt_large(data.get("volAvg")),
            "Div Yield": _fmt_number(data.get("lastDiv")),
            "52W Range": data.get("range", ""),
            "Sector": data.get("sector"),
            "Industry": data.get("industry"),
            "Exchange": data.get("exchangeShortName"),
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
            "Dividends": _fmt_large(s.get("dividendsPaid")),
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
            "P/E": _fmt_number(m.get("peRatio")),
            "P/B": _fmt_number(m.get("pbRatio")),
            "P/S": _fmt_number(m.get("priceToSalesRatio")),
            "EV/EBITDA": _fmt_number(m.get("enterpriseValueOverEBITDA")),
            "ROE": _fmt_number(m.get("roe")),
            "D/E": _fmt_number(m.get("debtToEquity")),
            "Curr Ratio": _fmt_number(m.get("currentRatio")),
        }
        for m in data
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
            "EPS Act": _fmt_number(e.get("eps")),
            "Rev Est": _fmt_large(e.get("revenueEstimated")),
            "Rev Act": _fmt_large(e.get("revenue")),
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
    # Tradier
    "tradier:expirations": _transform_option_expirations,
    "tradier:strikes": _transform_option_strikes,
    "tradier:chain": _transform_option_chain,
    # Finnhub
    "finnhub:company-news": _transform_company_news,
    "finnhub:market-news": _transform_market_news,
    "finnhub:economic-calendar": _transform_economic_calendar,
    "finnhub:earnings-calendar": _transform_earnings_calendar,
    "finnhub:company-profile": _transform_company_profile,
    "finnhub:basic-financials": _transform_basic_financials,
    "finnhub:eps-estimates": _transform_eps_estimates,
    "finnhub:recommendations": _transform_recommendations,
    # FMP
    "fmp:profile": _transform_fmp_profile,
    "fmp:income-statement": _transform_income_statement,
    "fmp:balance-sheet": _transform_balance_sheet,
    "fmp:cash-flow": _transform_cash_flow,
    "fmp:key-metrics": _transform_key_metrics,
    "fmp:earnings-calendar": _transform_fmp_earnings,
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
