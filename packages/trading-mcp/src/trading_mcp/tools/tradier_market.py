import asyncio

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.helpers import _tradier

mcp = FastMCP("tradier-market-tools")


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
    session_filter: str = "open",
) -> str:
    """Get intraday time-and-sales tick data for a stock or option contract.
    Higher granularity than historical bars — useful for intraday analysis and charting.

    Returns: timestamp, last trade price, OHLC, and volume per interval.

    symbol: ticker or OCC option symbol (e.g. 'AAPL' or 'AAPL260417C00260000').
    interval: tick interval — '1min', '5min', '15min'. Default '5min'.
    start: start datetime (YYYY-MM-DD HH:MM). Defaults to market open today.
    end: end datetime (YYYY-MM-DD HH:MM). Defaults to now.
    session_filter: 'open' for regular hours only (default), 'all' for pre/post-market included.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (
        await _tradier(ctx).get(
            t.TIMESALES,
            t.GetTimesalesRequest(symbol, interval, start, end, session_filter),
        )
    ).to_output()


@mcp.tool()
async def get_vwap(
    ctx: Context,
    symbol: str,
    interval: str = "5min",
    session_filter: str = "open",
) -> str:
    """Compute intraday VWAP (Volume-Weighted Average Price) for a stock.

    VWAP shows where the majority of money changed hands. Institutional algorithms
    use it as a benchmark — they buy below VWAP and sell above it.

    Returns: current VWAP, price vs VWAP, time spent above/below, VWAP slope,
    and an intraday progression table.

    symbol: ticker symbol (e.g. 'SPY').
    interval: bar interval — '1min', '5min', '15min'. Default '5min'.
    session_filter: 'open' for regular hours only (default), 'all' for pre/post-market included.

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    ts_req = t.GetTimesalesRequest(symbol, interval, session_filter=session_filter)
    quote_resp, ts_resp = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.TIMESALES, ts_req),
    )

    if not ts_resp.ticks:
        return f"(no intraday data for {symbol})"

    last_price = 0.0
    if quote_resp.quotes:
        last_price = float(quote_resp.quotes[0].get("last") or 0)

    cum_vol = 0.0
    cum_tp_vol = 0.0
    above_count = 0
    below_count = 0
    vwap_values: list[float] = []
    rows: list[dict[str, str]] = []

    for tick in ts_resp.ticks:
        high = float(tick.get("high", 0))
        low = float(tick.get("low", 0))
        close = float(tick.get("close", 0))
        volume = float(tick.get("volume", 0))

        if volume == 0:
            vwap_values.append(vwap_values[-1] if vwap_values else close)
            continue

        typical_price = (high + low + close) / 3
        cum_tp_vol += typical_price * volume
        cum_vol += volume
        vwap = cum_tp_vol / cum_vol
        vwap_values.append(vwap)

        if close > vwap:
            above_count += 1
        elif close < vwap:
            below_count += 1

        rows.append(
            {
                "Time": tick.get("time", "")[-8:],
                "Close": fmt_number(close),
                "Volume": fmt_number(volume, 0),
                "VWAP": fmt_number(vwap),
                "Diff": f"{((close - vwap) / vwap) * 100:+.2f}%",
            }
        )

    if not vwap_values:
        return f"(no volume data for {symbol})"

    current_vwap = vwap_values[-1]
    total_bars = above_count + below_count

    # VWAP slope: compare last quarter vs first quarter
    quarter = max(1, len(vwap_values) // 4)
    early_vwap = sum(vwap_values[:quarter]) / quarter
    late_vwap = sum(vwap_values[-quarter:]) / quarter
    slope_pct = ((late_vwap - early_vwap) / early_vwap) * 100
    if slope_pct > 0.05:
        slope_label = "rising"
    elif slope_pct < -0.05:
        slope_label = "declining"
    else:
        slope_label = "flat"

    fallback_price = float(ts_resp.ticks[-1].get("close", 0))
    price_for_diff = last_price or fallback_price

    data: dict[str, str] = {
        "Price": fmt_number(price_for_diff),
        "VWAP": fmt_number(current_vwap),
    }
    diff_pct = ((price_for_diff - current_vwap) / current_vwap) * 100
    position = "above" if diff_pct > 0 else "below"
    data["Price vs VWAP"] = f"{position} by {abs(diff_pct):.2f}%"

    if total_bars > 0:
        above_pct = above_count / total_bars * 100
        data["Time Above VWAP"] = f"{above_pct:.0f}% ({above_count}/{total_bars} bars)"

    data["VWAP Slope"] = f"{slope_label} ({slope_pct:+.2f}%)"
    data["Cumulative Volume"] = fmt_number(cum_vol, 0)

    # Sample ~12 rows for the table to keep output concise
    if len(rows) > 12:
        step = len(rows) // 11
        sampled = [rows[i] for i in range(0, len(rows) - 1, step)]
        sampled.append(rows[-1])
    else:
        sampled = rows

    sections = [
        f"## {symbol} VWAP ({ts_resp.ticks[0].get('time', '')[:10]})",
        "",
        kv_table(data),
        "",
        "### Intraday Progression",
        list_table(sampled),
    ]
    return "\n".join(sections)


@mcp.tool()
async def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.CLOCK, t.EmptyRequest())).to_output()


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

    resp = await _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, period))
    bars = resp.days
    if not bars:
        return "(no historical data)"

    closes = [float(b["close"]) for b in bars]
    latest_price = closes[-1]
    latest_date = bars[-1].get("date", "")

    sections: list[str] = [f"## {symbol} Technical Indicators ({latest_date})"]
    sections.append(f"**Price:** {latest_price:,.2f}\n")

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
